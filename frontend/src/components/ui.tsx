import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import type { Severity, Status } from "../api";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

const SEV: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 ring-rose-200",
  medium: "bg-amber-50 text-amber-700 ring-amber-200",
  low: "bg-yellow-50 text-yellow-700 ring-yellow-200",
  none: "bg-slate-50 text-slate-500 ring-slate-200",
};
const SEV_DOT: Record<string, string> = { high: "bg-rose-500", medium: "bg-amber-500", low: "bg-yellow-400", none: "bg-slate-300" };
const STATUS: Record<string, string> = {
  pending: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  auto_accepted: "bg-slate-100 text-slate-600 ring-slate-200",
  approved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  overridden: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function Pill({ className, children }: { className?: string; children: ReactNode }) {
  return <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", className)}>{children}</span>;
}
export const SeverityPill = ({ s }: { s: Severity | string }) => (
  <Pill className={SEV[s] ?? SEV.none}><span className={cx("h-1.5 w-1.5 rounded-full", SEV_DOT[s] ?? SEV_DOT.none)} />{s === "none" ? "no flag" : s}</Pill>
);
export const StatusPill = ({ s }: { s: Status | string }) => <Pill className={STATUS[s] ?? STATUS.pending}>{s.replace("_", " ")}</Pill>;
export const sevDot = (s: string) => SEV_DOT[s] ?? SEV_DOT.none;

export function Card({ className, children, title, action }: { className?: string; children: ReactNode; title?: ReactNode; action?: ReactNode }) {
  return (
    <section className={cx("rounded-2xl bg-white shadow-sm ring-1 ring-slate-200/70", className)}>
      {title && (
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-700">{title}</h3>{action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Kpi({ label, value, hint, icon, tone = "indigo" }: { label: string; value: ReactNode; hint?: string; icon: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    indigo: "bg-indigo-50 text-indigo-600", rose: "bg-rose-50 text-rose-600", emerald: "bg-emerald-50 text-emerald-600",
    sky: "bg-sky-50 text-sky-600", amber: "bg-amber-50 text-amber-600",
  };
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200/70">
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <span className={cx("grid h-9 w-9 place-items-center rounded-xl", tones[tone])}>{icon}</span>
      </div>
      <p className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export function ConfidenceBar({ v }: { v: number }) {
  const pct = Math.round((v ?? 0) * 100);
  const tone = pct >= 90 ? "bg-emerald-500" : pct >= 75 ? "bg-amber-400" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100"><div className={cx("h-full rounded-full", tone)} style={{ width: `${pct}%` }} /></div>
      <span className="w-8 text-xs tabular-nums text-slate-500">{pct}%</span>
    </div>
  );
}

export const Spinner = ({ label = "Loading" }: { label?: string }) => (
  <div className="flex items-center gap-3 p-8 text-sm text-slate-400">
    <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-500" />{label}…
  </div>
);
export const ErrorBox = ({ e }: { e: unknown }) => (
  <div className="rounded-xl bg-rose-50 p-4 text-sm text-rose-700 ring-1 ring-rose-200">{String((e as Error)?.message ?? e)}</div>
);

export function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className={cx("rounded-full px-3 py-1 text-xs font-medium ring-1 transition",
      on ? "bg-indigo-600 text-white ring-indigo-600 shadow-sm" : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50")}>{children}</button>
  );
}

// ----------------------------------------------------------------------------- toasts
type Toast = { id: number; text: string; tone: "ok" | "err" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "err") => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-6 z-50 flex flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={cx("pointer-events-auto rounded-xl px-4 py-3 text-sm font-medium shadow-lg ring-1",
            t.tone === "ok" ? "bg-slate-900 text-white ring-slate-800" : "bg-rose-600 text-white ring-rose-500")}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ----------------------------------------------------------------------------- icons (inline, stroke)
const I = (d: string) => () => (
  <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);
export const Icon = {
  doc: I("M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"),
  layers: I("M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5"),
  alert: I("M12 3l9 16H3L12 3zM12 10v4M12 17.5v.01"),
  check: I("M5 12l4 4L19 7"),
  coin: I("M12 3a9 9 0 100 18 9 9 0 000-18zM9 15c.5 1 1.6 1.5 3 1.5 1.7 0 3-.8 3-2.2 0-3-6-1.6-6-4.6 0-1.3 1.2-2.2 3-2.2 1.3 0 2.4.5 2.9 1.4M12 5.5v1.3M12 17.2v1.3"),
  grid: I("M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"),
  inbox: I("M4 13l2.5-8h11L20 13M4 13v6h16v-6M4 13h5l1 2h4l1-2h5"),
  folder: I("M3 7h6l2 2h10v10H3z"),
  chat: I("M4 5h16v11H8l-4 4z"),
  arrowLeft: I("M15 6l-6 6 6 6"),
  sparkle: I("M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"),
  edit: I("M4 20h4L19 9l-4-4L4 16zM14 6l4 4"),
  send: I("M4 12l16-8-6 16-2-6-8-2z"),
};
