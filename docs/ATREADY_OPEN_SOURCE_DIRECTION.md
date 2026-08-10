# AtReady open-source direction

Status: working product decision recorded on 2026-08-09. The local source identity is migrating from
Quartermaster to AtReady. GitHub repositories, public packages, directory listings, domains, and
other external accounts are not renamed or published by this decision.

## Decision

Use **AtReady by Stoicpickle** as the product identity.

AtReady is a small planning companion. A developer brings a rough idea or written plan, and AtReady
considers the tools, agents, services, subscriptions, models, credits, and capacity that the
developer has chosen to declare. It recommends where those resources may fit before implementation,
explains the recommendation, and produces inert handoff material. It does not execute the routed
work, contact resources, inspect accounts, or store credentials.

Positioning line: **Plan with what you have at the ready.**

The next distribution focus is an open-source beta of the deterministic local CLI. The bundled
Codex skill is an optional conversational adapter, not a second engine or a prerequisite. A
ChatGPT/Codex directory plugin may become a later installation and discovery surface, but
public directory submission is not the next dependency. Resume it only after real users show that
the planning behavior is useful enough to repeat and the supported-surface/runtime path is proven.

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
- Proposed private-development repository: `atready-dev`
- Proposed reserved/public repository: `atready`

Persisted v1 inventory state remains readable across the rename. Legacy private-state environment
and hidden backup names are compatibility details, not public product identifiers.

## Why open source first

- Test useful behavior before investing further in portal and universal-surface work.
- Let developers inspect the local-first routing and storage behavior.
- Give experienced Codex users a practical way to install, test, and critique the product.
- Preserve the optional skill while users test whether the CLI's planning behavior is useful.

## Next mini-direction

1. Complete and validate the local AtReady identity migration.
2. Rename the private GitHub development repository only after the reviewed local migration is
   ready to push; then update the local remote and verify the exact branch/SHA.
3. Rename or create the reserved public repository without publishing a release.
4. Produce a clean, reviewable public beta snapshot with one short install-and-first-plan path.
5. Invite early users to try it and collect practical feedback
   on setup, resource intake, plan usefulness, trust, and repeat use.
6. Revisit public plugin submission only if beta users want that installation surface.

## Beta success signal

The beta is successful when testers can install without maintainer intervention, describe their
resources without exposing credentials, bring a real rough plan, understand the recommendation,
and choose to use AtReady again. A completed installation alone is not product validation.

## Stop or reconsider

Reconsider the name if a closer functional product appears or practical trademark/package/listing
checks expose a material conflict. Reconsider the plugin path if the directory advertises AtReady
on surfaces that cannot complete its local workflow.
