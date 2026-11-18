import { api } from "../api";
import { cx, ErrorBox, Spinner } from "../components/ui";
import { useAsync } from "../useAsync";

const RANK = ["none", "low", "medium", "high"];
const BAR: Record<string, string> = { high: "bg-rose-500", medium: "bg-amber-400", low: "bg-yellow-300", none: "bg-slate-300" };

export default function Documents({ go }: { go: (h: string) => void }) {
  const { data, error, loading } = useAsync(api.documents, []);
  if (loading && !data) return <Spinner label="Loading documents" />;
  if (error) return <ErrorBox e={error} />;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {data!.map((d) => {
        const sev = RANK[d.sev_rank] ?? "none";
        const pct = Math.round((100 * (Number(d.clauses) - Number(d.pending))) / Math.max(1, Number(d.clauses)));
        return (
          <button key={d.doc_id} onClick={() => go(`#/doc/${d.doc_id}`)}
            className="group relative overflow-hidden rounded-2xl bg-white p-5 text-left shadow-sm ring-1 ring-slate-200/70 transition hover:-translate-y-0.5 hover:shadow-md">
            <span className={cx("absolute inset-y-0 left-0 w-1", BAR[sev])} />
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-600">{d.contract_type}</span>
              <span>{d.matter_id} · {d.matter_team}</span>
            </div>
            <h4 className="mt-3 line-clamp-2 min-h-[2.75rem] font-semibold text-slate-800 group-hover:text-indigo-700">{d.doc_title}</h4>
            <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
              <span>{d.clauses} clauses</span>
              <span className={cx(Number(d.pending) ? "font-medium text-indigo-600" : "text-emerald-600")}>
                {Number(d.pending) ? `${d.pending} to review` : "all clear"}</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${pct}%` }} /></div>
          </button>
        );
      })}
    </div>
  );
}
