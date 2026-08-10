import type { Metadata } from "next";
import { PolicyHeading, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Privacy",
  description: "The current AtReady privacy boundary and model-context caveat.",
};

export default function PrivacyPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <PolicyHeading
          code="privacy document 02"
          title="Privacy"
          description="A plain-language view of what AtReady stores, what may enter an AI host, and what the current product does not collect."
        />
        <div className="notice">
          <strong>Working policy copy.</strong> This page reflects the current implementation
          boundary but still requires maintainer and owner approval before public publication.
        </div>
        <div className="policy-body">
          <aside className="policy-aside">
            <strong>Short version</strong>
            Local inventory does not mean local-only processing. AtReady has no backend or
            telemetry in its current boundary; the configured ChatGPT or Codex host may still
            process the context supplied to it.
          </aside>
          <div>
            <section className="prose-section">
              <h2>What may be handled</h2>
              <p>
                A session may use a capability roster, access and readiness state, costs or
                capacity, routing constraints, project details the user provides, generated plans,
                and inert handoff text. Even without credentials, this can reveal subscriptions,
                budgets, installed tooling, and project strategy.
              </p>
            </section>
            <section className="prose-section">
              <h2>Where it goes</h2>
              <ul>
                <li>
                  Inventory and preferences are stored in user-controlled local files by the
                  separately installed runtime.
                </li>
                <li>
                  A sanitized snapshot can enter the configured ChatGPT or Codex host/model
                  context when the skill is used.
                </li>
                <li>
                  AtReady operates no hosted backend, analytics service, connector, or crash
                  reporting service in the current product boundary.
                </li>
                <li>
                  The host, model provider, operating system, backup software, sync tools, or shell
                  may retain their own copies under their own controls.
                </li>
              </ul>
            </section>
            <section className="prose-section">
              <h2>Credentials are out of bounds</h2>
              <p>
                Do not put passwords, API keys, session cookies, OAuth tokens, private keys,
                recovery codes, or other secrets in an inventory, project brief, prompt, or
                support report. Private notes are inert annotations, not a secret store.
              </p>
            </section>
            <section className="prose-section">
              <h2>Writes and retention</h2>
              <p>
                Creating a new absent inventory is the direct-write exception. Supported changes
                to an existing personal inventory are preview-first and require the exact reviewed
                state plus a bound plan token before apply. Safety backups persist until the user
                deliberately deletes one exact backup. Removing local files cannot remove copies
                already retained by a host, model provider, backup, sync, or logging system.
              </p>
            </section>
          </div>
        </div>
      </div>
    </SiteShell>
  );
}
