import { useEffect, useMemo, useRef, useState } from "react";
import { api, CLAUSE_LABEL, type Clause } from "../api";
import { Card, ConfidenceBar, cx, ErrorBox, Icon, Pill, SeverityPill, Spinner, StatusPill, useToast } from "../components/ui";
import { useAsync } from "../useAsync";

type Seg = { text: string; clause?: Clause };

/** Split the parsed text into plain / highlighted segments using each clause's source snippet. */
function segments(text: string, clauses: Clause[]): Seg[] {
  const hits: { start: number; end: number; clause: Clause }[] = [];
  for (const c of clauses) {
    const s = c.source_snippet?.trim();
    if (!s || s.length < 12) continue;
    const i = text.indexOf(s);
    if (i >= 0) hits.push({ start: i, end: i + s.length, clause: c });
  }
  hits.sort((a, b) => a.start - b.start || b.end - a.end);
  const out: Seg[] = [];
  let pos = 0;
  for (const h of hits) {
    if (h.start < pos) continue; // overlapping snippet: keep the first
    if (h.start > pos) out.push({ text: text.slice(pos, h.start) });
    out.push({ text: text.slice(h.start, h.end), clause: h.clause });
    pos = h.end;
  }
  out.push({ text: text.slice(pos) });
  return out;
}

export default function DocDetail({ docId, focus, go }: { docId: string; focus?: string; go: (h: string) => void }) {
  const { data, error, loading, reload } = useAsync(() => api.document(docId), [docId]);
  const [active, setActive] = useState<string | undefined>(focus);
  const textRef = useRef<HTMLDivElement>(null);
  const segs = useMemo(() => (data?.full_text ? segments(data.full_text, data.clauses) : []), [data]);

  useEffect(() => {
    if (!active || !textRef.current) return;
    const el = textRef.current.querySelector(`[data-clause="${active}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    document.getElementById(`card-${active}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active, segs]);

  if (loading && !data) return <Spinner label="Loading document" />;
  if (error) return <ErrorBox e={error} />;
  const d = data!;
  const head = d.clauses[0];
  const high = d.clauses.filter((c) => c.severity === "high").length;
  const pending = d.clauses.filter((c) => c.status === "pending").length;
  const order = { high: 0, medium: 1, low: 2, none: 3 } as Record<string, number>;
  const sorted = [...d.clauses].sort((a, b) => (order[a.severity] - order[b.severity]) || a.clause_type.localeCompare(b.clause_type));

  return (
    <div className="space-y-5">
      <button onClick={() => go("#/documents")} className="flex items-center gap-1 text-sm text-slate-500 hover:text-indigo-600"><Icon.arrowLeft /> All documents</button>
      <div className="rounded-2xl bg-gradient-to-br from-slate-900 to-indigo-900 p-6 text-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-md bg-white/10 px-2 py-0.5">{head.contract_type}</span>
          <span className="rounded-md bg-white/10 px-2 py-0.5">{head.matter_id} · {head.matter_team}</span>
          {d.page_count && <span className="rounded-md bg-white/10 px-2 py-0.5">{d.page_count} pages</span>}
        </div>
        <h2 className="mt-3 text-xl font-semibold">{head.doc_title}</h2>
        <p className="mt-1 text-sm text-indigo-200">Parties: {d.party_name ?? "—"}</p>
        <div className="mt-4 flex gap-6 text-sm">
          <span><b className="text-2xl font-semibold">{d.clauses.length}</b> clauses</span>
          <span><b className="text-2xl font-semibold text-rose-300">{high}</b> high risk</span>
          <span><b className="text-2xl font-semibold text-indigo-200">{pending}</b> pending review</span>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_28rem]">
        <Card title="Contract text" action={<span className="text-xs text-slate-400">highlights = AI source citations · click a card to jump</span>}>
          <div ref={textRef} className="doc-text max-h-[70vh] overflow-y-auto whitespace-pre-wrap pr-2 text-[15px] leading-7 text-slate-700">
            {!d.full_text && <p className="text-slate-400">Parsed text is not visible to you (Unity Catalog row filter).</p>}
            {segs.map((s, i) => s.clause
              ? <mark key={i} data-clause={s.clause.clause_id} onClick={() => setActive(s.clause!.clause_id)}
                  className={cx("snip cursor-pointer", `snip-${s.clause.severity}`, active === s.clause.clause_id && "snip-active")}
                  title={CLAUSE_LABEL[s.clause.clause_type]}>{s.text}</mark>
              : <span key={i}>{s.text}</span>)}
          </div>
        </Card>
        <div className="max-h-[calc(70vh+4rem)] space-y-3 overflow-y-auto pr-1">
          {sorted.map((c) => <ClauseCard key={c.clause_id} c={c} active={active === c.clause_id} onFocus={() => setActive(c.clause_id)} onChanged={reload} />)}
        </div>
      </div>
    </div>
  );
}

function ClauseCard({ c, active, onFocus, onChanged }: { c: Clause; active: boolean; onFocus: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(c.current_value ?? "");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<{ duration_ms: number; status: string }>) => {
    setBusy(true);
    try { const r = await fn(); toast(`Clause ${r.status} · saved to Lakebase in ${r.duration_ms.toFixed(0)} ms`); setEditing(false); onChanged(); }
    catch (e) { toast(String((e as Error).message), "err"); }
    finally { setBusy(false); }
  };
  const done = c.status === "approved" || c.status === "overridden";
  return (
    <div id={`card-${c.clause_id}`} onClick={onFocus}
      className={cx("rounded-2xl bg-white p-4 shadow-sm ring-1 transition", active ? "ring-2 ring-indigo-500" : "ring-slate-200/70 hover:ring-slate-300")}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="font-semibold text-slate-800">{CLAUSE_LABEL[c.clause_type] ?? c.clause_type}</h4>
        <div className="flex items-center gap-1.5"><SeverityPill s={c.severity} /><StatusPill s={c.status} /></div>
      </div>
      <p className="mt-2 break-words text-sm text-slate-700">{c.current_value}</p>
      {c.status === "overridden" && c.extracted_value !== c.current_value &&
        <p className="mt-1 text-xs text-slate-400 line-through">{c.normalized_value}</p>}
      <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">confidence <ConfidenceBar v={Number(c.confidence)} /></div>
      {c.risk_explanation && (
        <div className="mt-3 flex gap-2 rounded-xl bg-rose-50/70 p-3 text-sm text-rose-900 ring-1 ring-rose-100">
          <span className="text-rose-500"><Icon.sparkle /></span>
          <p><span className="font-semibold">{c.top_rule_id}</span> · {c.risk_explanation}</p>
        </div>
      )}
      {c.source_snippet && <blockquote className="mt-3 border-l-2 border-slate-200 pl-3 text-xs italic leading-5 text-slate-500 line-clamp-4">“{c.source_snippet}”</blockquote>}

      {editing ? (
        <div className="mt-3 space-y-2" onClick={(e) => e.stopPropagation()}>
          <textarea value={val} onChange={(e) => setVal(e.target.value)} rows={2}
            className="w-full rounded-lg border-0 bg-slate-50 p-2 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-indigo-500" />
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Reason for override (required)"
            className="w-full rounded-lg border-0 bg-slate-50 p-2 text-sm ring-1 ring-slate-200 focus:ring-2 focus:ring-indigo-500" />
          <div className="flex justify-end gap-2">
            <button onClick={() => setEditing(false)} className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">Cancel</button>
            <button disabled={busy || !val.trim() || !comment.trim()} onClick={() => act(() => api.override(c.clause_id, val, comment))}
              className="rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:opacity-40">Save override</button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex items-center justify-between" onClick={(e) => e.stopPropagation()}>
          <span className="text-xs text-slate-400">{c.reviews.length ? `last: ${c.reviews[c.reviews.length - 1].action} by ${c.reviews[c.reviews.length - 1].reviewer}` : ""}</span>
          <div className="flex gap-2">
            <button disabled={busy} onClick={() => setEditing(true)}
              className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"><Icon.edit />Override</button>
            <button disabled={busy || done} onClick={() => act(() => api.approve(c.clause_id))}
              className="flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:opacity-40"><Icon.check />Approve</button>
          </div>
        </div>
      )}
      {c.reviews.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-slate-100 pt-2">
          {c.reviews.map((r) => (
            <li key={r.review_id} className="text-xs text-slate-500">
              <Pill className={r.action === "override" ? "bg-violet-50 text-violet-700 ring-violet-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}>{r.action}</Pill>
              <span className="ml-2">{r.reviewer}</span> · {new Date(r.reviewed_at).toLocaleString()}{r.comment ? ` — ${r.comment}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
