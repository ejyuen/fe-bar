import { useState } from "react";
import { api, type GenieAnswer } from "../api";
import { Card, Icon, Spinner } from "../components/ui";

const SUGGESTIONS = [
  "Which contracts auto-renew in the next 90 days with uncapped liability?",
  "Count of high-severity flags by contract type",
  "What is the most common governing law?",
  "Documents pending review by matter team",
  "Override rate by clause type",
];

type Turn = { q: string; a?: GenieAnswer; err?: string };

export default function Genie({ configured }: { configured: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conv, setConv] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  if (!configured) return (
    <Card><div className="flex flex-col items-center gap-3 py-16 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><Icon.chat /></span>
      <h3 className="font-semibold">Genie space not configured yet</h3>
      <p className="max-w-md text-sm text-slate-500">Set the bundle variable <code className="rounded bg-slate-100 px-1">genie_space_id</code> after creating the space, then redeploy the app.</p>
    </div></Card>
  );

  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    setInput(""); setBusy(true);
    setTurns((t) => [...t, { q }]);
    try {
      const a = await api.genie(q, conv);
      setConv(a.conversation_id);
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a } : x)));
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, err: String((e as Error).message) } : x)));
    } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      {!turns.length && (
        <div className="grid gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => ask(s)} className="rounded-xl bg-white p-4 text-left text-sm text-slate-600 shadow-sm ring-1 ring-slate-200 hover:ring-indigo-300">{s}</button>
          ))}
        </div>
      )}
      {turns.map((t, i) => (
        <div key={i} className="space-y-3">
          <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">{t.q}</div>
          <div className="rounded-2xl rounded-bl-sm bg-white p-4 shadow-sm ring-1 ring-slate-200">
            {!t.a && !t.err && <Spinner label="Genie is thinking" />}
            {t.err && <p className="text-sm text-rose-600">{t.err}</p>}
            {t.a && (
              <div className="space-y-3 text-sm">
                {t.a.text && <p className="text-slate-700">{t.a.text}</p>}
                {t.a.description && <p className="text-slate-500">{t.a.description}</p>}
                {t.a.sql && <details className="rounded-lg bg-slate-900 p-3 text-xs text-slate-100"><summary className="cursor-pointer text-slate-300">Generated SQL</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap">{t.a.sql}</pre></details>}
                {t.a.columns.length > 0 && (
                  <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
                    <table className="w-full text-xs">
                      <thead className="bg-slate-50 text-left text-slate-500"><tr>{t.a.columns.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}</tr></thead>
                      <tbody className="divide-y divide-slate-100">{t.a.rows.slice(0, 50).map((r, j) => <tr key={j}>{r.map((v, k) => <td key={k} className="px-3 py-1.5 text-slate-700">{v}</td>)}</tr>)}</tbody>
                    </table>
                  </div>
                )}
                {t.a.error && <p className="text-rose-600">{t.a.error}</p>}
              </div>
            )}
          </div>
        </div>
      ))}
      <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="sticky bottom-4 flex gap-2 rounded-2xl bg-white p-2 shadow-lg ring-1 ring-slate-200">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about your contract portfolio…"
          className="flex-1 border-0 bg-transparent px-3 text-sm focus:outline-none" />
        <button disabled={busy || !input.trim()} className="flex items-center gap-1 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"><Icon.send />Ask</button>
      </form>
    </div>
  );
}
