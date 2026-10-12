import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatDate, hostOf } from "../api";
import { StatusBadge } from "./parts";

export default function SiteDetail() {
  const siteId = Number(useParams().siteId);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const site = useQuery({ queryKey: ["site", siteId], queryFn: () => api.site(siteId) });
  const runs = useQuery({ queryKey: ["runs", siteId], queryFn: () => api.runs(siteId) });

  const start = useMutation({
    mutationFn: () => api.startRun(siteId),
    onSuccess: ({ id }) => navigate(`/runs/${id}`),
  });
  const weekly = useMutation({
    mutationFn: (on: boolean) => api.setWeekly(siteId, on),
    onSuccess: (s) => {
      qc.setQueryData(["site", siteId], s);
      qc.invalidateQueries({ queryKey: ["sites"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteSite(siteId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sites"] });
      navigate("/");
    },
  });

  if (site.error) return <p className="error-text">{site.error.message}</p>;
  if (!site.data) return <p className="muted">Loading…</p>;

  return (
    <>
      <Link to="/" className="back">
        ← All sites
      </Link>
      <div className="page-head">
        <div>
          <h1>{hostOf(site.data.root_url)}</h1>
          <p className="muted">{site.data.root_url}</p>
        </div>
        <button className="btn btn-primary" onClick={() => start.mutate()} disabled={start.isPending}>
          {start.isPending ? "Starting…" : "Run check now"}
        </button>
      </div>
      {start.error && <p className="error-text">{start.error.message}</p>}

      <section className="card settings">
        <label className="toggle">
          <input
            type="checkbox"
            checked={site.data.weekly_check}
            onChange={(e) => weekly.mutate(e.target.checked)}
          />
          <span>
            <strong>Weekly re-check</strong>
            <span className="muted small"> · runs every Monday morning, so regressions after a release show up</span>
          </span>
        </label>
      </section>

      <h2 className="section-title">Check history</h2>
      {runs.data?.length === 0 && <p className="muted">No checks yet.</p>}
      {!!runs.data?.length && (
        <div className="table-wrap card">
          <table>
            <thead>
              <tr>
                <th>Started</th>
                <th>Trigger</th>
                <th>Status</th>
                <th className="num">URLs</th>
                <th className="num">Errors</th>
                <th className="num">Warnings</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => navigate(`/runs/${r.id}`)}>
                  <td>
                    <Link to={`/runs/${r.id}`}>{formatDate(r.started_at ?? r.created_at)}</Link>
                  </td>
                  <td className="muted">{r.trigger === "scheduled" ? "Weekly" : "Manual"}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="num">{r.urls_checked}</td>
                  <td className={`num ${r.errors ? "error-text" : ""}`}>{r.errors}</td>
                  <td className={`num ${r.warnings ? "warning-text" : ""}`}>{r.warnings}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="danger-zone">
        <button
          className="btn-link danger"
          onClick={() => {
            if (window.confirm(`Delete ${hostOf(site.data.root_url)} and all its check history?`)) remove.mutate();
          }}
        >
          Delete this site
        </button>
      </div>
    </>
  );
}
