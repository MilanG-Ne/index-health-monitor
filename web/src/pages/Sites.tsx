import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatDate, hostOf } from "../api";
import { StatusBadge } from "./parts";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function Sites() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const sites = useQuery({ queryKey: ["sites"], queryFn: api.sites });
  const [url, setUrl] = useState("");

  const add = useMutation({
    mutationFn: async (root: string) => {
      const site = await api.addSite(root);
      const run = await api.startRun(site.id);
      return run.id;
    },
    onSuccess: (runId) => {
      qc.invalidateQueries({ queryKey: ["sites"] });
      navigate(`/runs/${runId}`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (url.trim()) add.mutate(url.trim());
  };

  return (
    <>
      <section className="card add-card">
        <h1>Check a website</h1>
        <p className="muted">Enter a domain. The first check starts right away and takes about a minute.</p>
        <form onSubmit={submit} className="add-form">
          <input
            type="text"
            inputMode="url"
            placeholder="example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-label="Website address"
          />
          <button className="btn btn-primary" disabled={add.isPending || !url.trim()}>
            {add.isPending ? "Starting…" : "Add and check"}
          </button>
        </form>
        {add.error && <p className="error-text">{add.error.message}</p>}
      </section>

      <h2 className="section-title">Your sites</h2>
      {sites.isPending && <p className="muted">Loading…</p>}
      {sites.data?.length === 0 && <p className="muted">No sites yet. Add your first one above.</p>}
      <div className="site-list">
        {sites.data?.map((s) => (
          <Link to={`/sites/${s.id}`} className="card site-row" key={s.id}>
            <div>
              <div className="site-host">{hostOf(s.root_url)}</div>
              <div className="muted small">
                {s.last_run_id ? `Last check ${formatDate(s.last_run_finished_at)}` : "Not checked yet"}
                {s.weekly_check && " · weekly"}
              </div>
            </div>
            <div className="site-stats">
              {s.last_run_status === "done" ? (
                <>
                  <span className={`count ${s.last_run_errors ? "count-error" : "count-ok"}`}>
                    {plural(s.last_run_errors ?? 0, "error")}
                  </span>
                  <span className={`count ${s.last_run_warnings ? "count-warning" : "count-ok"}`}>
                    {plural(s.last_run_warnings ?? 0, "warning")}
                  </span>
                </>
              ) : (
                s.last_run_status && <StatusBadge status={s.last_run_status} />
              )}
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
