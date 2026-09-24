# Build Plan — Agentic Git Rebase System

> **Read first in every session:** this file and `docs/DECISIONS.md`. Don't re-explore the repo. Update both files when a decision changes.

- **Status:** Phase 1 done except two items:
  - The live BAML call hasn't run yet (no `ANTHROPIC_API_KEY` in the session).
  - Generator `--push` mode is deferred to Phase 4, because Q1 (the sandbox repo) is open.
- **Deadline:** demo on Mon Sept 28, 4 PM. The plan was written Thu Sept 24.

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
- Token usage comes from a BAML collector. Cost = usage × price table (Q7).
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
  | `semantic_break` | Record and report the orchestrator's action. Pass/fail depends on Q3. |

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
| `semantic_break` | if the orchestrator says auto_rebase: resolver `clean` → tests **fail** → `verifier.verdict == "escalate"`, `stage == "verifier"`. Also covered with `--force-resolve` (Q3). |
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
  - verifier catch (on `semantic_break`)
  - cost USD
  - latency s
- It also writes a totals row and the raw JSON.

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

---

## Open questions

Each question has a proposed answer, but none is decided. Please answer or approve.

- **Q1 — Sandbox and repo access.** Does `zhannahoe34/RebaseSandbox` exist, or should Phase 1 assume you'll create it? Is `Rebase` public? The sandbox workflow must check it out. If `Rebase` is private, `SANDBOX_REPO_TOKEN` also needs read on `Rebase`.
- **Q2 — What counts as "approved"?** A single account can't approve its own PR. *Proposal:* PRs labelled `approved` are eligible. Alternatives: all open non-draft PRs, or PRs with an APPROVED review from a second account.
- **Q3 — Can `semantic_break` reach the verifier?** It depends on the orchestrator saying auto_rebase, but a strong orchestrator may escalate first after reading "signature changed" + "adds calls". That would hide the headline case. *Proposal:*
  1. Symbol overlap covers modified definitions only, not call sites.
  2. Acceptance: final is escalate, with `stage == "verifier"` whenever the orchestrator chose auto_rebase.
  3. Add a `--force-resolve` flag that skips the orchestrator (policy still enforced) so the demo can show the verifier catch deterministically.

  **Need your call:** does an orchestrator-stage escalation on `semantic_break` count as a pass?
- **Q4 — Stale check vs `real_conflict`.** Strict range-diff flags any conflict resolution, because context changes, so `real_conflict` would always escalate. *Proposal:*
  - "patch unchanged" means identical added and removed lines per commit, ignoring context and hunk headers
  - `real_conflict` is designed so a correct resolution keeps both sides' lines intact
- **Q5 — GitHub demo layout.** All scenarios can't share one `main`, because a lockfile change on `main` would escalate every PR. *Proposal:*
  - **Wave A:** one merged change, with `trivial`, `real_conflict` and `semantic_break` PRs. This shows the matrix fan-out.
  - **Wave B:** a merged change that adds a migration and bumps the lockfile, with `migration_collision` and `lockfile_touch` PRs.
  - Locally, every scenario is still its own isolated repo.
- **Q6 — Confidence floor.** Should `combine` escalate when `confidence < 0.7` even if the action is auto_rebase? *Proposal:* yes, 0.7, configurable.
- **Q7 — Cost numbers.** Cost is estimated from reported token usage × a per-model price table in `config.py`, filled from Anthropic's published pricing at implementation time. Is an estimate acceptable in PR comments?
- **Q8 — Generated `baml_client/`.** *Proposal:* gitignore it and generate in `make` and CI. The alternative is to commit it so Actions skips the generate step. *Phase 1 went with the proposal for now (`.gitignore`, `make generate`); easy to reverse.*
- **Q9 — Resolver caps.** *Proposal:* 20 turns and $1.00 per PR. OK?
- **Q10 — Eval repetitions.** N=1 (cheap, noisy) or N=3 (better signal, ~3× cost and time)? *Proposal:* N=1, and N=3 for the orchestrator only if time allows.
- **Q11 — Which "config" files force escalation?** The brief names migrations, auth, lockfiles and CI as hard rules. *Proposal:* "config" files are a signal only, not a forced escalation, unless you list specific paths.
- **Q12 — Auth paths.** *Proposal:* `**/auth/**` and `**/*auth*.py` in the sandbox template. Any others?
