# CLAUDE.md — Traia `hermes-agent` fork: rules of work

This is the **Traia fork** of NousResearch/hermes-agent. It is the source for the Traia
agent **runtime** (`hermes-runtime` gateway image). Read this before touching anything.
All sessions/agents working here MUST follow the branch model below.

## The branch model (READ FIRST)

- **`main` = UPSTREAM hermes.** It tracks NousResearch upstream. **Do NOT put Traia work
  on `main`.** Patches pushed there are lost among thousands of upstream commits and are
  never pinned/built.
- **`traia-runtime-v0.16` = THE Traia runtime line — the single source of truth for BOTH
  dev and prod.** It is: upstream **v0.16.0** + every Traia patch. Both
  `infra/config/runtime-image.dev.json` and `runtime-image.prod.json` (in the monorepo)
  pin **SHAs from this branch**. Branch-protected (no force-push / no deletion).
- **`traia-runtime` = FROZEN predecessor (upstream v0.13.0 line).** It carried prod runtime
  **0.0.19 and earlier**. Superseded by `traia-runtime-v0.16` on 2026-07-10 (the v0.16
  unification). Kept for history/rollback; do NOT base new work on it. (Reconciliation TODO
  for the repo owner: once the v0.13.0 line is fully retired, rename
  `traia-runtime-v0.16` → `traia-runtime`, or delete the frozen branch — the SHAs stay
  reachable via the `traia-runtime/prod-*` tags regardless.)
- There is exactly **ONE** active Traia runtime line (`traia-runtime-v0.16`). Never create a
  second env-specific line off a different base. (That divergence is exactly what this file
  exists to prevent — see bottom.)

## How to ship a runtime change

1. Base your commit on `origin/traia-runtime-v0.16` (current tip). NEVER on `main` or an old base.
2. Commit (prefix `traia:` for Traia-specific patches); push to `traia-runtime-v0.16` (or PR into it).
3. In the **monorepo** (`traia-plugin-monorepo`), bump `hermes_agent_ref` in
   `infra/config/hermes-runtime-build.{dev,prod}.json` → the new tip SHA → PR to monorepo
   `main` → `build-and-promote` builds the image + auto-opens the backend
   `runtime-image.*.json` pin PR → deploy.
4. **Tag every prod pin**: `git tag -a traia-runtime/prod-<runtime-version> <sha>` and push it,
   so the prod build source is reachable even if a branch is ever lost.

## NEVER

- Never delete / force-push / rebase `traia-runtime-v0.16` — it is the prod build source and
  pins reference its SHAs. (Branch-protected.)
- Never merge the runtime line ↔ `main` (main is fast-moving upstream; the merge is huge and
  wrong). Upgrades happen by rebasing the Traia patches onto a newer base (below), not a merge.
- Never do an "urgent" prod fix on a separate base/branch — it goes on `traia-runtime-v0.16`
  like everything else, so dev and prod never diverge again.

## Current state (2026-07-10)

Base: **upstream v0.16.0**. Prod pin = **runtime 0.0.20** (`hermes_agent_ref` `f7308c782`,
tag `traia-runtime/prod-0.0.20`, image `sha256:42eb9843c086`). The line carries EVERY fix
from the 2026-07 LLM-egress-proxy prod-regression saga:
`agent/anthropic_adapter.py` (`_egress_proxy_callback_token` + `build_anthropic_client` +
`resolve_anthropic_token` — the anthropic v1–v8 proxy auth), `agent/credential_pool.py`
(env-follow v5/v6), `agent/agent_runtime_helpers.py::create_openai_client` (openai/xai v7
override), `agent/auxiliary_client.py::_try_anthropic` (aux-via-proxy), `hermes_cli/auth.py`
+ `hermes_cli/runtime_provider.py` (first-class openai provider), plus cron-memory,
gemini-schema, and env-gated log levels. Verified in-pod on the live 0.16 image: all three
proxy legs (anthropic/openai/xai) 200 through the egress proxy.

**Dev alignment:** dev should be moved onto this same line (pin `f7308c782` or a descendant)
so dev and prod are truly unified again — done via a separate merge back to develop.

## Upstream upgrades (bumping the base)

Upgrading = re-apply the Traia patches onto a newer upstream base on `traia-runtime-v0.16`,
then re-pin. ⚠️ Upstream **v0.15 "Velocity" gutted `run_agent.py`** (14,648 → 5,115 LOC) —
the runtime was extracted into `agent/agent_init.py`, `agent/agent_runtime_helpers.py`,
`agent/chat_completion_helpers.py`, `agent/conversation_loop.py`. On v0.16 the proxy/auth
choke points are: `build_anthropic_client` + `resolve_anthropic_token` (all anthropic build
sites + run paths route through them) and `agent_runtime_helpers.create_openai_client` (all
openai/xai builds). **Verify the proxied anthropic/openai/xai RUN path in-pod before any prod
pin** — this is the code from the v1–v8 egress-proxy-401 incident; never ship-and-observe.

## Runtime image build

Built by the monorepo `build-and-promote` from the pinned SHA. Dockerfile lives in the
**backend** repo: `containers/hermes/Dockerfile` — clones this fork, `git fetch <sha>`,
installs **`./pkg/hermes-agent[anthropic]`**. The `[anthropic]` extra is REQUIRED from v0.16
on (upstream moved `anthropic` out of base deps); without it every Sonnet/anthropic agent
fails at init with `ImportError`. (`[firecrawl]` is also installed for native web tools.)

## Why this file exists — the 2026-07 divergence (do not repeat)

Prod launched on **v0.13.0**. Dev was separately upgraded to **v0.16.0** (+ a cron-memory fix).
Then urgent prod LLM-egress-proxy fixes (anthropic v1–v8 + aux + openai provider) were done
**prod-first on the v0.13.0 base**, on branch `fix/proxied-anthropic-callback-token`, and never
rebased onto the dev v0.16 line. Result: dev and prod ran **different hermes versions AND
different patch sets** with no shared line — prod missing cron-memory, dev missing the proxy
fixes. The v0.16 unification (2026-07-10) re-homed all 5 proxy/auth patches onto v0.16 and
made `traia-runtime-v0.16` the single line. Keep it that way: **one line, all fixes, pinned
by SHA, tagged per prod release.**
