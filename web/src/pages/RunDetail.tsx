import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, formatDate, hostOf, IssueGroup, UrlRow } from "../api";
import { SeverityBadge, StatusBadge } from "./parts";

const ITEMS_SHOWN = 20;

export default function RunDetail() {
  const runId = Number(useParams().runId);
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });
  const finished = run.data?.status === "done";
  const issues = useQuery({ queryKey: ["issues", runId], queryFn: () => api.issues(runId), enabled: finished });

  if (run.error) return <p className="error-text">{run.error.message}</p>;
  if (!run.data) return <p className="muted">Loading…</p>;
  const r = run.data;
  const active = r.status === "queued" || r.status === "running";
  const progress = r.urls_found ? Math.min(100, Math.round((r.urls_checked / r.urls_found) * 100)) : 0;

  return (
    <>
      <Link to={`/sites/${r.site_id}`} className="back">
        ← {hostOf(r.root_url)}
      </Link>
      <div className="page-head">
        <div>
          <h1>Check of {hostOf(r.origin ?? r.root_url)}</h1>
          <p className="muted">
            {formatDate(r.started_at ?? r.created_at)} · {r.trigger === "scheduled" ? "weekly re-check" : "manual"}{" "}
            · <StatusBadge status={r.status} />
          </p>
        </div>
        {finished && (
          <a className="btn" href={`/api/runs/${r.id}/report.csv`}>
            Download CSV
          </a>
        )}
      </div>

      {active && (
        <section className="card">
          <p>
            {r.urls_found
              ? `Checking ${r.urls_found} URLs from the sitemap…`
              : "Reading robots.txt and sitemaps…"}
          </p>
          <div className="progress">
            <div style={{ width: `${r.urls_found ? Math.max(progress, 4) : 4}%` }} />
          </div>
        </section>
      )}

      {r.status === "failed" && (
        <section className="card error-card">
          <strong>The check failed.</strong> {r.error_message}
        </section>
      )}

      {finished && (
        <>
          <div className="stats">
            <Stat label="URLs checked" value={r.urls_checked} />
            <Stat label="Errors" value={r.errors} tone={r.errors ? "error" : "ok"} />
            <Stat label="Warnings" value={r.warnings} tone={r.warnings ? "warning" : "ok"} />
            <Stat label="Notices" value={r.notices} />
          </div>
          {r.truncated && (
            <p className="muted small">Only the first {r.urls_found} URLs were checked (the per-run limit).</p>
          )}

          <h2 className="section-title">Issues</h2>
          {issues.data?.length === 0 && (
            <section className="card all-clear">
              <strong>No issues found.</strong> Every sitemap URL returns 200, is indexable, and its canonical matches.
            </section>
          )}
          {issues.data?.map((g) => <IssueCard key={g.code} group={g} />)}

          {r.urls_checked > 0 && (
            <>
              <h2 className="section-title">All URLs</h2>
              <UrlTable runId={r.id} />
            </>
          )}
        </>
      )}
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "error" | "warning" | "ok" }) {
  return (
    <div className={`card stat ${tone ? `stat-${tone}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="muted small">{label}</div>
    </div>
  );
}

function IssueCard({ group }: { group: IssueGroup }) {
  const [all, setAll] = useState(false);
  const items = all ? group.items : group.items.slice(0, ITEMS_SHOWN);
  return (
    <details className={`card issue sev-border-${group.severity}`} open={group.severity === "error"}>
      <summary>
        <SeverityBadge severity={group.severity} />
        <span className="issue-title">{group.title}</span>
        <span className="issue-count">{group.count}</span>
      </summary>
      <p className="muted why">{group.why}</p>
      <ul className="issue-items">
        {items.map((i, n) => (
          <li key={n}>
            {i.url ? (
              <a href={i.url} target="_blank" rel="noreferrer" className="mono">
                {i.url}
              </a>
            ) : (
              <span className="muted">Whole site</span>
            )}
            {i.detail && <div className="muted small mono">{i.detail}</div>}
          </li>
        ))}
      </ul>
      {group.items.length > ITEMS_SHOWN && !all && (
        <button className="btn-link" onClick={() => setAll(true)}>
          Show all {group.items.length}
        </button>
      )}
    </details>
  );
}

function UrlTable({ runId }: { runId: number }) {
  const [page, setPage] = useState(1);
  const urls = useQuery({ queryKey: ["urls", runId, page], queryFn: () => api.urls(runId, page) });
  if (!urls.data) return <p className="muted">Loading…</p>;
  const pages = Math.max(1, Math.ceil(urls.data.total / urls.data.per_page));
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>URL</th>
            <th className="num">Status</th>
            <th>Indexing</th>
            <th className="num">Time</th>
          </tr>
        </thead>
        <tbody>
          {urls.data.items.map((u) => (
            <tr key={u.id}>
              <td className="mono url-cell">
                <a href={u.url} target="_blank" rel="noreferrer">
                  {u.url}
                </a>
                {!!u.redirect_chain?.length && <div className="muted small">→ {u.final_url}</div>}
              </td>
              <td className="num">
                <StatusCode row={u} />
              </td>
              <td className="small">{indexingNote(u)}</td>
              <td className="num muted small">{u.fetch_ms ? `${u.fetch_ms} ms` : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {pages > 1 && (
        <div className="pager">
          <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="muted small">
            Page {page} of {pages}
          </span>
          <button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function StatusCode({ row }: { row: UrlRow }) {
  if (row.error) return <span className="error-text small">{row.error.startsWith("Skipped") ? "skipped" : "error"}</span>;
  const hops = row.redirect_chain?.length ?? 0;
  const ok = row.status_code !== null && row.status_code < 300;
  return (
    <span className={ok && !hops ? "ok-text" : hops ? "warning-text" : "error-text"}>
      {hops ? `${row.redirect_chain![0].status}→` : ""}
      {row.status_code}
    </span>
  );
}

function indexingNote(u: UrlRow): string {
  const notes: string[] = [];
  if (u.error) notes.push(u.error);
  if (u.blocked_for_googlebot) notes.push("blocked by robots.txt");
  const robots = [u.meta_robots, u.x_robots_tag].filter(Boolean).join("; ");
  if (/noindex|none/i.test(robots)) notes.push("noindex");
  if (u.canonical && u.canonical.includes(" | ")) notes.push("multiple canonicals");
  else if (u.canonical && u.canonical.replace(/\/$/, "") !== (u.final_url ?? u.url).replace(/\/$/, ""))
    notes.push(`canonical → ${u.canonical}`);
  return notes.length ? notes.join(" · ") : "Indexable";
}
