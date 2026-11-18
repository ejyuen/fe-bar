import { useState } from "react";
import { api, CLAUSE_LABEL } from "../api";
import { Card, Chip, ConfidenceBar, ErrorBox, SeverityPill, Spinner, StatusPill } from "../components/ui";
import { useAsync } from "../useAsync";

const STATUSES = ["pending", "auto_accepted", "approved", "overridden"];
const SEVS = ["high", "medium", "low", "none"];
const TEAMS = ["Team Atlas", "Team Borealis", "Team Cascade", "Team Denali"];

export default function Queue({ go }: { go: (h: string) => void }) {
  const [status, setStatus] = useState<string[]>(["pending"]);
  const [severity, setSeverity] = useState<string[]>([]);
  const [team, setTeam] = useState<string[]>([]);
  const { data, error, loading } = useAsync(() => api.queue({ status, severity, team }), [status.join(), severity.join(), team.join()]);
  const tog = (v: string, xs: string[], set: (x: string[]) => void) => set(xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]);

  return (
    <Card title={<span>Review queue {data && <span className="ml-2 font-normal text-slate-400">{data.rows.length} clauses · Lakebase {data.ms} ms</span>}</span>}>
      <div className="mb-5 flex flex-wrap gap-x-8 gap-y-3">
        <Group label="Status">{STATUSES.map((s) => <Chip key={s} on={status.includes(s)} onClick={() => tog(s, status, setStatus)}>{s.replace("_", " ")}</Chip>)}</Group>
        <Group label="Severity">{SEVS.map((s) => <Chip key={s} on={severity.includes(s)} onClick={() => tog(s, severity, setSeverity)}>{s}</Chip>)}</Group>
        <Group label="Matter team">{TEAMS.map((s) => <Chip key={s} on={team.includes(s)} onClick={() => tog(s, team, setTeam)}>{s.replace("Team ", "")}</Chip>)}</Group>
      </div>
      {error ? <ErrorBox e={error} /> : loading && !data ? <Spinner /> : (
        <div className="overflow-hidden rounded-xl ring-1 ring-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>{["Severity", "Clause", "Value", "Contract", "Team", "Confidence", "Status"].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {data!.rows.map((r) => (
                <tr key={r.clause_id} onClick={() => go(`#/doc/${r.doc_id}/${r.clause_id}`)} className="cursor-pointer hover:bg-indigo-50/40">
                  <td className="px-4 py-3"><SeverityPill s={r.severity} /></td>
                  <td className="px-4 py-3 font-medium text-slate-700">{CLAUSE_LABEL[r.clause_type] ?? r.clause_type}</td>
                  <td className="max-w-[16rem] truncate px-4 py-3 text-slate-600" title={r.current_value ?? ""}>{r.current_value}</td>
                  <td className="max-w-[18rem] truncate px-4 py-3 text-slate-500" title={r.doc_title}>{r.doc_title}<span className="ml-2 text-xs text-slate-400">{r.contract_type}</span></td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-500">{r.matter_team}</td>
                  <td className="px-4 py-3"><ConfidenceBar v={Number(r.confidence)} /></td>
                  <td className="px-4 py-3"><StatusPill s={r.status} /></td>
                </tr>
              ))}
              {!data!.rows.length && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-400">Nothing matches these filters 🎉</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const Group = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex items-center gap-2"><span className="mr-1 text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>{children}</div>
);
