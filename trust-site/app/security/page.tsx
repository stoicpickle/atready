import type { Metadata } from "next";
import { PolicyHeading, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Security",
  description: "AtReady security boundary and reporting status.",
};

export default function SecurityPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <PolicyHeading
          code="security document 05"
          title="Security boundary"
          description="The current controls, explicit non-goals, and reporting status for AtReady’s pre-release product boundary."
        />
        <div className="notice">
          <strong>Pre-release status.</strong> Security fixes currently target the newest private
          development candidate. No stable or publicly supported version is available.
        </div>
        <div className="policy-body">
          <aside className="policy-aside">
            <strong>Reporting status</strong>
            A verified public security-report channel has not been published. Invited testers must
            use their existing private invitation path to request a channel without sending issue
            details first.
          </aside>
          <div>
            <section className="prose-section">
              <h2>Current invariants</h2>
              <ul>
                <li>No AtReady backend, connector, telemetry, or hosted inventory service.</li>
                <li>No credential storage or provider-account inspection.</li>
                <li>No broad filesystem, environment, subscription, or MCP discovery.</li>
                <li>No automatic handoff dispatch or project-resource execution.</li>
                <li>Existing personal-inventory changes remain preview-first and state-bound.</li>
              </ul>
            </section>
            <section className="prose-section">
              <h2>Host boundary</h2>
              <p>
                The ChatGPT or Codex host has its own permissions, network behavior, model
                processing, logs, and retention. AtReady’s narrower skill contract does not
                override those systems. Users should review the host’s data controls before
                providing confidential project or roster information.
              </p>
            </section>
            <section className="prose-section">
              <h2>Handoffs remain inert</h2>
              <p>
                Generated prompts, missions, commands, URLs, and checklists are display-only
                planning artifacts. A user must separately review and specifically authorize any
                execution outside AtReady.
              </p>
            </section>
            <section className="prose-section">
              <h2>Features that reopen the threat model</h2>
              <p>
                Broad discovery, network requests, hosted storage, telemetry, account connectors,
                credentials, billing access, automatic execution, or synchronization all require a
                new permissions and threat-model review before implementation.
              </p>
            </section>
          </div>
        </div>
      </div>
    </SiteShell>
  );
}
