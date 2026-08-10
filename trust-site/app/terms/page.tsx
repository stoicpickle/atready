import type { Metadata } from "next";
import { PolicyHeading, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Terms",
  description: "Draft AtReady terms and product limitations.",
};

export default function TermsPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <PolicyHeading
          code="terms document 03"
          title="Terms & limitations"
          description="The responsibilities and limits that accompany AtReady’s advisory planning output."
        />
        <div className="notice">
          <strong>Draft—not in force.</strong> Maintainer and owner approval, publisher identity,
          final effective date, and public URL are required before this can serve as public legal
          copy.
        </div>
        <div className="policy-body">
          <aside className="policy-aside">
            <strong>Current source license</strong>
            The development source is distributed under the Apache License 2.0. This working page
            does not change that license or its warranty and liability terms.
          </aside>
          <div>
            <section className="prose-section">
              <h2>Advisory output</h2>
              <p>
                AtReady produces recommendations and inert handoff material. It does not
                verify that a resource is currently available, authorized, independent, secure,
                affordable, or appropriate when work is executed, and it does not execute selected
                resources.
              </p>
            </section>
            <section className="prose-section">
              <h2>User responsibility</h2>
              <p>
                Users are responsible for reviewing outputs, checking current access and policy,
                obtaining required approvals, protecting local files, and separately authorizing
                any consequential action.
              </p>
            </section>
            <section className="prose-section">
              <h2>Prohibited inputs</h2>
              <p>
                Do not provide credentials, authentication tokens, regulated secrets, or data you
                are not authorized to process in inventories, project briefs, declarations,
                prompts, or reports.
              </p>
            </section>
            <section className="prose-section">
              <h2>High-impact use</h2>
              <p>
                Do not rely on AtReady as the sole control for safety-critical, legal,
                medical, financial, or other high-impact decisions.
              </p>
            </section>
          </div>
        </div>
      </div>
    </SiteShell>
  );
}
