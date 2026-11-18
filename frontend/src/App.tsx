import { useEffect, useState } from "react";
import { api } from "./api";
import { cx, Icon, ToastProvider } from "./components/ui";
import DocDetail from "./pages/DocDetail";
import Documents from "./pages/Documents";
import Genie from "./pages/Genie";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import { useAsync } from "./useAsync";

const NAV = [
  { hash: "#/", label: "Overview", icon: Icon.grid, title: "Portfolio overview" },
  { hash: "#/queue", label: "Review queue", icon: Icon.inbox, title: "Review queue" },
  { hash: "#/documents", label: "Documents", icon: Icon.folder, title: "Documents" },
  { hash: "#/genie", label: "Ask Genie", icon: Icon.chat, title: "Ask Genie" },
];

function useHash() {
  const [h, setH] = useState(window.location.hash || "#/");
  useEffect(() => { const f = () => setH(window.location.hash || "#/"); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  return [h, (x: string) => { window.location.hash = x; }] as const;
}

export default function App() {
  const [hash, go] = useHash();
  const me = useAsync(api.me, []);
  const parts = hash.replace(/^#\//, "").split("/");
  const page = parts[0] || "";
  useEffect(() => { api.audit("view_page", "page", page === "doc" ? "document" : page || "overview"); }, [page]);
  const nav = NAV.find((n) => n.hash === `#/${page}`) ?? (page === "doc" ? NAV[2] : NAV[0]);

  return (
    <ToastProvider>
      <div className="flex h-full">
        <aside className="flex w-60 shrink-0 flex-col bg-slate-900 text-slate-300">
          <div className="flex items-center gap-3 px-5 py-6">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 font-bold text-white shadow-lg">M</span>
            <div><p className="text-sm font-semibold text-white">Matter Intelligence</p><p className="text-xs text-slate-400">Northwind Legal Cloud</p></div>
          </div>
          <nav className="flex-1 space-y-1 px-3">
            {NAV.map((n) => (
              <a key={n.hash} href={n.hash}
                className={cx("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                  nav.hash === n.hash ? "bg-white/10 text-white" : "hover:bg-white/5 hover:text-white")}>
                <n.icon />{n.label}
              </a>
            ))}
          </nav>
          <div className="m-3 rounded-xl bg-white/5 p-3 text-xs">
            <p className="text-slate-400">Signed in as</p>
            <p className="truncate font-medium text-slate-200">{me.data?.email ?? "…"}</p>
            <p className="mt-2 text-slate-500">Unity Catalog row filters apply to your view.</p>
          </div>
        </aside>
        <main className="flex-1 overflow-y-auto">
          <header className="sticky top-0 z-10 border-b border-slate-200/70 bg-slate-50/80 px-8 py-5 backdrop-blur">
            <h1 className="text-xl font-semibold text-slate-900">{page === "doc" ? "Document review" : nav.title}</h1>
          </header>
          <div className="px-8 py-6">
            {page === "" && <Overview go={go} />}
            {page === "queue" && <Queue go={go} />}
            {page === "documents" && <Documents go={go} />}
            {page === "doc" && parts[1] && <DocDetail key={parts[1]} docId={parts[1]} focus={parts[2]} go={go} />}
            {page === "genie" && <Genie configured={!!me.data?.genie_configured} />}
          </div>
        </main>
      </div>
    </ToastProvider>
  );
}
