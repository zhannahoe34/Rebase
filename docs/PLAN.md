# Build Plan — Agentic Git Rebase System

> **Read first in every session:** this file and `docs/DECISIONS.md`. Don't re-explore the repo. Update both files when a decision changes.

- **Status:** Phase 1 done ([zhannahoe34/Rebase#2](https://github.com/zhannahoe34/Rebase/pull/2)), except two items:
  - The live BAML call hasn't run yet (no `ANTHROPIC_API_KEY` in that session).
  - Generator `--push` mode is deferred to Phase 4.
- **Next:** Phase 2 (review gate).
- **Deadline:** demo on Mon Sept 28, 4 PM. The plan was written Thu Sept 24.

---

## Handoff: start of the next session

### 1. Get the code
- If PR #2 is merged, branch from `main`.
- If PR #2 is still open, branch from `claude/agentic-rebase-plan-tpyyi7`, which has all of Phase 1.

Either way, create a new branch for Phase 2; that's one PR per phase.

### 2. Set up and check the key (don't skip)
```bash
uv sync
make generate      # baml_client is gitignored; nothing imports until this runs
make baml-smoke    # must be 5 passed, 0 skipped: the live call proves ANTHROPIC_API_KEY works
make test && make lint
make sandbox       # builds .sandbox/<scenario> local repos
```
If the live call is skipped or fails, stop and tell the user before doing any Phase 2 work: every Phase 2 acceptance test needs a real LLM.

### 3. Things already learned (don't re-discover them)
- **BAML 0.226.2 API** (checked in Phase 1):
  - `ClientRegistry().add_llm_client(name=, provider="anthropic", options={"model": ...})`, then `.set_primary(name)`.
  - Call with `b.with_options(client_registry=..., collector=Collector(name=...)).Fn(...)`.
  - The collector exposes `.last` and `.usage`. `b.request.Fn(...)` builds the HTTP request offline.
  - The generated client needs `pydantic` and `typing-extensions`, both pinned.
- **Ruff 0.16:**
  - It enforces `PLW1510` (every `subprocess.run` needs an explicit `check=`).
  - It formats Python blocks inside Markdown, so `docs/` is excluded in `pyproject.toml`.
- **Where scenario PR title, body and expected outcome live:** `sandbox_gen.scenarios.SCENARIOS[name]` (`.merged`, `.pr`, `.expected`). They're also in the commit messages. In the local repos: tag `base` = main before the push, `main` = after, and `pr/<name>` = the PR.
- **Signals:** `rebase_agent.signals.compute_signals(repo, base, merged, pr_head)`. Path classifiers are in `rebase_agent/config.py`; policy should reuse them, not duplicate them.
- **Git conventions (user preference):** no `Co-Authored-By`, `Claude-Session` or other attribution lines in commits or PR descriptions.

### 4. Phase 2 checklist (details in the Phase 2 section)
1. **Price table:** get current per-model prices from Anthropic's published pricing (the `claude-api` skill or the docs). Store them in `config.py` with the source URL and date. Never guess.
2. **Types:** add `PRSummary`, `Decision`, `PolicyResult`, `FinalDecision` and the ledger row types to `models.py`, following §0.4.
3. **BAML functions:**
   - `baml_src/analysts.baml`: `SummarizeChange`
   - `baml_src/orchestrator.baml`: `DecideRebase`

   Models come from env/config via `ClientRegistry`, never hardcoded (§0.2). Delete `smoke.baml` only if the smoke test moves onto a real function.
4. **Cost ledger** (§0.6): one JSONL row per call, plus a `rebase-agent costs <run_dir>` command.
5. **Policy:** `policy.py` with `apply_policy` and `combine`. Add a property test that policy escalation can never be overridden. Add the 0.7 confidence floor as a configurable setting, and say in the PR that Q6 is still open.
6. **CLI:**
   - `rebase-agent decide`: one PR, prints the `FinalDecision` plus cost.
   - `rebase-agent setup`: computes the merged summary once and writes JSON.
7. **Scenario tests** (`@pytest.mark.llm`, real LLM, never mocked):
   - policy scenarios → escalate, with the rule named
   - trivial and real_conflict → auto_rebase
   - semantic_break → record the orchestrator's decision as a note, not pass/fail (Q3)
8. **Wrap-up:** update this file and DECISIONS.md, open the Phase 2 PR (what works, what doesn't, exact commands, total LLM spend), then **stop for review**.

### 5. Coming later
- **Phase 4 needs `RebaseSandbox` access.** Try `add_repo` first; if that fails, stop and ask the user to switch the session's repo.
- **Q2b** (a GitHub App token for authoring sandbox PRs) and **Q5** (per-scenario base branches) need confirming at the start of Phase 4.

---

## 0. Cross-cutting

### 0.1 Pinned dependencies

These are the latest PyPI releases as of 2026-09-24. Exact pins go in `pyproject.toml`, and `uv.lock` is committed.

| Package | Pin | Used for |
|---|---|---|
| `baml-py` | `==0.226.2` | Analysts, orchestrator, verifier intent check. The `generators.baml` block uses `version "0.226.2"`, which must match. |
| `claude-agent-sdk` | `==0.2.159` | Resolver agent loop |
| `mcp` | `==2.2.0` | Our stdio MCP server and the resolver's MCP client config |
| `pydantic` | `==2.13.5` | Internal types. The generated `baml_client` also needs it, but `baml-py` doesn't install it (found in the Phase 1 smoke test). |
| `typing-extensions` | `==4.16.0` | Imported by the generated `baml_client`; not installed by `baml-py` either |
| `typer` | `==0.27.2` | CLIs |
| `httpx` | pinned in Phase 1 (latest) | GitHub REST (list PRs, comments) |
| `pytest` | `==9.1.1` | Tests (dev) |
| `ruff` | `==0.16.8` | Lint and format (dev) |

Tooling needed:
- Python 3.12 (`.python-version`)
- `uv >= 0.8.17`
- `git >= 2.38`, for `git merge-tree --write-tree` (this environment has 2.43)

We don't need an AST library: the sandbox code is Python, so symbol extraction uses the stdlib `ast` module.

### 0.2 Environment variables and secrets

| Var | Where | Default | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | local and Actions secret | — | Needed for all LLM calls |
| `SANDBOX_REPO_TOKEN` | local and Actions secret | — | PAT or App token with contents and PR write on the sandbox. Needs `workflow` scope if the generator pushes `.github/workflows/*`. **Never `GITHUB_TOKEN`.** |
| `SANDBOX_REPO` | local and Actions var | `zhannahoe34/RebaseSandbox` (see Q1) | `owner/name` |
| `REBASE_MODEL_ANALYST` | env or config | `claude-haiku-4-5-20251001` | |
| `REBASE_MODEL_ORCHESTRATOR` | env or config | `claude-sonnet-5` | Sweep: Haiku 4.5, Sonnet 5, Opus 5.5 (`claude-opus-5-5`) |
| `REBASE_MODEL_RESOLVER` | env or config | `claude-sonnet-5` | |
| `REBASE_MODEL_VERIFIER` | env or config | `claude-sonnet-5` | |
| `REBASE_RESOLVER_MAX_TURNS` | env or config | `20` | Q9 |
| `REBASE_RESOLVER_MAX_USD` | env or config | `1.00` | Q9 |

Models are never hardcoded. The defaults above live only in `config.py` and can be overridden.

### 0.3 Proposed repo layout

```
pyproject.toml  uv.lock  Makefile  .python-version  README.md
baml_src/
  generators.baml        # python/pydantic generator, pinned version
  clients.baml           # one client per model; selected at runtime via ClientRegistry
  analysts.baml          # SummarizeChange
  orchestrator.baml      # DecideRebase
  verifier.baml          # CheckIntent
src/rebase_agent/
  config.py              # Settings (env → models, caps, policy globs, price table)
  models.py              # pydantic types (below)
  git_ops.py             # subprocess git wrappers (clone, merge-tree, rebase, range-diff, push)
  github_api.py          # httpx: list open PRs, get PR, post comment
  signals/
    conflicts.py         # merge-tree dry run → conflict count/files
    overlap.py           # file overlap, diff size
    symbols.py           # ast: defs touched per side → symbol overlap
    classify.py          # lockfile / migration / ci / config / auth path classifiers
    compute.py           # compute_signals()
  analysts.py            # summarize_change() via BAML
  orchestrator.py        # decide() via BAML
  policy.py              # apply_policy(), combine()  — pure, no LLM
  resolver/
    agent.py             # resolve(): Agent SDK loop
    tools.py             # workdir-scoped custom tools (no push)
    budget.py            # turn + USD accounting from reported usage
  mcp_server/
    server.py            # stdio: conflict_preview, symbol_overlap
  verifier.py            # tests + CheckIntent
  stale.py               # range-diff check
  report.py              # RunOutcome → markdown PR comment
  pipeline.py            # run_pr(): end-to-end per PR
  cli.py                 # `rebase-agent` typer app
  baml_client/           # generated (Q8)
src/sandbox_gen/         # under src/ so uv_build packages it next to rebase_agent
  generator.py           # `rebase-sandbox` CLI
  template/              # tiny Python pkg + pytest suite + migrations/ + uv.lock + workflow yml
  assets/                # scenario-specific files (e.g. the bumped uv.lock)
  scenarios/{base,trivial,real_conflict,semantic_break,migration_collision,lockfile_touch}.py
skills/rebase-playbook/SKILL.md
eval/
  run_eval.py
  results/               # dated markdown tables
tests/
  unit/                  # no network, real git in tmp dirs
  scenarios/             # @pytest.mark.llm — real LLM, real git
.github/workflows/ci.yml # ruff + unit tests only (this repo)
docs/  PLAN.md  DECISIONS.md  demo/
```

### 0.4 Key interfaces

In `src/rebase_agent/models.py`. The BAML classes for `PRSummary`, `Decision` and the intent-check result mirror these field for field.

```python
Category = Literal["lockfile", "migration", "ci", "config", "auth"]

class TouchInfo(BaseModel):
    merged: list[str]          # paths in the merged change in this category
    pr: list[str]              # paths in the PR in this category

class Signals(BaseModel):
    conflict_count: int                 # conflicted files from merge-tree dry run
    conflicted_files: list[str]
    file_overlap: list[str]             # paths changed by both sides
    symbol_overlap: list[str]           # "module:qualname" defs modified by both sides
    diff_lines_merged: int
    diff_lines_pr: int
    touches: dict[Category, TouchInfo]

class PRSummary(BaseModel):             # used for both merged change and PR
    intent: str
    touched_areas: list[str]
    behavior_changes: list[str]
    risk_notes: list[str]

class Decision(BaseModel):              # orchestrator output (BAML)
    action: Literal["auto_rebase", "escalate"]
    confidence: float                   # 0..1
    reasons: list[str]

class PolicyResult(BaseModel):
    force_escalate: bool
    rules_hit: list[str]                # e.g. "migration:pr+merged:migrations/0003_*.sql"

class FinalDecision(BaseModel):
    action: Literal["auto_rebase", "escalate"]
    orchestrator: Decision
    policy: PolicyResult

class ResolverResult(BaseModel):
    status: Literal["clean", "resolved", "escalated", "error"]
    reason: str | None                  # required when escalated/error
    turns: int
    cost_usd: float
    files_touched: list[str]
    head_sha: str | None

class VerifierResult(BaseModel):
    tests_passed: bool
    test_output_tail: str
    intent_preserved: bool
    intent_reasons: list[str]
    verdict: Literal["pass", "escalate"]

class StaleCheckResult(BaseModel):
    unchanged: bool
    range_diff: str

class CostBreakdown(BaseModel):
    per_stage_usd: dict[str, float]
    total_usd: float

class RunOutcome(BaseModel):            # rendered to the PR comment
    pr_number: int
    final: Literal["pushed", "escalated", "error"]
    stage: str                          # where it ended: policy/orchestrator/resolver/verifier/stale/push
    signals: Signals
    merged_summary: PRSummary
    pr_summary: PRSummary
    decision: FinalDecision
    resolver: ResolverResult | None
    verifier: VerifierResult | None
    stale: StaleCheckResult | None
    cost: CostBreakdown
    latency_s: float
```

Function signatures:

```python
def compute_signals(repo: Path, base: str, merged: str, pr_head: str) -> Signals
def summarize_change(diff: str, title: str, body: str, *, model: str) -> tuple[PRSummary, Usage]
def decide(signals: Signals, merged: PRSummary, pr: PRSummary, *, model: str) -> tuple[Decision, Usage]
def apply_policy(signals: Signals) -> PolicyResult
def combine(decision: Decision, policy: PolicyResult) -> FinalDecision   # pure; escalate if either says so
async def resolve(workdir: Path, onto: str, pr: PRSummary, caps: Caps, *, model: str) -> ResolverResult
def verify(workdir: Path, base: str, pr: PRSummary, *, model: str) -> VerifierResult
def stale_check(workdir: Path, old_base: str, old_head: str, new_base: str, new_head: str) -> StaleCheckResult
def run_pr(repo: str | Path, pr: PRRef, merged_summary: PRSummary, *, push: bool) -> RunOutcome
```

CLI commands:
- `rebase-agent signals|summarize|decide|run-pr|setup|comment`
- `rebase-sandbox generate [--scenario NAME|all] (--local DIR | --push)`

### 0.5 Pipeline per PR

```
signals ─┐
merged summary (once/run) ─┼─► orchestrator ─► combine(policy) ─► escalate → comment
PR summary ─┘                                   │
                                                 ▼ auto_rebase
                         throwaway clone → git rebase → clean? ─yes─┐
                                                   │no              │
                                                   ▼                │
                                        resolver (Agent SDK, caps)  │
                                                   ▼                ▼
                                   verifier (tests + CheckIntent) → stale check (range-diff)
                                                   ▼
                                  push --force-with-lease → comment (every outcome)
```

On a clean rebase the resolver agent is **not** invoked (`status="clean"`). This matters for `semantic_break`: the resolver must not "fix" the call site, so the verifier is the one that catches it.

### 0.6 Cost ledger (Q7)

Every dollar is recorded, so the demo can quote real numbers.

- **One ledger row per model call**, appended to a JSONL file: `runs/<run_id>/ledger.jsonl` locally, and uploaded as an Actions artifact in CI. Fields:
  - `run_id`, `pr`, `scenario`, `stage` (analyst_merged / analyst_pr / orchestrator / resolver / verifier_intent)
  - `model`
  - `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`
  - `usd_per_mtok` for each token kind, `cost_usd`, `cost_source`
  - `latency_s`, `timestamp`
- **Two cost sources, labelled:**
  - BAML calls use `estimated`: tokens from the BAML `Collector` × the price table.
  - Agent SDK calls use `sdk_reported`: the SDK's own reported cost. We also recompute it from tokens and log any difference.
- **Price table** in `config.py`, taken from Anthropic's published pricing when Phase 2 starts, with the source URL and date stored next to it. It is never guessed. A model missing from the table is an error, not $0.
- **Rollups:**
  - `rebase-agent costs runs/<run_id>` prints per-stage, per-PR, per-model and total spend.
  - The PR comment shows a per-stage breakdown and the total.
  - The eval table (Phase 5) has cost per scenario × model plus the grand total of the eval run itself.
- **Merged-change summary:** its cost is shown once per run, not per PR, and is also shown split across PRs, to show the saving from reuse.

---

## Phase 1 — Sandbox generator + deterministic signals CLI

**Goal:** reproducible scenarios, and a `signals` command that gives correct deterministic signals for each one. Before anything else, prove that the BAML toolchain works here.

**Steps**
1. **BAML smoke test (first task):**
   1. `uv add baml-py==0.226.2`, then `uv run baml-cli init` (or the pinned version's equivalent).
   2. Add a trivial function and run `uv run baml-cli generate`.
   3. Check that `from rebase_agent.baml_client import b` imports.
   4. If `ANTHROPIC_API_KEY` is set, make one live call.

   Wrap this as `make baml-smoke`. **If generation or import fails, stop the phase and report.**
2. `src/sandbox_gen/template/`: a small Python package (e.g. `shop/pricing.py`, `shop/inventory.py`, `shop/auth/…`) with a pytest suite, `migrations/0001_init.sql`, `migrations/0002_*.sql`, a `uv.lock`, and a CI workflow file.
3. Scenario modules. Each one defines `base` edits, `merged` edits, `pr` edits, `expected: ExpectedOutcome` and `expected_signals`.
4. Local mode: `generate --local DIR --scenario X` builds a git repo with `main` at merged, a `base` tag, and a `pr/X` branch.
5. Push mode: `generate --push` force-resets the sandbox repo and (re)opens the PRs. **Deferred to Phase 4:** it can't be tested until Q1 (the sandbox repo) and Q5 (the wave layout) are answered, so for now it exits with "not implemented" rather than shipping untested code.
6. Idempotency: fixed author/committer name, email and dates make commit SHAs deterministic.
7. The signals modules and the `rebase-agent signals` CLI (JSON output).

**Signal definitions**
- **conflict count:** from `git merge-tree --write-tree --name-only merged pr_head`.
- **symbol overlap:** `ast` definitions whose line span intersects a changed hunk, taken on both sides, then intersected. It covers definitions only, not call sites (see Q3).
- **classifiers:** globs in `config.py`:
  - lockfile: `uv.lock`, `poetry.lock`, `package-lock.json`, …
  - migration: `migrations/**`
  - ci: `.github/workflows/**`
  - config: `*.toml`, `*.yaml` at the root
  - auth: `**/auth/**`

**Acceptance criteria**
- `uv run pytest tests/unit` is green, with snapshot tests of `Signals` for each scenario:

  | Scenario | Expected signals |
  |---|---|
  | `trivial` | `conflict_count == 0`, `file_overlap == []` |
  | `real_conflict` | `conflict_count >= 1`, the target function in `symbol_overlap` |
  | `semantic_break` | `conflict_count == 0`, `symbol_overlap == []` |
  | `migration_collision` | `touches["migration"].merged` and `.pr` both non-empty, with the same migration number |
  | `lockfile_touch` | `touches["lockfile"].merged` non-empty |

- For `trivial` and `semantic_break`, applying the PR onto merged runs cleanly with `git rebase`. For `semantic_break`, the sandbox tests **fail** after the rebase. The generator test proves this, so the scenario really is broken.
- Idempotency test: generating twice gives identical SHAs.
- `make baml-smoke` passes.

**Mocked vs real:** everything is real (real git in tmp dirs). There is no LLM except the optional smoke call.

**Risk:** low–medium (BAML toolchain). **Estimate:** ~5 h.

**Check-in:** none required. Runs end to end.

---

## Phase 2 — Analysts + orchestrator + policy guardrails  ⛔ REVIEW GATE

**Goal:** a per-PR decision from real LLM calls, with policy enforced in code.

**Work**
- `baml_src/analysts.baml` has `SummarizeChange(diff, title, body) -> PRSummary`. `baml_src/orchestrator.baml` has `DecideRebase(signals, merged, pr) -> Decision`. The prompts say the orchestrator has no repo access and must give reasons.
- The model is chosen at runtime with a BAML `ClientRegistry` built from `config.py`. Check the exact API against the 0.226.2 docs.
- Token usage comes from a BAML collector. Every call writes a cost ledger row (§0.6), and `rebase-agent costs` reports the rollups.
- `policy.py` has two pieces:
  - `apply_policy(signals)` hits a rule if the merged change or the PR touches migration, lockfile, ci or auth. Config files are reported but not forced (Q11).
  - `combine()`: `action = "escalate" if policy.force_escalate or decision.action == "escalate" else "auto_rebase"`.
  - The confidence floor (Q6) also lives in `combine`.
- CLI:
  - `rebase-agent decide --repo DIR --pr-branch B` prints the `FinalDecision` JSON.
  - `rebase-agent setup` computes the merged summary once and writes it to JSON for reuse.

**Acceptance criteria**
- Unit tests (no LLM needed):
  - Exhaustive or property test of `combine`: whenever `policy.force_escalate` is true, the result is `escalate` for every `Decision` (action, confidence).
  - Tests for each rule in `apply_policy`.
- Scenario tests, `@pytest.mark.llm`, **real LLM** with the default models:

  | Scenario | Expected |
  |---|---|
  | `migration_collision` | `final.action == "escalate"`, the migration rule in `rules_hit` |
  | `lockfile_touch` | `final.action == "escalate"`, the lockfile rule in `rules_hit` |
  | `trivial` | `final.action == "auto_rebase"` |
  | `real_conflict` | `final.action == "auto_rebase"` |
  | `semantic_break` | Not pass/fail: record the orchestrator's action and reasons in the test output (Q3). The pass/fail check is `--force-resolve` in Phase 3. |

- Test that the merged-change summary is computed once per run: a call counter on `summarize_change` in the pipeline test.

**Mocked vs real:**
- `combine` and policy unit tests use hand-built `Decision` objects. That tests the combine logic, not the LLM.
- Scenario acceptance tests never mock the LLM. Without `ANTHROPIC_API_KEY` they are **reported as not run**, never as passed.

**Risk:** medium (LLM decision variance on `real_conflict` and `semantic_break`). **Estimate:** ~5 h.

**Check-in: stop here for review.**

---

## Phase 3 — MCP server, skill, resolver, verifier, stale check  ⛔ REVIEW GATE (highest risk)

**Goal:** the full local pipeline via `rebase-agent run-pr --repo DIR --pr-branch B` (no push). Its output is a `RunOutcome` and the rendered comment markdown.

**MCP server** (`mcp_server/server.py`, stdio, built with the `mcp` 2.2.0 server API):
- `conflict_preview(repo_path, onto, head) -> {conflicted_files, hunks}`, which wraps `git merge-tree`.
- `symbol_overlap(repo_path, base, a, b) -> list[str]`, which reuses `signals/symbols.py`.
- Every path is validated to be inside the resolver's workdir.

**Skill** (`skills/rebase-playbook/SKILL.md`, under ~60 lines):
- Preview the conflicts first (`conflict_preview`).
- Resolve only conflict hunks, and keep both sides' intent.
- Never change code outside conflicted hunks.
- Run the tests after each file.
- If unsure, or the conflict isn't resolvable, stop and report `escalate` with a reason.
- Never push.

**Resolver** (`resolver/agent.py`):
- Throwaway `git clone` into `tempfile.mkdtemp()`, then `git rebase <merged>`. If the rebase is clean, return `status="clean"` without calling the agent.
- On conflict, run the Agent SDK with:
  - `cwd=workdir`
  - built-in Bash/Write/Edit disabled
  - custom in-process tools from `resolver/tools.py`: `read_file`, `write_file`, `list_conflicts`, `run_tests`, `git_add`, `rebase_continue`. Each one resolves the path and rejects anything outside workdir. There is no push or remote tool, and the clone's remote URL is stripped.
  - our stdio server as an MCP server
  - the skill loaded, through the pinned SDK's skills mechanism, or else injected into the system prompt
- Caps:
  - `max_turns` is passed to the SDK and also counted.
  - USD is accumulated from each reported usage/result message by `budget.py`.
  - If either cap is exceeded, interrupt and return `status="escalated"` with a reason such as `"max_turns 20 reached"`.
  - Any exception returns `status="error"` with a reason. It never fails silently.

**Verifier** (`verifier.py`):
1. `uv run pytest -q` in the workdir. Keep the output tail.
2. BAML `CheckIntent(pr_summary, resolved_diff) -> {intent_preserved, reasons}`, where `resolved_diff = git diff <merged>..HEAD`.
3. `verdict = "pass"` only if the tests pass **and** the intent is preserved.

**Stale check** (`stale.py`): `git range-diff old_base..old_head new_base..new_head`. `unchanged` is true only if every commit pair has identical added and removed lines, ignoring context and hunk headers (Q4). New, dropped or reordered commits mean escalate.

**Pipeline** (`pipeline.py`): wires everything as in §0.5 and records per-stage cost and latency. `report.py` renders the comment:
- decision and reasons
- policy rules hit
- signals table
- resolver/verifier/stale results
- cost and latency

**Acceptance criteria** (real LLM, `@pytest.mark.llm`)

| Scenario | Expected |
|---|---|
| `trivial` | resolver `clean` → verifier `pass` → stale `unchanged` → `final == "pushed"` (dry-run: "would push") |
| `real_conflict` | resolver `resolved` → tests pass → verifier `pass` → stale `unchanged` → would push |
| `semantic_break` | **Pass/fail via `--force-resolve`:** resolver `clean` → tests **fail** → `verifier.verdict == "escalate"`, `stage == "verifier"`, `final == "escalated"`. On the normal path, the orchestrator's decision is recorded as a note, not pass/fail (Q3). |
| `migration_collision`, `lockfile_touch` | `stage == "policy"`, resolver never constructed (asserted) |
| Cap test | `real_conflict` with `max_turns=1` → `status == "escalated"` and a reason that names the cap |

Unit tests (no LLM):
- tool path-escape rejection
- MCP tools called through an in-process MCP client session
- range-diff parser on fixture outputs
- report rendering snapshot

**Mocked vs real:** unit tests have no LLM and use real git. All scenario acceptance tests use the real LLM and the real Agent SDK.

**Risk:** **high**. Unknowns:
- Agent SDK tool scoping and skills loading in 0.2.159
- accuracy of the cost accounting
- resolver behaviour on `real_conflict`

**Estimate:** ~12 h (Sat–Sun), with buffer.

**Check-in: stop here for review.**

---

## Phase 4 — GitHub Actions wiring

**Goal:** a push to sandbox `main` rebases or escalates every eligible open PR on GitHub, and each one gets a comment.

**Work**
- The workflow is `src/sandbox_gen/template/.github/workflows/rebase.yml`, installed into the sandbox by the generator.
  - `on: push: branches: [main]`
  - `concurrency: rebase-${{ github.ref }}`
- **setup job:**
  1. Checkout the sandbox.
  2. Checkout `zhannahoe34/Rebase` at a pinned ref (Q1).
  3. `uv sync`, then `rebase-agent setup`. This lists eligible open PRs (Q2) with `SANDBOX_REPO_TOKEN`, computes the merged summary once, and emits the matrix JSON plus a summary artifact.
- **rebase job:**
  - `strategy.matrix.pr: ${{ fromJson(needs.setup.outputs.prs) }}`, with `fail-fast: false`.
  - It runs `rebase-agent run-pr --pr N --push --merged-summary summary.json`.
- **Push:** `git push --force-with-lease=refs/heads/<branch>:<expected_old_sha>` over `https://x-access-token:${SANDBOX_REPO_TOKEN}@github.com/...`. Only PR branches are pushed and `main` never is, so there is no retrigger loop.
- **Comment:** `github_api.post_comment` on every outcome. Errors are commented too.
- `ci.yml` in this repo runs ruff and unit tests only.

**Acceptance criteria**
- `rebase-sandbox generate --push --scenario <wave>` (Q5) causes one workflow run with N matrix legs. Each PR gets a comment that matches its expected outcome.
- The `trivial` and `real_conflict` branches are force-pushed, and the sandbox CI re-runs on them (which proves a non-`GITHUB_TOKEN` push).
- The PR description links to the run URLs.
- Rerunning the generator resets everything cleanly.

**Mocked vs real:** all real, against the sandbox repo only.

**Risk:** medium (tokens and permissions, Actions debug loop). **Estimate:** ~4 h.

**Check-in:** none required.

---

## Phase 5 — Eval harness + results table

**Goal:** quantify decisions, resolution and verifier catches across models.

**Work** (`eval/run_eval.py`)
- Runs locally only, with no push: scenarios × orchestrator ∈ {Haiku 4.5, Sonnet 5, Opus 5.5} × resolver ∈ {Sonnet 5} (+ Opus 5.5 if time allows).
- Default repetitions `N=1` (Q10).
- The merged summary is computed once per scenario × analyst model.
- Output: `eval/results/YYYY-MM-DD.md`, with one row per (scenario, orch model, resolver model). Columns:
  - expected vs actual final
  - decision correct ✓/✗
  - resolution success
  - verifier catch (on `semantic_break`, run with `--force-resolve`)
  - orchestrator note (what it decided on the normal path; Q3)
  - cost USD (from the ledger, split by stage) and tokens
  - latency s
- It also writes a totals row (including the eval run's own total spend), the raw JSON and the ledger.

**Acceptance criteria**
- `uv run python eval/run_eval.py --models haiku,sonnet,opus` writes the table.
- Every cell comes from a real run. Failures appear as ✗, with the reason in the JSON.

**Mocked vs real:** real LLM only.

**Risk:** low–medium (cost and time). **Estimate:** ~3 h.

**Check-in:** none required.

---

## Phase 6 — README, diagram, recorded demo, `make demo`

**Work**
- A README covering what it does, the architecture, setup, env vars, the commands, and how to read a PR comment.
- A Mermaid diagram of the §0.5 flow and the agents/MCP/skill relationships.
- `make demo` resets the sandbox, generates the demo wave, and runs the local pipeline with pretty output, or triggers Actions with `DEMO_MODE=actions`.
- A fallback recording (asciinema cast or saved logs), plus screenshots or links of the PR comments, in `docs/demo/`.

**Acceptance criteria**
- A fresh clone plus env vars plus `make demo` reproduces the headline `semantic_break` escalation.

**Risk:** low. **Estimate:** ~2 h.

**Check-in:** none required.

---

## Schedule

| When | Work |
|---|---|
| Thu 9/24 | Phase 1 |
| Fri 9/25 | Phase 2, then **review gate** |
| Sat–Sun 9/26–27 | Phase 3, then **review gate** |
| Sun 9/27 evening | Phase 4 |
| Mon 9/28 AM | Phases 5–6 |
| Mon 4 PM | Demo |

Phase 3 is the critical path, and the review gates add wall-clock latency.

**Cut order if late:** resolver sweep → Opus in the sweep → eval latency column → the push-mode polish in the generator.

Never cut: policy tests, the verifier, or honest PR notes.

---

## Working rules (all phases)

1. **One PR per phase.** Each PR description states what works, what doesn't, and how to verify it with exact commands.
2. **Honesty over completeness.**
   - Never weaken, skip or fake a test to get to green.
   - Never mock the LLM in scenario acceptance tests. LLM tests that didn't run (for example, no key) are reported as not run.
   - If a phase isn't fully working, say so plainly in the PR. A plausible-but-wrong PR is worse than an honest "not done".
3. **Check-ins.** Phases 1, 4 and 6 may run end to end. **Phases 2 and 3 are review gates:** stop at the end with a clear summary and wait for review.
4. **Token discipline.** Future sessions read `docs/PLAN.md` and `docs/DECISIONS.md` first instead of re-exploring. Keep both updated when decisions change.
5. **Cut scope, not quality.** One MCP server, one skill, a small model sweep, range-diff only for stale approvals.
6. Local CLI first. The whole pipeline must work against a local clone before Phase 4.
7. Only the sandbox repo, never a real work repo. Never use `GITHUB_TOKEN` for pushes.
8. No attribution lines (`Co-Authored-By`, `Claude-Session`, "Generated with…") in commits or PR descriptions.

---

## Questions: answered (review of 2026-09-24)

- **Q1 — Sandbox repo.** `zhannahoe34/RebaseSandbox` exists. The session may only get access to one repo at a time. **Action:** before Phase 4 needs the sandbox, stop and ask the user to switch access (try `add_repo` first).
- **Q2 — Approval.** The user approves sandbox PRs on GitHub themselves, and eligibility = at least one APPROVED review. **Caveat (still open, see Q2b):** GitHub doesn't let an account approve a PR it authored, and PRs opened with the user's own PAT are authored by the user.
- **Q3 — `semantic_break`.** Don't count an orchestrator-stage escalation as a pass. Instead:
  - Build the deterministic path: `--force-resolve` skips the orchestrator (policy still enforced). With it, the acceptance test requires `stage == "verifier"` and `final == "escalated"`.
  - On the normal path, record what the orchestrator decided (the stage, decision and reasons) in test output and the eval table, as a note rather than a pass or fail.
  - Symbol overlap stays definitions-only (done in Phase 1).
- **Q4 — Stale check.** Accepted: "patch unchanged" means identical added and removed lines per commit, ignoring context and hunk headers. `real_conflict` already has this property (tested in Phase 1).
- **Q5 — GitHub layout.** Not final, but the user prefers **branches over reusing `main`**. Working proposal for Phase 4:
  - Each scenario (or wave) gets its own long-lived base branch, e.g. `base/<scenario>`, that stands in for `main`.
  - PRs target that branch, and the workflow triggers on pushes to `main` and `base/**`.
  - All scenarios then coexist in the sandbox without resets clobbering each other.

  Confirm this at the start of Phase 4.
- **Q6 — Confidence floor.** Deferred; the user wants the meaning of "escalate" clarified first. **Escalate** means the system does **not** rebase or push: the PR branch stays as it is, and a PR comment explains why (decision, reasons, signals, cost) so a human handles it. Proposal unchanged: an auto_rebase with confidence < 0.7 is treated as escalate.
- **Q7 — Cost transparency.** Yes, and in depth: record every dollar. See §0.6 (cost ledger).
- **Q8 — Generated `baml_client/`.** Gitignored, generated by `make generate` and CI (done).
- **Q9 — Resolver caps.** 20 turns and $1.00 per PR (defaults, configurable).
- **Q10 — Eval repetitions.** N=1 by default; N=3 for the orchestrator if time allows.

## Open questions

- **Q2b — Who authors sandbox PRs?** If the generator opens PRs with the user's PAT, the user is the author and GitHub blocks self-approval. Options:
  1. **GitHub App token** for the generator, so PRs are authored by the app's bot account and the user can approve. It also satisfies "PAT or App token".
  2. A second GitHub account opens the PRs.
  3. Fall back to the `approved` label.

  *Proposal:* option 1, else option 3.
- **Q6 — Confidence floor**, see above.
- **Q11 — Which "config" files force escalation?** The brief names migrations, auth, lockfiles and CI as hard rules. *Proposal:* "config" files are a signal only, not a forced escalation, unless you list specific paths.
- **Q12 — Auth paths.** *Proposal:* `**/auth/**` and `**/*auth*.py` (as implemented in Phase 1). Any others?
