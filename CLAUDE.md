# CLAUDE.md — Traia `hermes-agent` fork: rules of work

This is the **Traia fork** of NousResearch/hermes-agent. It is the source for the Traia
agent **runtime** (`hermes-runtime` gateway image). Read this before touching anything.
All sessions/agents working here MUST follow the branch model below.

## The branch model (READ FIRST)

- **`main` = UPSTREAM hermes.** It tracks NousResearch upstream (currently ≈ v0.16.0).
  **Do NOT put Traia work on `main`.** Patches pushed there are lost among thousands of
  upstream commits and are never pinned/built.
- **`traia-runtime` = THE Traia runtime line — the single source of truth for BOTH dev and
  prod.** It is: a pinned upstream base + every Traia patch. Both
  `infra/config/runtime-image.dev.json` and `runtime-image.prod.json` (in the monorepo)
  pin **SHAs from this branch**.
- There is exactly **ONE** Traia runtime line. Never create a second env-specific line off a
  different base. (That divergence is exactly what this file exists to prevent — see bottom.)

## How to ship a runtime change

1. Base your commit on `origin/traia-runtime` (current tip). NEVER on `main` or an old base.
2. Commit (prefix `traia:` for Traia-specific patches); push to `traia-runtime` (or PR into it).
3. In the **monorepo** (`traia-plugin-monorepo`), bump `hermes_agent_ref` in
   `infra/config/hermes-runtime-build.{dev,prod}.json` → the new tip SHA → PR to monorepo
   `main` → `build-and-promote` builds the image + auto-opens the backend
   `runtime-image.*.json` pin PR → deploy.
4. **Tag every prod pin**: `git tag -a traia-runtime/prod-<runtime-version> <sha>` and push it,
   so the prod build source is reachable even if a branch is ever lost.

## NEVER

- Never delete / force-push / rebase `traia-runtime` — it is the prod build source and pins
  reference its SHAs. (This branch should be branch-protected.)
- Never merge `traia-runtime` ↔ `main` (main is fast-moving upstream; the merge is huge and
  wrong). Upgrades happen by rebasing the Traia patches onto a newer base (below), not a merge.
- Never do an "urgent" prod fix on a separate base/branch — it goes on `traia-runtime` like
  everything else, so dev and prod never diverge again.

## Upstream upgrades (bumping the base)

Current base: **upstream v0.13.0** (`498bfc7b`). Upgrading = re-apply the Traia patches onto a
newer upstream base on `traia-runtime`, then re-pin. ⚠️ Upstream **v0.15 "Velocity" gutted
`run_agent.py`** (14,648 → 5,115 LOC) — the runtime was extracted into `agent/agent_init.py`,
`agent/agent_runtime_helpers.py`, `agent/chat_completion_helpers.py`, `agent/conversation_loop.py`.
So the egress-proxy / provider-auth patches DO NOT cherry-pick cleanly past v0.13 — they must be
re-homed into those modules. **Verify the proxied-anthropic RUN path in-pod on a Sonnet workspace
before any prod pin** — this is the code from the v1–v8 egress-proxy-401 incident; never
ship-and-observe.

## Runtime image build

Built by the monorepo `build-and-promote` from the pinned SHA. Dockerfile:
`traia-agent-workspaces/containers/hermes/Dockerfile` — clones this fork, `git fetch <sha>`,
installs **`./pkg/hermes-agent[anthropic]`**. The `[anthropic]` extra is REQUIRED from v0.16 on
(upstream moved `anthropic` out of base deps); without it every Sonnet/anthropic agent fails at
init with `ImportError`.

## Why this file exists — the 2026-07 divergence (do not repeat)

Prod launched on **v0.13.0**. Dev was separately upgraded to **v0.16.0** (+ a cron-memory fix).
Then urgent prod LLM-egress-proxy fixes (anthropic v1–v8 + aux + openai provider) were done
**prod-first on the v0.13.0 base**, on branch `fix/proxied-anthropic-callback-token`, and never
rebased onto the dev v0.16 line. Result: dev and prod ran **different hermes versions AND
different patch sets** with no shared line — prod missing cron-memory (agents lost `MEMORY.md`
every cron tick), dev missing the proxy fixes. `traia-runtime` unifies them. Keep it that way:
**one line, all fixes, pinned by SHA, tagged per prod release.**
