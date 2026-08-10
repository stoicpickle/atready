import type { Metadata } from "next";
import { PolicyHeading, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Support",
  description: "AtReady support status and safe bug-report preparation.",
};

export default function SupportPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <PolicyHeading
          code="support document 04"
          title="Support"
          description="What to prepare when something goes wrong and which public support pieces are not active yet."
        />
        <div className="notice">
          <strong>Public support is not active.</strong> AtReady is still in private
          development. No anonymous support URL, public issue tracker, support email, or response
          time is promised by this working copy.
        </div>
        <div className="policy-body">
          <aside className="policy-aside">
            <strong>Maintainer finalization</strong>
            Before launch: publish one anonymous support destination, verify one private
            vulnerability-reporting channel, and replace this status with the confirmed process.
          </aside>
          <div>
            <section className="prose-section">
              <h2>For invited testers</h2>
              <p>
                Use only the private contact path included with your invitation. Do not post a
                private repository URL, inventory, project content, or access details publicly.
              </p>
            </section>
            <section className="prose-section">
              <h2>Prepare a useful bug report</h2>
              <ul>
                <li>AtReady version and exact candidate identifier.</li>
                <li>Operating system, Python version, and the host surface used.</li>
                <li>The smallest command or prompt that reproduces the issue.</li>
                <li>Expected behavior and actual behavior.</li>
                <li>Use synthetic input only. Remove real resource names, projects, paths, and accounts.</li>
              </ul>
            </section>
            <section className="prose-section">
              <h2>Sensitive reports</h2>
              <p>
                Do not include exploit details or secrets in a public issue. Until a verified
                private reporting channel is published, invited testers should request one through
                their existing private invitation path without disclosing vulnerability details.
                No response-time guarantee is offered.
              </p>
            </section>
          </div>
        </div>
      </div>
    </SiteShell>
  );
}
