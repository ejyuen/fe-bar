import { api } from "../api";
import { Donut, HBars } from "../components/charts";
import { Card, ErrorBox, Icon, Kpi, Pill, SeverityPill, Spinner } from "../components/ui";
import { useAsync } from "../useAsync";

export default function Overview({ go }: { go: (h: string) => void }) {
  const { data, error, loading } = useAsync(api.overview, []);
  if (loading && !data) return <Spinner label="Loading portfolio" />;
  if (error) return <ErrorBox e={error} />;
  const d = data!;
  const k = d.kpis;
  const n = (x: unknown) => Number(x ?? 0);
  const auto = n(k.queue_clauses) ? Math.round((100 * n(k.auto_accepted)) / n(k.queue_clauses)) : 0;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Kpi label="Docs processed" value={n(k.docs)} icon={<Icon.doc />} hint="parsed, classified, extracted" />
        <Kpi label="Clauses extracted" value={n(k.clauses)} icon={<Icon.layers />} tone="sky" hint="14 clause types" />
        <Kpi label="High-risk flags" value={n(k.high_flags)} icon={<Icon.alert />} tone="rose" hint="firm playbook" />
        <Kpi label="Auto-accepted" value={`${auto}%`} icon={<Icon.check />} tone="emerald" hint={`${n(k.pending)} pending · ${n(k.reviewed)} reviewed`} />
        <Kpi label="Cost / 1K docs" value={`$${n(k.cost_per_1k).toFixed(0)}`} icon={<Icon.coin />} tone="amber" hint="estimate" />
      </div>
      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Documents by contract type" className="lg:col-span-3">
          <HBars data={d.by_contract_type.map((r) => ({ label: r.label ?? "Unknown", value: n(r.value) }))} />
        </Card>
        <Card title="Risk flags by severity" className="lg:col-span-2">
          <Donut data={d.by_severity.map((r) => ({ label: r.label, value: n(r.value) }))} />
        </Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Auto-renewing contracts" className="lg:col-span-3"
          action={<span className="text-xs text-slate-400">latest expiration first</span>}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
              <tr><th className="pb-2 font-medium">Contract</th><th className="pb-2 font-medium">Type</th><th className="pb-2 font-medium">Expires</th><th className="pb-2 font-medium">Liability</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {d.auto_renewals.map((r) => (
                <tr key={r.doc_id} className="cursor-pointer hover:bg-slate-50" onClick={() => go(`#/doc/${r.doc_id}`)}>
                  <td className="max-w-xs truncate py-2.5 pr-3 font-medium text-slate-700">{r.title}</td>
                  <td className="py-2.5 text-slate-500">{r.contract_type}</td>
                  <td className="py-2.5 tabular-nums text-slate-600">{r.expiration_date}</td>
                  <td className="py-2.5">{r.uncapped_liability === "true"
                    ? <Pill className="bg-rose-50 text-rose-700 ring-rose-200">uncapped</Pill>
                    : <Pill className="bg-slate-50 text-slate-500 ring-slate-200">capped</Pill>}</td>
                </tr>
              ))}
              {!d.auto_renewals.length && <tr><td colSpan={4} className="py-4 text-slate-400">No auto-renewing contracts visible to you.</td></tr>}
            </tbody>
          </table>
        </Card>
        <Card title="Playbook rules triggered" className="lg:col-span-2">
          <ul className="space-y-3">
            {d.by_rule.map((r) => (
              <li key={r.rule_id + r.severity} className="flex items-start gap-3">
                <span className="mt-0.5 w-9 shrink-0 font-mono text-xs text-slate-400">{r.rule_id}</span>
                <span className="flex-1 text-sm text-slate-600">{r.rule_text}</span>
                <SeverityPill s={r.severity} />
                <span className="w-6 text-right text-sm font-semibold tabular-nums">{r.flags}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <p className="text-xs text-slate-400">Figures reflect your Unity Catalog row filter and column masks (queries run as {d.user}).</p>
    </div>
  );
}
