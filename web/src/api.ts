export type Severity = "error" | "warning" | "info";
export type RunStatus = "queued" | "running" | "done" | "failed";

export interface Me {
  id: string;
  email: string | null;
  name: string | null;
  auth_mode: "replit" | "dev";
}

export interface Site {
  id: number;
  root_url: string;
  weekly_check: boolean;
  created_at: string;
  last_run_id?: number | null;
  last_run_status?: RunStatus | null;
  last_run_finished_at?: string | null;
  last_run_errors?: number | null;
  last_run_warnings?: number | null;
  last_run_urls_checked?: number | null;
}

export interface Run {
  id: number;
  site_id: number;
  root_url: string;
  trigger: "manual" | "scheduled";
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  origin: string | null;
  urls_found: number;
  urls_checked: number;
  errors: number;
  warnings: number;
  notices: number;
  truncated: boolean;
  error_message: string | null;
}

export interface IssueGroup {
  code: string;
  severity: Severity;
  title: string;
  why: string;
  count: number;
  items: { url: string | null; detail: string | null }[];
}

export interface UrlRow {
  id: number;
  url: string;
  status_code: number | null;
  final_url: string | null;
  redirect_chain: { url: string; status: number }[] | null;
  meta_robots: string | null;
  x_robots_tag: string | null;
  canonical: string | null;
  blocked_for_googlebot: boolean | null;
  lastmod: string | null;
  fetch_ms: number | null;
  error: string | null;
}

export interface UrlPage {
  items: UrlRow[];
  total: number;
  page: number;
  per_page: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("/api/me"),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  sites: () => request<Site[]>("/api/sites"),
  site: (id: number) => request<Site>(`/api/sites/${id}`),
  addSite: (root_url: string) =>
    request<Site>("/api/sites", { method: "POST", body: JSON.stringify({ root_url }) }),
  setWeekly: (id: number, weekly_check: boolean) =>
    request<Site>(`/api/sites/${id}`, { method: "PATCH", body: JSON.stringify({ weekly_check }) }),
  deleteSite: (id: number) => request<void>(`/api/sites/${id}`, { method: "DELETE" }),
  runs: (siteId: number) => request<Run[]>(`/api/sites/${siteId}/runs`),
  startRun: (siteId: number) => request<{ id: number }>(`/api/sites/${siteId}/runs`, { method: "POST" }),
  run: (id: number) => request<Run>(`/api/runs/${id}`),
  issues: (id: number) => request<IssueGroup[]>(`/api/runs/${id}/issues`),
  urls: (id: number, page: number) => request<UrlPage>(`/api/runs/${id}/urls?page=${page}&per_page=50`),
};

/** SQLite returns timestamps without a zone; they are UTC. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : value.replace(" ", "T") + "Z";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
