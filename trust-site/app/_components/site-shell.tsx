import Link from "next/link";
import Image from "next/image";
import type { ReactNode } from "react";

const navItems = [
  ["Product", "/atready"],
  ["Surfaces", "/surfaces"],
  ["Privacy", "/privacy"],
  ["Security", "/security"],
  ["Support", "/support"],
  ["Terms", "/terms"],
] as const;

export function SiteShell({ children }: { children: ReactNode }) {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="phase-strip">
          <span>AtReady / product &amp; trust</span>
          <span>Private development · not publicly available</span>
        </div>
        <div className="header-inner">
          <Link className="brand" href="/atready" aria-label="AtReady home">
            <Image src="/brand/icon.png" alt="" width={38} height={38} priority />
            <span>AtReady</span>
          </Link>
          <nav aria-label="Primary navigation">
            <ul className="nav-list">
              {navItems.map(([label, href]) => (
                <li key={href}>
                  <Link className="nav-link" href={href}>
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="main-content">{children}</main>
      <footer className="site-footer">
        <div className="footer-inner">
          <div>
            <strong>AtReady</strong>
            <p>
              A local-first resource-fit companion that brings user-declared resources into a
              project plan. This trust site is a pre-publication working copy.
            </p>
          </div>
          <nav className="footer-links" aria-label="Trust links">
            {navItems.slice(1).map(([label, href]) => (
              <Link key={href} href={href}>
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </footer>
    </>
  );
}

export function DocumentKicker({ code }: { code: string }) {
  return (
    <div className="document-kicker">
      <span>AtReady / {code}</span>
      <span className="signal-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

export function PolicyHeading({
  code,
  title,
  description,
}: {
  code: string;
  title: string;
  description: string;
}) {
  return (
    <>
      <DocumentKicker code={code} />
      <div className="page-heading">
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </>
  );
}
