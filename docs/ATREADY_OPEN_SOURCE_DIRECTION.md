# AtReady open-source direction

Status: product decision recorded on 2026-08-09 and updated after the first public source snapshot.
The product and local source identity are AtReady. The public `stoicpickle/atready` repository is
live; PyPI, directory listings, domains, and other external release channels remain separate gates.

## Decision

Use **AtReady by Stoicpickle** as the product identity.

AtReady is a resource-fit companion for Codex. A developer or Codex brings a rough implementation
plan, and AtReady considers the tools, agents, services, subscriptions, models, credits, and
capacity that the developer has chosen to declare. It recommends where those resources may fit,
explains constraints and gaps, and produces inert handoff material. Codex owns the project plan;
AtReady contributes resource context that Codex would not otherwise have. It does not execute the
routed project work or contact resources automatically. A separately authorized
`resource discover --inspect-version` check may invoke one allowlisted local executable with fixed
version arguments; that external program's side effects remain unknown. AtReady does not inspect
accounts or store credentials.

Positioning line: **Help Codex plan with what you already have.**

The next distribution focus is an open-source beta of the Codex skill and its deterministic local
CLI engine. The skill is the intended conversational experience; the CLI stores and validates the
roster, produces inspectable resource-fit evidence, and remains a standalone fallback. A
ChatGPT/Codex directory plugin may become a later installation and discovery surface, but
public directory submission is not the next dependency. Resume it only after real users show that
the resource-fit behavior is useful enough to repeat and the supported-surface/runtime path is
proven.

## Naming evidence

A current search found no exact-name GitHub repository for `AtReady` and no meaningful competing
software product using the joined name. The `atready` and `project-atready` names returned 404 from
both the PyPI and npm registries when checked. The relevant `stoicpickle` and `stoicpickle-labs`
GitHub repository slugs also appeared available.

The name comes from the ordinary phrase **at the ready**: capabilities available for use when a
plan needs them. That describes the product without implying that it owns, commands, procures, or
executes those capabilities.

This is practical product-collision research, not trademark, company-name, domain, app-store,
social-handle, or legal clearance. Recheck every external name immediately before claiming or
publishing it; registry availability can change.

## Identity map

- Product: **AtReady**
- Publisher-qualified name: **AtReady by Stoicpickle**
- Python distribution: `project-atready`
- Python module and CLI: `atready`
- Codex plugin: `atready`
- Codex skill: `project-atready`
- Private-development repository: `atready-dev`
- Public source repository: `atready`

Persisted v1 inventory state remains readable across the rename. Legacy private-state environment
and hidden backup names are compatibility details, not public product identifiers.

## Why open source first

- Test useful behavior before investing further in portal and universal-surface work.
- Let developers inspect the local-first routing and storage behavior.
- Give experienced Codex users a practical way to install, test, and critique the product.
- Keep the Codex skill and CLI engine aligned while users test whether the resource advice is useful.

## Next mini-direction

1. Keep private development changes reviewed and green before promoting a clean public snapshot.
2. Invite early users to try the source beta and collect practical feedback
   on setup, resource intake, recommendation usefulness, trust, and repeat use.
3. Prioritize confusing first-use behavior over new providers, connectors, or routing features.
4. Add a verified PyPI install only when it materially improves the early-user path.
5. Revisit public plugin submission only if beta users want that installation surface.

## Beta success signal

The beta is successful when testers can install without maintainer intervention, describe their
resources without exposing credentials, bring a real rough plan, understand how the recommendation
could improve Codex's plan, and choose to use AtReady again. A completed installation alone is not
product validation.

## Deferred public demo clip

Return to Screen Studio when the next public demo is ready. The target is a roughly 20 second real
screen recording for X, not a generated interface mockup. Show a synthetic pixel game request,
Codex invoking AtReady, and the actual compact resource-fit recommendation using examples such as
Codex and Retro Diffusion. Keep `SYNTHETIC EXAMPLE` visible, use provider names as plain text without
logos or an endorsement claim, and end on the no execution boundary.

Use the Intel build of Screen Studio on the current iMac, record at 1080p, and free comfortable
working storage before capture and export. Prepare the exact synthetic roster, prompt, output,
timing, and X copy before purchasing a month or beginning production.

## Stop or reconsider

Reconsider the name if a closer functional product appears or practical trademark/package/listing
checks expose a material conflict. Reconsider the plugin path if the directory advertises AtReady
on surfaces that cannot complete its local workflow.
