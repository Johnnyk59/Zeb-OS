# ZebOS — Full-Stack Architecture & Engineering Audit

**Auditor's stance:** world-class systems architect, uncompromising, evidence-first.
Every finding below is grounded in a specific file I read, not vibes.
**Scope caveat (intellectual honesty):** ZebOS is ~1.37M lines across 2,948
Python files plus a React app, two TUIs, and a desktop shell. No human — and no
audit — reads all of that. I did deep, targeted reconnaissance of the load-bearing
subsystems (entrypoints, auth, the chat/dashboard surface, autonomy, config,
packaging, CI) and sampled the rest. Where I sampled rather than exhaustively
verified, I say so.

**Date:** 2026-07-11 · **Commit base:** `main` @ latest · **Reviewer model:** claude-sonnet-5 (undercover)

---

## 0. The one truth that reframes everything

**ZebOS is not an operating system. It is an AI agent framework wearing an OS
costume.** The README brands it *"Zeb Agent ☤"* from Nous Research. There is no
kernel, no scheduler in the OS sense, no process table, no syscall layer, no
init system, no memory manager — `grep` for those primitives returns only
incidental hits (`gateway/shutdown_forensics.py` reading `/proc`, not a kernel).
What exists is a very capable **agent platform**: a provider-abstracted LLM loop,
a tool/skill system, multi-channel gateways (Telegram/Discord/Feishu/…), a local
GGUF backbone, autonomous background bots, and several UIs.

This matters because the "OS" framing sets a **billion-dollar-OS bar the product
cannot clear and does not need to clear.** The honest, winning positioning is:
*"the self-hosted, offline-capable, self-improving agent platform."* Every
roadmap decision below is made against **that** bar — where ZebOS can genuinely
be world-class — not against Linux.

**Verdict scorecard (A–F, against the agent-platform bar):**

| Domain | Grade | One-line |
|---|---|---|
| Dependency & supply-chain hygiene | **A-** | Exact pins, uv.lock, OSV + supply-chain CI, minimal core. Genuinely excellent. |
| Provider/model abstraction | **B** | Clean local-first design; singleton sharp edges. |
| Local backbone (offline) | **B** | Works out of the box now; footprint tuning shipped. |
| CI breadth | **B** | 16 workflows, sliced parallel tests. Good on paper. |
| Security posture | **D** | Network-exposed arbitrary file write + secret-in-logs + no TLS/RBAC/audit. |
| Autonomy safety | **D-** | On by default; file mover defaults to *not* dry-run, no undo. |
| Code structure / maintainability | **D** | 20k-line god-files; a 8.4k-line config module. |
| UI architecture | **C-** | Four+ parallel frontends duplicating the same surface. |
| Testing / dev-experience | **C** | Strong intent; fragile local repro, >2min collection. |
| Observability | **C** | Forensics + health checks exist; no unified telemetry/tracing. |

---

## P0 — CRITICAL FAILURES (blocking; fix before any "world-class" claim)

### P0-1. Network-exposed arbitrary filesystem read **and write** behind a single shared key
- **Evidence:** `zeb_chat/dashboard_api.py` — `/api/files`, `/api/files/read`,
  `/api/files/write` resolve `os.path.abspath(path)` with **no sandbox, no root
  jail, no allowlist.** `write_file` writes arbitrary bytes to any absolute path
  the process UID can reach. `zeb_chat/server.py:483` binds **`0.0.0.0:8000`** by
  default; there is no TLS.
- **Why it's catastrophic:** `os.path.abspath` resolves `..` — it does not
  contain traversal. A single leaked/sniffed Bearer key = write to
  `~/.bashrc`, `/etc/cron.d/*`, `.ssh/authorized_keys`, or the app's own `.env`
  → **remote code execution / full host takeover.** The key travels in
  cleartext HTTP on all interfaces.
- **Fix:** (a) bind `127.0.0.1` by default, require explicit opt-in for `0.0.0.0`
  and force TLS when non-loopback; (b) introduce a configurable **workspace root
  jail** — resolve the real path and reject anything not under it
  (`os.path.realpath` + `os.path.commonpath`); (c) make write require a second,
  separately-scoped capability, not the same read key.

### P0-2. The API key is printed to stdout/logs on every boot
- **Evidence:** `zeb_chat/api_key.py::log_api_key_banner` `print()`s **and**
  `logger.info`s the raw key ("visible in Docker logs" — stated as a feature).
- **Why:** Docker logs, journald, CI capture, log shippers, and screen-shares all
  now contain a live credential that, per P0-1, is a host-takeover primitive.
  The crypto around the key is otherwise *good* (192-bit `token_urlsafe`,
  `hmac.compare_digest`, `0600`) — which makes leaking it in plaintext the more
  glaring lapse.
- **Fix:** print a **one-time** setup URL with a short-lived enrollment token, or
  a fingerprint (`sha256[:8]`) — never the key itself after first issuance. Redact
  in the logging formatter.

### P0-3. Autonomy is ON by default and the file organizer moves real files with no undo
- **Evidence:** `zeb_autonomy/registry.py:52` — `if not auto.get("enabled", True)`
  → autonomy defaults **enabled**. `zeb_autonomy/bots/file_organizer.py:66` —
  `dry_run = cfg.get("dry_run", False)` defaults **False**, then line 103 does a
  raw `shutil.move(...)`. There is **no trash, no rollback, no journal** of moves
  that can be reversed.
- **Why it's catastrophic:** a fresh, unconfigured deployment will, on its own
  timer, **physically relocate a user's files** into category folders with no
  confirmation and no undo. This is a data-loss engine shipped in the default ON
  position. For an "autonomous OS" the blast radius is the whole home directory.
- **Fix:** (a) default `autonomy.enabled = False` (opt-in); (b) default
  `file_organizer.dry_run = True`; (c) never `shutil.move` without a reversible
  **move journal** (record src→dst, offer `zeb autonomy undo`); (d) scope every
  actor bot to an explicit allow-listed root.

### P0-4. Local test suite is not reproducible; collection alone exceeds 2 minutes
- **Evidence:** `python -m pytest --collect-only` **timed out at 120s**;
  full-suite `-k` runs surface **317 collection errors** all rooted in
  `ModuleNotFoundError: No module named 'multipart'` — `python-multipart` is not
  installed in a plain environment. CI only works because it runs `uv sync`.
- **Why it's P0 for velocity:** a contributor who runs `pip install -e .` cannot
  collect the suite; the failure mode (`RuntimeError: Form data requires
  "python-multipart"`) is opaque and mass-produced. Collection taking >2 min means
  the inner dev loop is broken before a single test runs.
- **Fix:** make `uv sync` the documented, only-supported bootstrap (or add
  `python-multipart` to core deps); add a `pytest` import-mode / conftest guard
  that fails fast with a one-line "run `uv sync`" message; profile and fix the
  collection-time blowup (likely import-time side effects in a shared conftest).

---

## P1 — MAJOR IMPROVEMENTS (system-wide impact)

### P1-1. God-files are an existential maintainability and delivery risk
- **Evidence (single files):** `gateway/run.py` **20,760 LOC**, `cli.py`
  **16,194**, `zeb_cli/web_server.py` **15,501**, `zeb_cli/main.py` **14,515**,
  `tui_gateway/server.py` **13,915**, `zeb_cli/config.py` **8,407**,
  `zeb_cli/auth.py` **8,248**, `agent/auxiliary_client.py` **7,513**.
- **Why:** no reviewer can hold a 20k-line module in their head; merge conflicts
  are guaranteed; test isolation is impossible; a change to config touches an 8k
  file where the earlier bug in *this very session* lived (a schema default
  silently pinning `n_ctx`). These files are where regressions breed.
- **Fix:** treat any file >1,500 LOC as a defect. Carve `gateway/run.py` into a
  package (`gateway/run/{lifecycle,dispatch,platforms,health}.py`); split
  `config.py` into `schema/`, `io/`, `env/`, `resolution/`. Add a CI guard that
  fails when a non-generated source file exceeds a threshold.

### P1-2. Four-plus parallel frontends re-implementing the same surface
- **Evidence:** `web/` React+Vite app (53 `.tsx`), `zeb_chat/static/dashboard.html`
  (a hand-rolled ~1,600-line vanilla-JS SPA — the one I extended this session),
  `tui_gateway/` (13.9k-LOC Python TUI server), `ui-tui/` (a separate Node TUI
  with its own `packages/`), and `apps/desktop` (Electron shell). Chat, model
  selection, files, and status logic exist in **at least three** of these.
- **Why:** every feature (model selector, chat persistence, files browser) must
  be built and fixed N times; they drift; the vanilla dashboard duplicates the
  React app's job. This is the single biggest source of silent inconsistency.
- **Fix:** pick **one** canonical web client (the React app) and make the static
  dashboard either its build output or an explicitly-scoped "no-build fallback."
  Define one typed API contract (OpenAPI generated from the FastAPI routers) and
  generate clients for React + TUI from it. Kill or clearly demote the duplicates.

### P1-3. No RBAC, no multi-user, no audit trail, no rate limiting on a tool-executing surface
- **Evidence:** `require_key()` in `dashboard_api.py` is the *entire* authz model
  — one key, all-or-nothing. No per-endpoint scopes, no request log of "who ran
  what," no throttle. The same key that reads status can rewrite `/etc`.
- **Why:** an agent platform that edits code, moves files, stores OAuth tokens,
  and restarts gateways is a **privileged execution surface**. Single-key
  all-powerful auth is acceptable for a localhost toy, not for the "world-class"
  bar or any shared/hosted deployment.
- **Fix:** capability-scoped tokens (read / chat / files / admin), an append-only
  audit log of privileged actions (already have `shutdown_forensics.py` — extend
  the pattern), per-key rate limits, and a real session/identity model.

### P1-4. Secrets at rest are plaintext `.env`; OAuth subscription token included
- **Evidence:** the Anthropic-subscription flow I added stores
  `CLAUDE_CODE_OAUTH_TOKEN` via `save_env_value` into `~/.zeb/.env` in cleartext;
  provider keys live the same way. `api_key_env_vars` span
  `ANTHROPIC_API_KEY/ANTHROPIC_TOKEN/CLAUDE_CODE_OAUTH_TOKEN`.
- **Why:** plaintext long-lived credentials on disk, world-readable if perms slip,
  and grep-able by any compromised tool/skill running in-process.
- **Fix:** OS keychain integration (Keychain/DPAPI/libsecret) with `.env` as the
  explicit fallback; encrypt-at-rest with a machine-bound key; scope token
  lifetime and support rotation from the UI.

### P1-5. In-process, process-wide model singleton pins global state
- **Evidence:** `agent/llama_cpp_adapter.py::_load_model` caches one `Llama`
  keyed only on path; whichever caller loads first fixes `n_ctx` for **everyone**
  (the exact class of bug that pinned context to 4K earlier this session). Three
  construction sites (`agent_init`, `auxiliary_client`, adapter default) had to be
  kept in lockstep by hand.
- **Why:** shared mutable global with no invalidation contract; concurrency and
  multi-config scenarios are fragile; correctness depends on call ordering.
- **Fix:** a real model manager with an explicit (path, n_ctx, n_threads) cache
  key, reference counting, and a documented reload/evict API — not a
  first-writer-wins module global.

### P1-6. Offline-first promise is undermined by network-time downloads with no integrity pinning
- **Evidence:** `local_model_manager.ensure_local_model_weights` resolves the GGUF
  filename by **listing the HF repo at runtime** and downloads via `hf_hub_download`
  with no sha256/expected-digest verification of the final artifact (size is
  "best effort" only). The superpowers dev-skills hook (separate branch) similarly
  `git clone`s at session start.
- **Why:** "runs offline with no keys" is the headline, yet first boot hard-depends
  on reaching huggingface.co, and the downloaded multi-GB binary is trusted without
  a pinned hash — a supply-chain gap inconsistent with the (excellent) pip-pinning
  discipline elsewhere.
- **Fix:** pin the exact filename **and sha256** per (repo, quant); verify after
  download; ship a documented air-gapped path (`local_model.path`) as a
  first-class, tested flow, not an escape hatch.

---

## P2 — FEATURE GAPS (missing essentials for the category)

- **P2-1. No unified observability/tracing.** Health checks (`gateway/self_healing.py`)
  and forensics exist, but there is no request tracing, no per-turn token/cost
  accounting surfaced centrally, no structured event bus for "what did the agent
  do." A world-class agent platform needs an end-to-end trace of every turn
  (prompt → tool calls → files touched → tokens → cost).
- **P2-2. No permission/consent model for tool actions.** The agent has full
  workspace read/write; there is no per-action approval gate, no "dangerous action"
  classification surfaced to the user, no diff-before-apply for file writes in the
  agent path (the dashboard has a save button; the agent loop does not gate).
- **P2-3. No sandboxing of tool/skill execution.** Skills and MCP tools run
  in-process with the agent's full privileges. A malicious or buggy skill has the
  same reach as P0-1. Needs subprocess/container/seccomp isolation with a broker.
- **P2-4. No first-class backup/restore or state migration.** State lives in
  `~/.zeb` (`zeb_state.py` is 6,409 LOC) but there's no snapshot/restore command,
  no schema-versioned migrations surfaced, no export/import of a workspace.
- **P2-5. Autonomy has no global kill-switch UX or budget guardrails.** Bots run on
  timers with no surfaced "pause all autonomy," no per-bot spend/time budget, no
  rate ceiling. The dashboard should have a prominent autonomy master switch and
  live activity ledger.
- **P2-6. No SSO / no team model.** Single shared key precludes any multi-seat or
  org deployment — a hard ceiling on "compete with major systems."

---

## P3 — OPTIMIZATION OPPORTUNITIES

- **P3-1. Test collection >2 min** implies import-time side effects; lazy-import
  conftests and heavy modules to cut inner-loop latency dramatically.
- **P3-2. The vanilla dashboard re-fetches `/api/models` on every selector build**
  and polls `/api/status` every 800ms and `/api/localmodel` every 1.5s with no
  backoff when hidden — add visibility-aware polling and SSE/WebSocket push.
- **P3-3. Brain animation** (now a 2.5D canvas showpiece) runs `requestAnimationFrame`
  unconditionally even when the tab is hidden or the canvas is off-screen; gate on
  `document.hidden` and `IntersectionObserver` to save CPU/battery.
- **P3-4. Repeated `os.path.abspath`/`listdir` per request** in the files API with
  a 5,000-entry scan and re-sort; add pagination and a cached directory index
  (there is already `zeb_autonomy/file_index.py` — reuse it).
- **P3-5. Provider/plugin discovery globs the filesystem** on each call
  (`plugins/*/plugin.yaml`); cache manifests at boot with mtime invalidation.

---

## Domain deep-dives (what's working / broken / missing / redesign)

### Architecture & code structure
- **Working:** clear module boundaries at the top level (`agent`, `gateway`,
  `zeb_cli`, `tools`, `plugins`, `cron`, `zeb_autonomy`); lazy-import discipline
  in hot paths; fail-open philosophy in the dashboard API.
- **Broken:** god-files (P1-1); a single 8.4k-LOC `config.py` that is both schema,
  IO, env, and resolution; three model-construction sites kept in sync by hand.
- **Missing:** a documented layering/dependency-direction rule; an internal API
  contract between UI and backend; module-size CI enforcement.
- **Redesign:** decompose the top-5 god-files into packages; extract a typed
  `zeb_core` the CLI, gateway, chat server, and TUIs all depend on instead of
  cross-importing each other's internals.

### Security (see P0-1/2, P1-3/4, P2-2/3)
- **Working:** key crypto (192-bit, constant-time, 0600); exact-pin supply chain;
  OSV + `supply-chain-audit.yml`; the Mini-Shai-Hulud response documented in
  `pyproject.toml` is genuinely best-in-class dependency governance.
- **Broken:** network-exposed write-anywhere; secret-in-logs; no TLS; no authz
  granularity; plaintext token storage.
- **Missing:** threat model doc, sandbox, audit log, rate limiting, CSRF/Origin
  checks on state-changing endpoints.
- **Redesign:** treat the whole HTTP surface as **privileged**; default to
  loopback+TLS; capability tokens; broker all filesystem/tool access through a
  policy layer that a compromised skill cannot bypass.

### Autonomy (`zeb_autonomy/`)
- **Working:** clean registry with per-bot guarded registration (one bad bot
  doesn't sink the subsystem); has tests (`tests/autonomy/`); `self_improvement`
  writes only a reflection guide (low blast radius).
- **Broken:** enabled-by-default + `file_organizer` not-dry-run-by-default + raw
  `shutil.move` + no undo (P0-3).
- **Missing:** global kill switch, per-bot budgets, reversible action journal,
  consent for destructive actions.
- **Redesign:** every actor bot implements a `plan() → preview → apply()` contract
  with a reversible journal; nothing destructive runs without either dry-run or an
  explicit approval.

### Local model / offline
- **Working:** out-of-the-box Qwen2.5-7B GGUF at 64K, footprint-tuned for a 32GB
  VPS; auto-download; graceful degradation without keys; `/api/modelinfo` +
  `/status` self-awareness (added this session).
- **Broken:** singleton n_ctx pinning (P1-5); download integrity not pinned (P1-6).
- **Missing:** GPU-offload autodetection surfaced to the user; per-request model
  hot-swap without process restart; quantization picker with RAM math in the UI.
- **Redesign:** a model-manager service with explicit cache keys, integrity
  verification, and a documented air-gapped install path.

### UI / UX
- **Working:** the vanilla dashboard is coherent and now feature-rich (split-screen
  brain, `/status`, recent-chats, Anthropic subscription connect, files back-button
  — all verified in a headless browser this session with zero JS errors).
- **Broken:** four+ frontends (P1-2); no shared design system or component library
  across React/vanilla/TUI; polling instead of push.
- **Missing:** accessibility pass (keyboard nav, ARIA, contrast in both themes),
  i18n in the vanilla dashboard (the repo has `locales/` but the static dashboard
  is English-only), mobile layout for the dashboard.
- **Redesign:** one client, one contract, generated from OpenAPI; SSE/WebSocket for
  live state; a real design system.

### Testing / CI / dev-experience
- **Working:** 16 workflows incl. sliced parallel tests, typecheck, lint,
  docker-lint, OSV, supply-chain-audit, uv-lockfile-check; `tests/chat` (59) and
  `tests/autonomy` are green and meaningful.
- **Broken:** local repro depends on `uv sync` with an opaque failure otherwise;
  collection >2 min (P0-4).
- **Missing:** a documented one-command bootstrap; coverage reporting/gates;
  contract tests between UI and API; load/perf tests for the gateway.
- **Redesign:** fast-fail bootstrap check; split slow integration tests from unit;
  cache/parallelize collection.

### Packaging / deploy
- **Working:** Dockerfile + compose (Linux/Windows), Nix flake, uv.lock, PyPI
  publish workflow, exact pins. This is above-average.
- **Missing:** SBOM generation, image signing/provenance (cosign), a hardened
  non-root container user documented as default, healthcheck/liveness in compose.
- **Redesign:** ship signed images + SBOM; default the container to a non-root UID
  with a jailed workspace volume (ties into P0-1).

### Extensibility (plugins / skills / MCP)
- **Working:** rich plugin ecosystem (`plugins/` 104k LOC, platform adapters),
  skills system, MCP tool integration (`tools/mcp_tool.py` 5.3k LOC), lazy-dep
  install per backend.
- **Broken:** plugins/skills run in-process at full privilege (P2-3); provider
  discovery re-globs the FS per call (P3-5).
- **Missing:** a signed/verified skill registry; capability manifests declaring
  what a skill may touch; a sandbox broker.
- **Redesign:** skills declare capabilities; the runtime enforces them; a signed
  registry with provenance mirrors the (excellent) pip supply-chain model.

---

## Sequenced 90-day blueprint (do these in order)

**Weeks 1–2 — Stop the bleeding (all P0):**
1. Bind loopback by default; jail `/api/files*` to a workspace root; split read vs
   write capability. 2. Stop logging the key; issue a one-time enrollment URL.
3. Default `autonomy.enabled=false` and `file_organizer.dry_run=true`; add a move
   journal + `zeb autonomy undo`. 4. Make `uv sync` the blessed bootstrap; fail
   fast with a clear message; fix collection time.

**Weeks 3–6 — Structural integrity (P1-1, P1-3, P1-5):**
Decompose the top-3 god-files into packages behind unchanged public APIs (lean on
`test-driven-development` + `verification-before-completion` — characterize with
tests first, refactor under green). Introduce capability-scoped tokens + an audit
log. Replace the model singleton with a real manager.

**Weeks 7–10 — Consolidation (P1-2, P1-4, P1-6):**
Pick the React app as the one client; generate its API client from OpenAPI; demote
the vanilla dashboard to generated fallback. Keychain-backed secret storage. Pin
GGUF sha256 + verify; document + test the air-gapped path.

**Weeks 11–13 — Category-defining features (P2):**
Unified per-turn tracing + cost ledger; a tool-action consent/permission model; a
skill sandbox broker; autonomy master switch + budgets in the UI.

---

## Bottom line

ZebOS's **fundamentals are stronger than its framing**: the dependency governance,
CI breadth, and local-first design are genuinely good — better than most projects
that call themselves "world-class." What's blocking it is a small number of
**severe, concrete safety failures** (network-exposed write-anywhere, a
data-moving bot that's on-by-default with no undo, a credential printed to logs)
and a **maintainability debt** (20k-line files, four frontends) that will strangle
velocity as it grows. Fix the four P0s this month and the product goes from
"impressive but dangerous" to "trustworthy." Everything after that is about
earning the ambition in the name — by being the best **agent platform**, not by
pretending to be an OS.
