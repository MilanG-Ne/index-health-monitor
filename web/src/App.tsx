import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError } from "./api";
import Login from "./pages/Login";
import RunDetail from "./pages/RunDetail";
import SiteDetail from "./pages/SiteDetail";
import Sites from "./pages/Sites";
import { Logo } from "./pages/parts";

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });

  if (me.isPending) return <div className="center muted">Loading…</div>;
  if (me.error) {
    if (me.error instanceof ApiError && me.error.status === 401) return <Login />;
    return <div className="center error-text">Could not reach the server: {me.error.message}</div>;
  }

  const signOut = async () => {
    await api.logout();
    qc.clear();
    window.location.href = "/";
  };

  return (
    <>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <Link to="/" className="brand">
            <Logo />
          </Link>
          <div className="topbar-user">
            <span className="muted-light">{me.data.name || me.data.email}</span>
            <button className="btn-ghost" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="wrap page">
        <Routes>
          <Route path="/" element={<Sites />} />
          <Route path="/sites/:siteId" element={<SiteDetail />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="wrap footer muted">
        Checks robots.txt, XML sitemaps and every listed page ·{" "}
        <a href="/bot" target="_blank" rel="noreferrer">
          About the crawler
        </a>
      </footer>
    </>
  );
}
