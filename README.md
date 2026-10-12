# Index Health Monitor

Finds what stops Google from indexing a website's pages. You add a site, and the app:
- reads its robots.txt and XML sitemaps;
- checks every listed URL for status codes, redirect chains, noindex, robots.txt blocks, canonical conflicts and `lastmod` problems;
- explains each problem and gives you a CSV report;
- re-checks the site every week.

The app is built for Replit and uses Replit Auth, Replit PostgreSQL, Replit Object Storage and Replit Deployments. It also runs locally, with a dev login, SQLite and a local folder standing in for those.

- **Back end:** Python, FastAPI, httpx, SQLAlchemy Core.
- **Front end:** React, TypeScript, Vite, TanStack Query.

---

## Run it locally

You need Python 3.10 or newer and Node 18 or newer.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd web && npm ci && npm run build && cd ..
.venv/bin/uvicorn server.main:app --reload --port 8000
```

Open http://localhost:8000 and click **Sign in**. Locally, this signs you in as "Local Developer" straight away.

To work on the front end with hot reload, run `npm run dev` in `web/` and open http://localhost:5173. Vite forwards `/api` and `/auth` to the back end on port 8000.

### Tests

```bash
.venv/bin/python -m pytest -q
```

The tests run against a fake website in memory, so they never touch the network. They cover:
- robots.txt matching (wildcards, `$`, longest match, Googlebot groups);
- SSRF blocking;
- redirect chains;
- sitemap indexes, gzip and the XML-bomb guard;
- `<head>` parsing;
- a full end-to-end crawl through the API with a known set of problems.

---

## Set up on Replit

1. **Import:** push this folder to GitHub, then in Replit choose *Create Repl → Import from GitHub*. The `.replit` file sets up Python 3.11, Node 20, the Run button and the deployment.
2. **Database:** open the **Database** tool and create a PostgreSQL database. Replit sets `DATABASE_URL` for you, and the tables are created on first start.
3. **Object Storage:** open the **Object Storage** tool and create a bucket. If you have more than one bucket, set `STORAGE_BUCKET_ID` in Secrets.
4. **Secrets:** nothing is required. On first start the app generates a random session key and keeps it in the database. If you prefer to manage it yourself, set `SESSION_SECRET` in Secrets.
5. **Auth:** the app uses Replit Auth through standard OpenID Connect:
   - issuer: `https://replit.com/oidc`;
   - client id: the Repl's `REPL_ID`;
   - PKCE, and no client secret.

   Press **Run** and sign in. If login fails, ask Replit Agent: *"Set up Replit Auth for this FastAPI app. Login route is /auth/login, callback /auth/callback; keep the session handling in server/auth.py."* The rest of the app only uses `current_user()` from `server/auth.py`, so nothing else needs to change.
6. **Security Scanner:** run it from the tools panel, fix what it finds, and take a screenshot for the case study.
7. **Deploy:**
   - **Web app:** *Deploy → Reserved VM*. The build and run commands come from `.replit`. See the note below for why it's Reserved VM.
   - **Weekly re-check:** *Deploy → Scheduled*.
     - Build command: `pip install -r requirements.txt`.
     - Run command: `python -m server.jobs.weekly`.
     - Schedule: every Monday at 06:00.
     - It uses the same database and bucket as the web app.
8. **Optional:** add a custom domain such as `index.ivig.dev`. If you use a different domain, update `USER_AGENT` in `server/crawler/fetch.py` so it points at your `/bot` page.

### Why Reserved VM and not Autoscale
A check runs in the background after the "start check" request has returned. Autoscale only guarantees CPU while a request is in progress, so a check could stall halfway. A Reserved VM keeps running. If you want to try Autoscale anyway, change `deploymentTarget` to `"cloudrun"`. Checks are short (about 5 seconds for 35 URLs), and the page polls while a check runs, but that isn't guaranteed to be enough.

### Settings (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local SQLite file | Set by Replit's Database tool |
| `SESSION_SECRET` | generated and stored in the database | Signs the login cookie |
| `AUTH_MODE` | `replit` on Replit, `dev` locally | `dev` is refused inside a deployment |
| `STORAGE_MODE` | `replit` on Replit, `local` locally | Where CSV reports go |
| `STORAGE_BUCKET_ID` | default bucket | Pick a specific Object Storage bucket |
| `MAX_URLS_PER_RUN` | 500 | URL cap for each check |
| `MAX_RUNS_PER_DAY` | 10 | Manual checks per user per 24 hours |
| `MAX_SITES_PER_USER` | 10 | |
| `CRAWL_CONCURRENCY` / `CRAWL_DELAY_MS` | 4 / 250 | Politeness settings |

---

## How it works

```
server/
  main.py            API routes, sessions, serves web/dist
  auth.py            Replit Auth (OIDC) or the dev login, current_user()
  config.py          settings from the environment
  db.py              tables (SQLAlchemy Core; Postgres on Replit, SQLite locally)
  repo.py            every query; all user-facing ones filter by user_id
  storage.py         Replit Object Storage or a local folder
  reports.py         CSV report
  crawler/
    fetch.py         safe fetching: SSRF guard, manual redirects, size caps
    robots.py        robots.txt with Google's matching rules
    sitemaps.py      sitemap discovery, indexes, gzip, protocol limits
    page.py          meta robots, X-Robots-Tag, canonical
    checks.py        the 21 issue rules and their explanations
    run.py           one crawl, start to finish
  jobs/weekly.py     the Scheduled deployment entry point
web/src/             React app (Sites, Site detail, Run detail)
tests/               pytest suite with a fake website
```

### Safety
The app fetches URLs that users type in, so:
- only http and https on ports 80 and 443 are allowed;
- every host, including each redirect hop, must resolve to public IP addresses;
- sitemaps are parsed with defusedxml;
- gzip output is capped;
- page bodies are capped at 2 MB;
- each user gets one running check, 10 manual checks a day and 500 URLs per check;
- the crawler respects robots.txt for its own `IndexHealthMonitor` user agent and explains itself at `/bot`.

### Changes from the original spec
- **SQLAlchemy Core instead of raw SQL migrations,** so the same schema runs on Postgres and on local SQLite. Tables are created on startup.
- **Reserved VM instead of Autoscale** for the web app (see above).
- **robots.txt is parsed by the app itself** rather than by Python's `urllib.robotparser`, which doesn't support Google's `*` and `$` rules.
- **More checks than the spec listed:**
  - multiple canonical tags;
  - invalid `lastmod` values;
  - sitemap read errors;
  - URLs skipped because robots.txt blocks this crawler.
