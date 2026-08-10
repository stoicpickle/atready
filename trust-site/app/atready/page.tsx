import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { DocumentKicker, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Product",
  description:
    "Meet AtReady, a local-first planning companion for fitting user-declared resources to project work.",
};

const routeSteps = [
  {
    number: "01",
    label: "Declare once",
    title: "Name what you have",
    copy: "Keep a local roster of the tools, agents, services, subscriptions, and capacity you want considered.",
  },
  {
    number: "02",
    label: "Bring a rough plan",
    title: "Shape the work",
    copy: "AtReady identifies the minimum useful workstreams and checks the constraints that matter before implementation begins.",
  },
  {
    number: "03",
    label: "Review the fit",
    title: "See who should do what",
    copy: "The route explains selections, omissions, gaps, and inert handoff text. You decide what happens next.",
  },
];

export default function AtReadyPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <DocumentKicker code="product document 01" />
        <section className="hero">
          <div>
            <p className="eyebrow">Planning pivot / before implementation</p>
            <h1>
              Bring a plan. <em>See your resource fit.</em>
            </h1>
            <p className="hero-copy">
              AtReady is a small planning companion for Codex. It considers the resources
              you chose to declare, suggests where they fit, explains why, and prepares handoff
              text for review—without contacting or running those resources.
            </p>
            <div className="button-row">
              <Link className="button" href="/surfaces">
                Check surface status
              </Link>
              <Link className="button secondary" href="/privacy">
                Read the data boundary
              </Link>
            </div>
          </div>
          <aside className="status-card" aria-label="Availability status">
            <strong>Pre-submission</strong>
            <span>
              AtReady is in private development. It is not publicly available, listed in
              the OpenAI Plugins Directory, or published on PyPI.
            </span>
          </aside>
        </section>

        <div className="stat-band" aria-label="Product boundary summary">
          <div className="stat">
            <span className="field-label">Inventory</span>
            <strong>User-declared</strong>
          </div>
          <div className="stat">
            <span className="field-label">Routing</span>
            <strong>Reviewable</strong>
          </div>
          <div className="stat">
            <span className="field-label">Handoffs</span>
            <strong>Inert</strong>
          </div>
          <div className="stat">
            <span className="field-label">Execution</span>
            <strong>Not authorized</strong>
          </div>
        </div>

        <section className="section">
          <div className="section-head">
            <p className="eyebrow">The working rhythm</p>
            <div>
              <h2>A little structure at the useful moment</h2>
              <p>
                AtReady is not the project manager and not the implementation agent. Its
                narrow job is to make a plan resource-aware before work begins.
              </p>
            </div>
          </div>
          <div className="route-list">
            {routeSteps.map((step) => (
              <article className="route-step" key={step.number}>
                <div className="route-number">{step.number}</div>
                <div className="route-title">
                  <span className="field-label">{step.label}</span>
                  <strong>{step.title}</strong>
                </div>
                <div className="route-copy">{step.copy}</div>
              </article>
            ))}
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <p className="eyebrow">Clear boundaries</p>
            <div>
              <h2>Planning help, not hidden automation</h2>
              <p>
                The current product boundary keeps recommendation, authorization, credential
                access, and execution as separate states.
              </p>
            </div>
          </div>
          <div className="two-column">
            <article className="document-panel safe">
              <h3>What it does</h3>
              <ul>
                <li>Uses the roster and project details the user chooses to provide.</li>
                <li>Preserves eligibility gaps instead of weakening constraints.</li>
                <li>Explains every selected and deliberately unused resource.</li>
                <li>Previews supported inventory changes before a separate apply step.</li>
              </ul>
            </article>
            <article className="document-panel danger">
              <h3>What it does not do</h3>
              <ul>
                <li>It does not scan accounts, subscriptions, credentials, or the home directory.</li>
                <li>It does not operate a AtReady backend or telemetry service.</li>
                <li>It does not contact providers or verify live resource access.</li>
                <li>It does not dispatch handoffs or run resources for project work.</li>
              </ul>
            </article>
          </div>
          <div className="boundary-callout">
            <strong>Local-first is not local-only</strong>
            <p>
              Inventory files stay on the user’s filesystem under AtReady’s current
              boundary. When the skill is used, a sanitized resource snapshot and project details
              may enter the configured ChatGPT or Codex host/model context. Resource names,
              capabilities, cost, and usage state may still be sensitive.
            </p>
          </div>
        </section>

        <section className="section">
          <div className="section-head">
            <p className="eyebrow">Illustrated output</p>
            <div>
              <h2>Designed to show its work</h2>
              <p>
                These product illustrations use synthetic data. They are review material, not a
                claim that AtReady has a custom browser interface.
              </p>
            </div>
          </div>
          <figure className="artifact-frame">
            <Image
              src="/brand/route-overview.png"
              alt="Synthetic AtReady route document showing three ordered workstreams and no authorized execution"
              width={1440}
              height={900}
            />
            <figcaption>
              <span>Route document / synthetic example</span>
              <span>Planning output only</span>
            </figcaption>
          </figure>
        </section>
      </div>
    </SiteShell>
  );
}
