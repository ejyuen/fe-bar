import { sevDot } from "./ui";

export function HBars({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="space-y-3">
      {data.map((d) => (
        <div key={d.label} className="grid grid-cols-[7rem_1fr_2rem] items-center gap-3 text-sm">
          <span className="truncate text-slate-600">{d.label}</span>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" style={{ width: `${(100 * d.value) / max}%` }} />
          </div>
          <span className="text-right tabular-nums font-medium text-slate-700">{d.value}</span>
        </div>
      ))}
    </div>
  );
}

const SEV_HEX: Record<string, string> = { high: "#f43f5e", medium: "#f59e0b", low: "#facc15", none: "#cbd5e1" };

export function Donut({ data }: { data: { label: string; value: number }[] }) {
  const order = ["high", "medium", "low"];
  const rows = [...data].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
  const total = rows.reduce((s, d) => s + d.value, 0) || 1;
  const R = 52, C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <div className="flex items-center gap-8">
      <svg viewBox="0 0 140 140" className="h-36 w-36 -rotate-90">
        <circle cx="70" cy="70" r={R} fill="none" stroke="#f1f5f9" strokeWidth="18" />
        {rows.map((d) => {
          const len = (C * d.value) / total;
          const el = <circle key={d.label} cx="70" cy="70" r={R} fill="none" stroke={SEV_HEX[d.label] ?? "#94a3b8"} strokeWidth="18"
            strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-acc} />;
          acc += len;
          return el;
        })}
        <text x="70" y="70" className="rotate-90" transform="rotate(90 70 70)" textAnchor="middle" dominantBaseline="central"
          style={{ fontSize: 26, fontWeight: 600, fill: "#0f172a" }}>{total}</text>
      </svg>
      <ul className="space-y-2 text-sm">
        {rows.map((d) => (
          <li key={d.label} className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${sevDot(d.label)}`} />
            <span className="w-16 capitalize text-slate-600">{d.label}</span>
            <span className="tabular-nums font-medium">{d.value}</span>
            <span className="text-xs text-slate-400">{Math.round((100 * d.value) / total)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
