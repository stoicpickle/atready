import type { Metadata } from "next";
import { PolicyHeading, SiteShell } from "../_components/site-shell";

export const metadata: Metadata = {
  title: "Supported surfaces",
  description: "AtReady plugin surface compatibility and public-launch stop/go rule.",
};

const surfaces = [
  {
    surface: "Codex local / worktree",
    status: "Probe pending",
    boundary: "Candidate target where local files and a compatible local runtime may be available.",
    proof: "Must pass explicit activation, routing, onboarding, mutation preview, and failure cases.",
  },
  {
    surface: "Codex cloud",
    status: "Unverified",
    boundary: "Do not assume access to a user’s machine, local inventory, or separately installed runtime.",
    proof: "Must be excluded or communicate incompatibility before an unusable workflow begins.",
  },
  {
    surface: "ChatGPT desktop",
    status: "Unverified",
    boundary: "Plugin visibility does not prove local runtime or filesystem compatibility.",
    proof: "Must test listing visibility, invocation, local prerequisites, and honest stopping behavior.",
  },
  {
    surface: "ChatGPT web",
    status: "Unverified",
    boundary: "A browser session cannot be assumed to reach local files or a local Python tool.",
    proof: "Must not advertise starter prompts that cannot complete on the surface.",
  },
  {
    surface: "CLI and IDE hosts",
    status: "Unverified",
    boundary: "Host permissions, skill discovery, and local-runtime access differ by integration.",
    proof: "Each named surface needs its own clean-environment proof before support is claimed.",
  },
];

export default function SurfacesPage() {
  return (
    <SiteShell>
      <div className="page-shell">
        <PolicyHeading
          code="surface manifest 06"
          title="Supported surfaces"
          description="AtReady has not yet declared a public support matrix. This page records the candidate targets and the evidence each one still needs."
        />
        <div className="notice">
          <strong>No public support claim yet.</strong> A locally valid plugin bundle does not prove
          that every ChatGPT or Codex surface can discover, invoke, or complete its workflows.
        </div>
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Surface</th>
                <th scope="col">Current status</th>
                <th scope="col">Known boundary</th>
                <th scope="col">Required proof</th>
              </tr>
            </thead>
            <tbody>
              {surfaces.map((row) => (
                <tr key={row.surface}>
                  <td>
                    <strong>{row.surface}</strong>
                  </td>
                  <td>
                    <span className="surface-status">{row.status}</span>
                  </td>
                  <td>{row.boundary}</td>
                  <td>{row.proof}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <section className="section">
          <div className="section-head">
            <p className="eyebrow">Publication gate</p>
            <div>
              <h2>The stop / go rule</h2>
              <p>
                The probe can proceed only if unsupported surfaces exclude AtReady or clearly
                explain incompatibility before invocation. If a directory listing advertises
                starter prompts on surfaces that cannot complete them, public directory submission
                stops and distribution remains limited to compatible local or repository channels.
              </p>
            </div>
          </div>
          <div className="two-column">
            <article className="document-panel safe">
              <h3>Go</h3>
              <p>
                The product is visible only where it can work, or the host presents an honest
                compatibility boundary before the user begins.
              </p>
            </article>
            <article className="document-panel danger">
              <h3>Stop</h3>
              <p>
                The listing appears universal while its core prompts depend on local capabilities
                unavailable to one or more advertised surfaces.
              </p>
            </article>
          </div>
        </section>
      </div>
    </SiteShell>
  );
}
