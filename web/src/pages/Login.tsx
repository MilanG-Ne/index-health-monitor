import { Logo } from "./parts";

const CHECKS = [
  ["Broken and redirecting sitemap URLs", "Every URL is fetched and the full redirect chain recorded."],
  ["Noindex pages in the sitemap", "Meta robots and X-Robots-Tag, including Googlebot-only rules."],
  ["robots.txt blocks", "Evaluated with Google's own matching rules, wildcards included."],
  ["Canonical conflicts", "Pages whose canonical disagrees with the URL in the sitemap."],
  ["lastmod Google ignores", "Build timestamps, future dates and invalid formats."],
  ["Weekly re-checks", "Catch regressions after a release, with a CSV for every run."],
];

export default function Login() {
  return (
    <div className="login">
      <div className="login-hero">
        <div className="wrap">
          <Logo />
          <h1>Find what stops Google from indexing your pages</h1>
          <p className="lead">
            Index Health Monitor reads your robots.txt and XML sitemaps, checks every listed page, and tells you
            what to fix first.
          </p>
          <a className="btn btn-primary btn-lg" href="/auth/login">
            Sign in to check a site
          </a>
        </div>
      </div>
      <div className="wrap checks-grid">
        {CHECKS.map(([title, text]) => (
          <div className="card" key={title}>
            <h3>{title}</h3>
            <p className="muted">{text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
