# Interview Deep-Dive Cheat Sheet

Read `docs/DECISIONS.md` and `docs/PLAN.md` for the *why*. This is the *how*, grounded in the
code as it stands on branch `claude/serene-volta-qf6ed8` (current HEAD as of 2026-09-28). Every
implementation claim below cites `path:line` or a function name. Anything I could not confirm in
code is marked **UNVERIFIED**. Re-ran `uv run pytest tests/unit -q` myself today: **332 passed**
in ~201s, matching `docs/PLAN.md`'s recorded count.

---

## 1. 60-second walkthrough

**Say out loud:** "When a change lands on `main` in the sandbox repo, a GitHub Actions workflow
lists every open, *approved* PR and, for each one, runs a pipeline: compute deterministic git
signals, have one LLM summarize the PR and another decide auto-rebase-or-escalate, let a
hard-coded policy veto risky paths regardless of what the LLM said, and — only if the answer is
auto-rebase — hand a tool-using Claude agent a throwaway clone to finish the rebase. A verifier
then reruns the tests and asks a third LLM call whether the PR's intent survived, a `git
range-diff` check confirms the PR's own reviewed lines weren't quietly changed, and only then does
it force-push the branch. Every outcome — pushed, escalated, or errored — gets a PR comment with
the reasons, the signals, and the exact dollar cost."

**Supporting detail:** the whole thing is `rebase_agent.pipeline.run_pr()`
([pipeline.py:133](../src/rebase_agent/pipeline.py)), described further in §2. It never raises —
every path returns a `RunOutcome` (`pipeline.py:242-243`).

---

## 2. Trace of one PR (push-to-main → PR comment)

**Say out loud:** "A push to `main` fires `rebase.yml`; a setup job computes the merged-change
summary once and lists eligible PRs; a matrix job runs the full per-PR pipeline and force-pushes
the resolved branch; the CLI posts a comment on every outcome, including errors."

### Trigger
`src/sandbox_gen/template/.github/workflows/rebase.yml` (installed into the sandbox repo by the
generator — this repo's own `.github/workflows/ci.yml` is a different, unrelated lint+test
workflow).

- `on: push: branches: [main]` (rebase.yml:5-7).
- `concurrency: { group: rebase-${{ github.ref }}, cancel-in-progress: false }` (rebase.yml:9-11)
  — same-ref pushes queue, they don't cancel each other (see §7 "two pushes").
- **Setup job guard** (rebase.yml:27): `!github.event.forced && github.event.before != <zero-sha>`
  — skips force-pushes and branch creation, so the sandbox generator's resets never fire the
  pipeline.

### Step 1 — setup job (rebase.yml:24-48)
Checks out the sandbox and this repo (`REBASE_REF`), `uv sync && baml-cli generate`, then:
```
uv run rebase-agent setup --repo ../sandbox --base <event.before> --merged <event.after> \
  --github-base <ref_name> --out summary.json --matrix-out prs.json
```
→ `cli.setup()` ([cli.py:50](../src/rebase_agent/cli.py)).
- **Input:** local clone path, before/after SHAs from the push event, target branch name.
- Lists PRs via `GitHub.open_prs(base=github_base)` and filters with `GitHub.eligibility(pr)`
  ([github_api.py:115-128](../src/rebase_agent/github_api.py)) — eligible iff the
  `rebase:approved` label is present, **or** the latest review per user is `APPROVED` with no
  outstanding `CHANGES_REQUESTED`.
- **Short-circuit:** zero eligible PRs → writes an empty matrix and returns *without* computing
  the merged summary — costs $0 (cli.py:86-88; unit-tested in
  `tests/unit/test_setup_cli.py:70-77`).
- Otherwise: `summarize_merged()` (`pipeline.py:34`) → one BAML `SummarizeChange` call (title/body
  of the merged commit + its diff) → `PRSummary`. **Output:** `summary.json` (reused by every PR)
  and `prs.json` (eligible PR numbers).
- Workflow-level short-circuit: `rebase` job has `if: needs.setup.outputs.prs != '[]'`
  (rebase.yml:52) — no eligible PRs, no matrix job at all.

### Step 2 — rebase job, one matrix leg per eligible PR (rebase.yml:50-75)
```
uv run rebase-agent run-pr --repo ../sandbox --pr N --base <before> --merged <after> \
  --merged-summary summary.json --push
```
→ `cli.run_pr_cmd()` (cli.py:121-193). Fetches the PR's **current** head SHA
(`gh.get_pr(pr)`, cli.py:154-155) and builds a `PushTarget(url, branch, expected_sha=head_sha)`
(cli.py:165) — this SHA is the lease for the eventual force-push.

### Step 3 — `pipeline.run_pr()` (pipeline.py:133-247) — the real state machine
| # | Stage | Function | Input → Output | Short-circuit |
|---|---|---|---|---|
| 1 | `signals` | `compute_signals(repo, base, merged, pr_branch)` (signals/compute.py:12) | 4 refs → `Signals` | none (pure git) |
| 2 | `analyst_pr` | `summarize_pr()` (pipeline.py:48) → BAML `SummarizeChange` | diff/title/body → `PRSummary` | none |
| 3 | `orchestrator`/`policy` | `_decide()` (pipeline.py:63) = `apply_policy()` (policy.py:19) + BAML `DecideRebase` (orchestrator.py:9) + `combine()` (policy.py:35) | `Signals`+2×`PRSummary` → `FinalDecision` | **escalate** → `done("escalated", "policy" if policy forced it else stage)` (pipeline.py:188-189) — no clone, no resolver, no verifier, no push |
| 4 | `resolver` (setup) | `prepare_workdir()` (resolver/agent.py:45) | repo+refs → throwaway clone | if the PR's live head has moved since step in §Step-2 (`head != push.expected_sha`) → escalate immediately, "PR head moved" (pipeline.py:193-196) |
| 5 | `resolver` | `resolve()` (resolver/agent.py:111) | workdir+`PRSummary`+`Caps` → `ResolverResult` | clean rebase → **agent never invoked**, `status="clean"` (agent.py:124-132). `status=="error"` → `done("error",...)` (pipeline.py:209-210). `status=="escalated"` (cap hit / explicit `escalate` tool / unresolved) → `done("escalated","resolver")` (pipeline.py:211-212) |
| 6 | `verifier` | `verify()` (verifier.py:17) | workdir+`PRSummary` → `VerifierResult` | `verdict=="escalate"` (tests failed **or** intent not preserved) → `done("escalated","verifier")` (pipeline.py:224-225) — **this is the `semantic_break` catch** |
| 7 | `stale` | `stale_check()` (stale.py:100) | old/new base+head → `StaleCheckResult` | changed **and not** `within_conflicts` → `done("escalated","stale")` (pipeline.py:232-233) |
| 8 | `push` | `git_push()` (github_api.py:153) | workdir+`PushTarget` → none | `PushRejected` (stale lease) → `done("escalated","push",...)` (pipeline.py:238-240) |
| 9 | — | else | | `done("pushed","push")` |

The entire function body is wrapped in `try/except Exception` (pipeline.py:242-243): any
unhandled exception at any stage becomes `final="error"` with the exception's type+message,
never a crash, never a silent drop.

### Step 4 — comment
Back in `cli.run_pr_cmd`: `report.render(outcome)` (report.py:28) builds the markdown;
`gh.post_comment(pr, text)` (github_api.py:130) posts it — comment defaults to `True` and fires
**on every outcome, errors included** (cli.py:189-191). Outcome JSON + rendered markdown +
`ledger.jsonl` are written next to each other and uploaded as an Actions artifact
(rebase.yml:73-75).

---

## 3. Component by component

### D3 — Deterministic signals
`Signals` (models.py:16-23): `conflict_count`, `conflicted_files`, `file_overlap`,
`symbol_overlap`, `diff_lines_merged`, `diff_lines_pr`, `touches: dict[Category, TouchInfo]`.

- **Conflict count:** `git merge-tree --write-tree --name-only --no-messages <merged> <pr_head>`
  (signals/conflicts.py:8-24); returncode 1 = conflicts, paths from stdout after the first line
  (the partial tree OID).
- **File/symbol overlap:** file overlap is a plain set intersection of `git diff --name-only`
  results (git_ops.py:28-30, compute.py:30). Symbol overlap
  (signals/symbols.py) parses both file versions with **stdlib `ast`**, computes `(qualname,
  first_line, last_line)` spans including nested defs and decorators (symbols.py:16-33), matches
  them against changed line numbers from a `-U0` diff via hunk-header regex (symbols.py:36-49),
  and reports `path:qualname` where **either side's** old-or-new span intersects a changed line
  (symbols.py:52-69). **Definitions only, not call sites** (PLAN.md Q3) — this is exactly why
  `semantic_break`/`behavior_change` don't show up as symbol overlap.
- **Classifiers** (signals/classify.py:9-25, globs in config.py:6-23):
  - `lockfile`: filename in `{uv.lock, poetry.lock, Pipfile.lock, package-lock.json, yarn.lock,
    pnpm-lock.yaml, Cargo.lock, go.sum, Gemfile.lock}`.
  - `migration`: path contains `/migrations/` or `/alembic/versions/`.
  - `ci`: path starts with `.github/workflows/`, `.gitlab-ci.yml`, or `.circleci/`.
  - `config`: root-level file named `Dockerfile`/`Makefile`/`.env`/`setup.py`, or root-level with
    suffix `.toml`/`.yaml`/`.yml`/`.ini`/`.cfg` (and not already a lockfile).
  - `auth`: `auth` is a parent directory component, **or** the file is `*.py` and `"auth"` is a
    substring of the stem (classify.py:23) — this is why `tests/test_auth_expiry.py` in the
    `auth_touch` scenario is itself classified `auth` (confirmed by
    `tests/unit/test_waves.py:106-107`, which asserts the rule fires exactly once for that PR).

### D4 — Analyst agents
`analysts.summarize_change()` (analysts.py:11-31) wraps BAML `SummarizeChange(title, body, diff)
-> PRSummary` (analysts.baml:11). Default model `claude-haiku-4-5-20251001`
(config.py:32). Refuses (doesn't silently truncate) diffs over `MAX_DIFF_CHARS = 200_000`
(analysts.py:8). Merged-change summary is computed **once per run** and threaded through:
`pipeline.decide_all()` (pipeline.py:104-118) and `pipeline.run_pr()` both take an already-computed
`merged_summary` argument; unit-tested with a call-counting stub in
`tests/unit/test_pipeline.py:14-33` (`analyst_merged` called exactly once across 3 PRs).

### D5 — Orchestrator
`orchestrator.decide()` (orchestrator.py:9-30) wraps BAML `DecideRebase(signals, merged, pr) ->
Decision` (orchestrator.baml:25). Default model `claude-sonnet-5` (config.py:33).
`Decision` (models.py:33-36): `action: Literal["auto_rebase","escalate"]`, `confidence: float`,
`reasons: list[str]`. **No repo access** — the BAML function's only params are the `Signals`
struct and two `PRSummary` structs; there is no tool, no file path, nothing else it can see.

### D6 — Policy guardrails
`policy.apply_policy(signals)` (policy.py:19-32): for each of the 4 `FORCED_CATEGORIES =
("migration", "lockfile", "ci", "auth")` (config.py:73), if either side touches it, add a rule
string `"{category}:{pr|merged|pr+merged}:{sorted comma-joined paths}"` to `rules_hit`; `config`
category (not forced) goes to `notes` instead (Q11). `policy.combine(decision, policy,
confidence_floor=None)` (policy.py:35-54): `escalated_by` accumulates `"policy"` (if
`force_escalate`), `"orchestrator"` (if the LLM said escalate), or `"confidence_floor"` (if
`auto_rebase` but `confidence < floor`, default `0.7`, env `REBASE_CONFIDENCE_FLOOR`, `0`
disables). **The orchestrator still runs even when policy will force escalation** — `_decide()`
(pipeline.py:63-87) calls `orchestrator.decide()` unconditionally (unless `--force-resolve`), then
`combine()` merges both — so its opinion is recorded in the comment and costs ~$0.008/PR even on a
policy-blocked PR (D20). Exhaustively property-tested: `tests/unit/test_policy.py:33-60` proves
`force_escalate=True` overrides every `(action, confidence, floor)` combination.

### D7 — Resolver
`resolver.resolve()` (resolver/agent.py:111-192). `prepare_workdir()` (agent.py:45-66) does a
`git clone --no-checkout` into `tempfile.mkdtemp()`, checks out the PR head on branch
`rebase-work`, **removes the `origin` remote** (agent.py, the `remote remove origin` step in the
command list at line 57), and sets `merge.conflictStyle=diff3`. `resolve()` first tries `git
rebase <onto>` directly; **if it's clean, the agent is never invoked** — `status="clean"`, 0
turns, $0 (agent.py:124-132). On conflict, launches `claude_agent_sdk.query()` with
`ClaudeAgentOptions` (agent.py:84-108):
- `tools=["Skill"]` — the *only* built-in tool; no Bash/Read/Write/Edit.
- `allowed_tools` = the 7 custom in-process tools (below) + 2 MCP tools.
- `plugins=[{"type":"local","path":.../resolver/plugin}]`, `skills=["rebase:rebase-playbook"]`.
- `setting_sources=[]` — ignores this machine's own Claude settings.
- `max_turns=20`, `max_budget_usd=1.00` (from `config.resolver_caps()`, env-overridable).
- `env={"ANTHROPIC_API_KEY": config.api_key()}` — **only** the Anthropic key, nothing else (§7).

Caps are enforced by the SDK (`error_max_turns`/`error_max_budget_usd` result subtypes) **and**
independently counted from the message stream by `Budget` (resolver/budget.py:15-41), which maps
either signal to an escalation reason string like `"max_turns 20 reached"`.

### D8 — Verifier
`verifier.verify()` (verifier.py:17-45): (1) `run_pytest(workdir)` (resolver/tools.py:29-42,
300s timeout, reused from the resolver's own test tool); (2) BAML `CheckIntent(pr,
resolved_diff) -> IntentCheck` (verifier.baml:8) where `resolved_diff = git diff
<new-main>..HEAD`. `verdict = "pass"` **iff** `tests_passed and check.intent_preserved`
(verifier.py:44) — either one failing is `"escalate"`.

### D9/D22 — Stale-approval check
`stale.stale_check()` (stale.py:100-127): `git range-diff --creation-factor=100
<old_base>..<old_head> <new_base>..<new_head>` (D22 raised the default 60→100 after a live bug:
small commits went unpaired and showed as "dropped + added" instead of naming the changed line —
`tests/unit/test_stale.py:104-111`). `parse_changes()` (stale.py:44-77) turns the range-diff
output into `PatchChange` records (`old`/`new`/`dropped`/`added`). `unchanged = not changes`.
**D22 (Q4 option 2):** even if changed, `within_conflicts()` (stale.py:85-97) allows the push if
every changed patch **line's file** was a file that conflicted, and every **removed ("old")**
line's text appears verbatim inside a conflict hunk the resolver actually saw (diff3-style, so
the hunks include the base side). ⚠️ Implementation nuance I want to flag for follow-ups: the
function only re-checks *removed* lines against hunk text (stale.py:92-96) — an *added* ("new")
line only needs its file to be a conflicted file, not to appear in the hunk text itself. All the
checked-in tests use verbatim keep-both content, so I did not find a test that would catch a
resolver rewriting a line to something novel while staying "within" a conflicted file — see §8.

### D10 — Push and report
`github_api.push()` (github_api.py:153-177): `git push --porcelain
--force-with-lease=refs/heads/<branch>:<expected_sha> <url> HEAD:refs/heads/<branch>`. Token goes
on the command line only (the clone keeps no remote), and is scrubbed from any error text
(`_scrub`, github_api.py:40-41). A lease rejection (`"stale info"` or `"[rejected]"` in the git
output) raises `PushRejected`, everything else raises `GitHubError`
(github_api.py:172-177). `report.render()` (report.py:28-120) always emits headline, stage, cost,
time; then conditionally Decision/Policy/Signals/Resolver/Verifier/Stale sections; always a
per-stage + total cost table.

### D11 — MCP server
`mcp_server/server.py` (stdio, `mcp` 2.2.0's `MCPServer`), exactly two tools:
- `conflict_preview(repo_path, onto, head) -> {conflicted_files, hunks}` — wraps
  `signals/conflicts.conflict_hunks()` (server.py:48-53).
- `symbol_overlap(repo_path, base, a, b) -> list[str]` — wraps `signals/symbols.modified_symbols()`
  intersected on both sides (server.py:55-62).

Both validate `repo_path` resolves inside the root passed at process start
(`_repo()`, server.py:28-32, raises `PathOutsideRoot`) and that ref arguments don't start with
`-` (`_ref()`, server.py:35-38 — blocks a ref like `--output=/tmp/x` being parsed as a git flag;
exercised in `tests/unit/test_mcp_server.py:60-73`).

### D12 — Skill
`resolver/plugin/skills/rebase-playbook/SKILL.md` (39 lines): preview conflicts first via MCP →
`list_conflicts` → per file: `read_file` → edit only between `<<<<<<<`/`>>>>>>>` (diff3, so
`|||||||` shows the common ancestor) → `write_file` → `run_tests` → `git_add` → `rebase_continue`
→ finish with one sentence on what was kept. Rules: never touch code outside conflict hunks,
never "improve"/refactor, never weaken a test, cannot push, and "if the two sides pursue
incompatible goals... call `escalate` ... Escalating is a correct outcome; a wrong resolution is
not" (SKILL.md:35-38).

### D13 — Trigger
`src/sandbox_gen/template/.github/workflows/rebase.yml`, installed into the **sandbox repo**, not
this one — see §2. `permissions: contents: read` only (rebase.yml:13-14); the resolver's own push
uses `SANDBOX_REPO_TOKEN`, never the workflow's `GITHUB_TOKEN` (D2 — the default token's pushes
don't retrigger CI).

### D14 — Eval harness
**Not built.** No `eval/` directory exists in the repo, and `docs/PLAN.md`'s own status line
confirms it: "Next: open the Phase 4 PR against `main`; then Phases 5–6." I looked for `eval/`,
`runs/`, and `demo/` directories and found none (all are gitignored/not-yet-created — see §9,
§10). Don't claim a model-sweep table exists; it doesn't yet.

### D19 — LLM transport
`llm.py`: `_client(model)` (llm.py:28-40) builds a `ClientRegistry` with one runtime client named
`"Runtime"` (model, api key, `max_tokens=16000`). `call()` (llm.py:73-99): builds the request with
BAML (`client.request.Fn(**args)`), POSTs it with `httpx` (`_post`, retries 3× with exponential
backoff on `{408,409,429,500,502,503,504,529}`, llm.py:19,44-56), **records the ledger row before
parsing** (llm.py:92-93, one line before the parse at line 99) — so a reply that fails to parse is
still paid for — then raises `LLMError` if `stop_reason` isn't `end_turn`/`stop_sequence`
(llm.py:95-97), else parses with `client.parse.Fn(text)`.

### D20 — Phase 2 additions
`PolicyResult.notes` (models.py:42), `FinalDecision.escalated_by`/`.confidence_floor`
(models.py:49-51) — both confirmed live in `policy.combine()` above.

### D21 — Phase 3 choices
Skill plugin dir: `PLUGIN_DIR = .../resolver/plugin` (agent.py:33), skill id
`"rebase:rebase-playbook"` (agent.py:34). Tool scoping enforced **in code**, not just the skill
(resolver/tools.py):
- `Workdir.path()` (tools.py:54-60): resolves the path, rejects anything not
  `is_relative_to(root)`, and rejects any path with `.git` in its parts.
- `write_file()` (tools.py:100-107): refuses unless the relative path is in
  `Workdir.conflicted()` (freshly computed from `git diff --diff-filter=U`, tools.py:71-73) —
  **not** a fixed list, so it tracks state correctly across a multi-file resolution.
- `git_add()` (tools.py:120-131): refuses if the file isn't conflicted, and refuses if any of
  `<<<<<<<`/`|||||||`/`>>>>>>>` markers remain.
- `rebase_continue()` (tools.py:133-143): refuses while `conflicted()` is non-empty.

Resolver outcomes: `escalate(reason)` tool records `wd.escalation` (tools.py:145-147);
`"resolved"` is decided from **repo state** — `wd.rebase_in_progress()` / `wd.conflicted()`
after the run, not the model's own claim (agent.py:181-183); a cap hit becomes `"escalated"` with
the cap named (agent.py:173-175, budget.py:33-40); anything else unexpected becomes `"error"`
(agent.py:178-180). Resolver prompt: a short custom `SYSTEM_PROMPT`
(agent.py:38-42), not Claude Code's default.

### D23 — Sandbox layout & eligibility
`sandbox_gen.scenarios.WAVES` (scenarios/__init__.py:38-54): wave 1 = 9 "code" scenarios, wave 2 =
2 "risky" scenarios (`migration_collision`, `lockfile_touch`) — risky changes get their own wave
because policy escalates **every** PR once the merged change touches migrations/lockfiles.
`generator.trigger()` (generator.py:218-243) fast-forwards `main` by exactly one wave and refuses
if remote `main` isn't at wave N-1. Eligibility = `github_api.eligibility()` (above); `REBASE_REF`
env var in `rebase.yml:18` lets the workflow check out an unmerged phase branch of this repo.

---

## 4. Scenario walkthroughs

No `runs/`, `eval/`, or `docs/demo/` directory is committed to this repo — I found no recorded
eval or run output to quote. The closest thing to real evidence is `docs/PLAN.md`'s own Phase-4
handoff table (from **live GitHub Actions runs**, not checked-in transcripts): "Verified across 3
replays of the original 5 scenarios (identical outcomes each time) and 1 replay of the expanded
set of 11 scenarios... Wave 1 of the expanded set cost about $0.22 in LLM spend across 10 PRs."
That table is reproduced in full detail below alongside the code path each scenario takes.
Deterministic parts (conflict/symbol/policy) are also unit-tested exactly (`test_scenario_signals.py`,
`test_waves.py`).

| # | Scenario | Wave | Deciding layer | Code path | Comment content (from `report.render`) |
|---|---|---|---|---|---|
| 1 | `trivial` | 1 | resolver's clean short-circuit | 0 conflicts → orchestrator not expected to escalate → `resolve()` returns `clean` with 0 turns (agent.py:124-132) → verifier pass → stale unchanged → push | headline "Rebased and pushed", Resolver section shows `status: clean` |
| 2 | `real_conflict` | 1 | resolver (agent loop) | conflict in `shop/inventory.py:restock` → agent resolves by keeping both guards, `run_tests`→PASSED→`git_add`→`rebase_continue` → verifier pass → stale unchanged (PR's own added lines survive unchanged) → push | Resolver section lists tool_calls incl. `mcp__rebase-tools__conflict_preview`, `Skill` |
| 3 | `semantic_break` | 1 | **verifier** (headline demo case) | 0 conflicts, 0 symbol overlap → clean rebase (resolver never invoked) → tests **fail** (`cart_total` calls `calc_price` with the old 2-arg signature) → `verdict="escalate"` → `stage="verifier"`. Normal path records the orchestrator's opinion as a note only, per Q3/D18; the pass/fail check is `--force-resolve` (pipeline.py:73-78), which skips the orchestrator but **not** the policy | "Escalated to a human: not rebased" at `verifier`, tests FAILED shown in a `<details>` block |
| 4 | `migration_collision` | 1 (own PR) / 2 (merged) | **policy** | both sides add `migrations/0003_*.sql` → `apply_policy` forces escalate → resolver never constructed (asserted via monkeypatch in `tests/scenarios/test_run_pr.py:131-141`) | stage `policy`, rule `migration:pr+merged:...` |
| 5 | `lockfile_touch` | 1 (own PR clean) / 2 (merged) | **policy** | at wave 1 the PR itself is clean (no lockfile touch on the PR side) so it would push; the *merged* lockfile bump lands in wave 2, at which point **every** eligible PR's `touches.lockfile.merged` is non-empty → policy forces escalate for everyone | stage `policy`, rule `lockfile:merged:uv.lock` |
| 6 | `conflicting_intent` | 1 | orchestrator, resolver, or verifier (never policy) | both sides rewrite the same oversell branch of `reserve()` with contradictory behavior; no forced category, so it's never blocked by policy — must be stopped by judgment: the orchestrator may escalate directly, or the resolver's skill rule ("incompatible goals → escalate") fires, or (worst case) the verifier's tests fail because no keep-both/ours/theirs resolution satisfies both | `also_stages=("resolver","verifier")` in the scenario's `Expected`; `final` is always `escalated`, never pushed |
| 7 | `behavior_change` | 1 | orchestrator or verifier | `apply_discount`'s *meaning* changes (percent→fraction) with **no signature change**, so signals show 0 conflicts and 0 symbol overlap — subtler than `semantic_break`, nothing for a human or a signal to spot; `promo_price` calls it with the old meaning (`10` instead of `0.10`) | test asserts `"pct must be between 0 and 1" in test_output_tail` when forced (`tests/scenarios/test_run_pr.py:106`) |
| 8 | `multi_file_conflict` | 1 | resolver | 2 conflicts (`shop/shipping.py`, `shop/tax.py`), resolver must work through both files, keep both sides in each | `files_touched == {"shop/shipping.py","shop/tax.py"}` asserted directly (`test_run_pr.py:122`) |
| 9 | `auth_touch` | 1 | **policy**, despite being provably safe | PR (not main) adds to `shop/auth/tokens.py` — purely additive, rebases cleanly, tests would pass if it got that far (`test_waves.py:110`: "would be safe: policy is the stop") — but the `auth` rule fires regardless | stage `policy`, rule `auth:pr:shop/auth/tokens.py,tests/test_auth_expiry.py` |
| 10 | `ci_touch` | 1 | **policy** | PR edits `.github/workflows/ci.yml` (adds a harmless `compileall` step) — still forced | stage `policy`, rule `ci:pr:.github/workflows/ci.yml` |
| 11 | `unapproved` | 1 | **eligibility** (before the matrix even exists) | no `rebase:approved` label and no APPROVED review → excluded in `cli.setup()`'s eligibility loop, never enters `prs.json` | **no matrix leg runs, no comment is posted at all** |

Wave-2 detail worth saying out loud: pushing wave 2 (`migration_collision` + `lockfile_touch`'s
merged changes together) makes **every remaining eligible open PR** escalate at `policy`, because
the merged side now touches both migrations and the lockfile — confirmed by
`tests/unit/test_waves.py:74-79` (`test_wave2_risky_changes_escalate_every_pr_by_policy`).

---

## 5. Numbers to know

**Caps & floors** (all in `config.py`, all env-overridable):
- Confidence floor: **0.7** default (`REBASE_CONFIDENCE_FLOOR`, `0` disables it) — config.py:74.
- Resolver caps: **20 turns**, **$1.00** (`REBASE_RESOLVER_MAX_TURNS`,
  `REBASE_RESOLVER_MAX_USD`) — config.py:89-93.
- Forced policy categories: `migration`, `lockfile`, `ci`, `auth` — config.py:73.
- `range-diff --creation-factor=100` — stale.py:117.
- Diff size refusal threshold for the analyst: 200,000 chars — analysts.py:8.
- Test timeout in the resolver/verifier: 300s — resolver/tools.py:17.

**Model defaults** (config.py:31-36, all overridable per-agent via `REBASE_MODEL_<AGENT>`):
analyst = `claude-haiku-4-5-20251001`; orchestrator/resolver/verifier = `claude-sonnet-5`.

**Prices** (config.py:57-70, USD / million tokens, source: platform.claude.com pricing, fetched
2026-09-24):

| Model | Input | Output | Cache read | Cache write (5m) | Cache write (1h) |
|---|---|---|---|---|---|
| Haiku 4.5 | 1.00 | 5.00 | 0.10 | 1.25 | 2.00 |
| Sonnet 5 | 2.00 | 10.00 | 0.20 | 2.50 | 4.00 |
| Opus 5.5 | 4.00 | 20.00 | 0.20 | 5.00 | 8.00 |

A model missing from this table is a hard error, never `$0` (llm.py:84-85, ledger.py:24-26).

**Cost — the one recorded live data point:** "Wave 1 of the expanded set cost about $0.22 in LLM
spend across 10 PRs (per-PR comments), plus the once-per-run merged summary" (PLAN.md status
line) — roughly **$0.02/PR** at this stage, dominated by policy-blocked PRs that only pay for one
`analyst_pr` (Haiku) + one `orchestrator` (Sonnet) call before escalating. A PR that reaches the
resolver costs more; the checked-in **unit-test fixture** (`tests/unit/fixtures/report_resolved.md`,
not a live number — built by hand in `tests/unit/test_report.py`) illustrates the *shape* of a
per-stage breakdown for a resolved PR: orchestrator $0.0060 + resolver $0.0375 = **$0.0435
total**, 11 resolver turns, 52s latency. Cost-at-scale extrapolation (not measured, see §7).

**Eval results:** none — Phase 5 not built (§3, D14).

**Test counts (verified today):**
- `uv run pytest tests/unit -q` → **332 passed** in 201s (0 failures, 0 skips).
- `@pytest.mark.llm` scenario tests (real LLM + real Agent SDK, `tests/scenarios/test_decide.py` +
  `tests/scenarios/test_run_pr.py`): **23** — matches `docs/PLAN.md`'s "23 LLM scenario tests...
  not run locally" exactly (I recounted by hand: 10 in `test_decide.py`, 13 in `test_run_pr.py`,
  including parametrized cases).

**Lines of code (re-measured today, `wc -l`):**
- `src/rebase_agent/` core (excl. `resolver/`, `signals/`, `mcp_server/`, `baml_client/`): **1585**
  across 15 files — biggest: `pipeline.py` 246, `cli.py` 206, `github_api.py` 177.
- `src/rebase_agent/resolver/`: **478** (`agent.py` 211, `tools.py` 200, `budget.py` 67).
- `src/rebase_agent/signals/`: **199**.
- `src/rebase_agent/mcp_server/`: **74**.
- `src/sandbox_gen/generator.py`: **319**; `src/sandbox_gen/scenarios/*.py`: **759** across 12
  files.
- `baml_src/*.baml`: **191** across 6 files.
- **Total non-test source: 3606 lines.**
- `tests/`: **1817** lines across 17 test files + 2 conftest files.

---

## 6. Code tour — 6–8 places to open live, in order

1. **`docs/PLAN.md` §0.5** — the pipeline diagram, to orient the interviewer in 10 seconds before
   touching code.
2. **`src/rebase_agent/pipeline.py:133`** (`run_pr`) — the whole state machine on one screen; walk
   the 7 short-circuits from §2's table.
3. **`baml_src/orchestrator.baml`** — the actual orchestrator prompt (§7 has the "how was it
   designed" answer); show that it explicitly disclaims repo access and explains the pipeline
   downstream of its own decision.
4. **`src/rebase_agent/policy.py`** — `apply_policy` + `combine`; show that this is plain Python,
   not an LLM call, and that it can only ever make the outcome *more* conservative.
5. **`src/rebase_agent/resolver/tools.py`** (`Workdir` class) — `write_file`/`git_add`/`path()`;
   this is the strongest "we didn't just trust the LLM" evidence in the whole repo.
6. **`src/rebase_agent/resolver/plugin/skills/rebase-playbook/SKILL.md`** — 39 lines, read it
   aloud; contrast the soft (prompt-level) rules here against the hard (code-level) ones in #5.
7. **`tests/scenarios/test_run_pr.py`** — real-LLM acceptance tests; show
   `test_semantic_break_force_resolve_caught_by_verifier` next to
   `test_semantic_break_normal_path_note` (lines 68-83) to explain the Q3 "note vs. pass/fail"
   distinction live.
8. **`src/sandbox_gen/template/.github/workflows/rebase.yml`** — the actual trigger, concurrency
   group, and the setup→matrix wiring.

---

## 7. Likely deep-dive questions with answers, grounded in code

**Why not GitHub's "Update branch" button, auto-merge, or a merge queue?**
None of those resolve a textual conflict, verify that a *clean* rebase didn't silently break
something (the `semantic_break`/`behavior_change` cases — same signature or no signature change at
all, tests fail after a perfectly clean rebase), or protect the PR's own reviewed diff content
from drifting during conflict resolution. A merge queue solves ordering and "CI before merge," not
"main moved and now this PR conflicts" or "the rebase changed what the reviewer actually
approved." This system adds four things none of those features have: an LLM read of *intent* that
gates the decision (D5); a hard-coded veto for high-risk paths that the LLM cannot override
(D6/policy.py:35-54); an actual tool-using agent that can resolve textual conflicts instead of
just failing (D7); and two independent after-the-fact checks — a rerun test suite + intent
check (D8) and a range-diff patch-integrity check (D9/D22) — that GitHub's native tooling has no
equivalent of at all.

**"Dismiss stale approvals" + force-push — doesn't that dismiss the approval anyway? How does
that interact with range-diff?**
Yes. The push is a genuine `git push --force-with-lease` from the bot's PAT
(github_api.py:153-177), and GitHub's "dismiss stale approvals on push" setting dismisses reviews
on **any** new commit to the PR branch, regardless of who pushed it or whether the content is
byte-identical. So if that branch-protection setting is on, our own rebase dismisses the human's
approval. **The system does not detect or react to this** — it doesn't re-request review or notify
the approver; that's a real gap (§8). This is precisely the problem D9/D22's range-diff check
exists to compensate for: it independently re-verifies "this is still what was approved" (or
"changed only inside conflicts the resolver saw," D22) at the *content* level, since GitHub's own
approval state can no longer vouch for that after any push. The catch: that compensation lives
entirely in the PR comment, not in GitHub's own UI — a reviewer glancing at the "Reviewers"
sidebar sees a dismissed/missing approval with no visible link to the bot's range-diff proof.
**UNVERIFIED:** whether the sandbox repo's branch protection actually has this setting enabled —
that's a GitHub UI setting, not something checked into the repo.

**Prompt injection — PR titles/descriptions/diffs are untrusted. What stops a PR from talking the
system into auto-rebasing? What stops the resolver from acting on instructions inside files?**
Two different attack surfaces:
- *Analyst/orchestrator prompts* (analysts.baml:21-28, orchestrator.baml:53-63) interpolate the
  title/body/diff as plain text with no sanitization. One deliberate mitigation: the analyst
  prompt says "if the title or description disagrees with the diff, trust the diff and say so in
  risk_notes" (analysts.baml:18-19) — so a malicious *title* can't talk the summarizer out of what
  the diff actually does (a malicious *diff*'s own comments/strings are a softer problem, not
  specifically defended against). The bigger structural defense: `Decision.action` is a typed
  2-value enum (models.py:34) and is **always** AND-ed with `apply_policy()` in plain code
  (policy.py:35-54) — a hostile PR can at best manipulate `reasons` strings or push the decision
  toward more/less confidence; it cannot skip policy, and even a maximally "convinced"
  `auto_rebase` still has to survive the resolver → verifier → stale-check gauntlet, none of which
  the orchestrator's output can bypass. The resolver also has **no push capability at all** — the
  clone's remote is removed (agent.py, `remote remove origin` step) — so nothing the orchestrator
  says can result in a direct push.
- *Resolver reading file contents* (`read_file` tool, tools.py:163-166 could surface injected text
  from a PR-authored file): mitigations are (a) **no shell/Bash tool exists** — `tools=["Skill"]`
  is the only built-in (agent.py:88) — so file text can't be executed as a command; (b)
  `write_file` only accepts files git currently reports conflicted (tools.py:100-107), so it can't
  be redirected to edit arbitrary files; (c) `git_add` refuses while conflict markers remain
  (tools.py:120-131); (d) the skill explicitly forbids deleting/weakening tests, inventing
  behavior, or touching anything outside conflict hunks (SKILL.md:30-34) — a soft, prompt-level
  defense; (e) even a fully "convinced" resolver is checked independently afterward: `verifier.py`
  reruns the real tests and a separate BAML intent check, and `stale.py`'s range-diff flags **any**
  change outside the conflicted hunks (D22) — so sabotage outside the hunks gets caught by the
  stale check, and sabotage that breaks behavior gets caught by the verifier. The one thing *not*
  independently re-verified: a resolution that stays inside the conflict markers, passes tests,
  and still reads as "intent preserved" to the LLM, but is subtly wrong. That's inherent to giving
  an LLM the conflict-resolution job at all, not a specific hole in this system.

**Can the resolver read secrets (API key, push token)? What exactly can its tools do?**
The resolver subprocess *is* given `env={"ANTHROPIC_API_KEY": config.api_key()}` (agent.py:107) —
it needs that to function — but none of its 7 tools can read its own process environment or any
path outside the workdir (`Workdir.path()` rejects anything not `is_relative_to(root)` and
anything touching `.git`, tools.py:54-60). There's no shell tool, so no `printenv`/`env`
equivalent either. **The push token (`SANDBOX_REPO_TOKEN`) is never given to the resolver at
all** — pushing happens later, in a different process (`pipeline.run_pr`/`cli`), using a URL
string the resolver never sees, and the clone's git remote is stripped before the agent even
starts (agent.py, `remote remove origin`). Full tool list and what each enforces:
`read_file`/`write_file` (path + conflicted-only, tools.py:94-107), `list_conflicts`
(tools.py:109-114), `run_tests` (tools.py:116-118, 300s timeout), `git_add` (conflicted +
no-markers-remain, tools.py:120-131), `rebase_continue` (refuses with unresolved files,
tools.py:133-143), `escalate` (records a reason string, tools.py:145-147) — plus the 2 read-only
MCP tools (`conflict_preview`, `symbol_overlap`, both root-scoped, mcp_server/server.py:28-38).

**Two pushes to `main` in quick succession — what happens? Concurrency group? force-with-lease?**
`rebase.yml`'s `concurrency: group: rebase-${{ github.ref }}, cancel-in-progress: false`
(rebase.yml:9-11): both pushes are to the same ref, so the second run **queues** behind the first
rather than canceling it — both eventually execute, back to back, never in parallel. Within a run,
`run-pr`'s `PushTarget.expected_sha` is captured once at the start from `gh.get_pr(pr)`
(cli.py:154-155); if a PR's branch moves before the local rebase even starts, `run_pr` catches
that explicitly and escalates with "PR head moved" before doing any work (pipeline.py:193-196). If
it moves later, the final `--force-with-lease=<branch>:<expected_sha>` still protects it — git
refuses the push, `PushRejected` becomes an "escalated at push" outcome with the git error in the
comment (github_api.py:172-177, pipeline.py:238-240). Net effect: **two overlapping runs can never
clobber each other's push** — the loser of the race escalates cleanly. Directly tested:
`tests/unit/test_github_api.py:143-150`.

**Flaky or slow tests; repos with no tests.**
`run_pytest()` (resolver/tools.py:29-42) has a hard 300s timeout; a timeout is reported as
`passed=False` with a clear message — so a hang becomes a verifier escalation, not a stuck
pipeline. There is **no flake retry anywhere** — a test that fails once escalates a PR that would
otherwise have been fine; nothing re-runs it. **Repos with no tests** are a real, unaddressed
weak spot: `pytest` with nothing collected exits **5**, which `run_pytest`'s `proc.returncode ==
0` check (tools.py:42) reads as `passed=False` — meaning **every PR in a test-less repo would fail
verification and escalate, forever**, even a byte-for-byte-safe rebase. I found no special-casing
for exit code 5 anywhere in `verifier.py` or `resolver/tools.py`.

**What happens on each failure path?**
- *Cap hit (resolver):* `Budget` (resolver/budget.py:28-41) or the SDK's own
  `error_max_turns`/`error_max_budget_usd` result subtype → `ResolverResult(status="escalated",
  reason="max_turns 20 reached" | "max_usd 1.00 reached (spent $X)")` → pipeline escalates at
  `stage="resolver"`.
- *BAML parse failure:* `llm.call()` records the ledger row **before** parsing (llm.py:92-93,
  before line 99) — so it's paid for either way — then the parse exception propagates uncaught up
  through `analysts.py`/`orchestrator.py`/`verifier.py` into `pipeline.run_pr`'s outer
  `except Exception` (pipeline.py:242-243) → `final="error"` with the exception's message, stage =
  wherever it happened.
- *API error:* `_post()` retries 3× with backoff on `{408,409,429,500,502,503,504,529}`
  (llm.py:19,44-56); exhausted retries or a non-retryable status raise `LLMError` — same
  outer-`except` path → `final="error"`.
- *Git error:* most git wrappers use `check=True` and raise `GitError` on nonzero exit
  (git_ops.py:11-17) — same outer-`except` path. Some calls intentionally use `check=False` and
  interpret specific codes themselves (e.g. `merge-tree` returncode 1 = "conflicts," not an
  error — conflicts.py:19-22).
- *Verifier failure (tests fail / intent not preserved):* **not** an error — `verdict="escalate"`
  is the intended, most important outcome (D8) — `final="escalated"`, `stage="verifier"`.

**Cost at scale (e.g. 20 open PRs, 10 merges/day).**
The one hard number in the repo is $0.22 across 10 PRs for one wave (§5) — roughly $0.02/PR when
most PRs are policy-blocked (cheap: one Haiku + one Sonnet call each) rather than resolver-bound
(expensive: Sonnet agent turns, capped at $1.00/PR). Extrapolating — **not measured, treat as an
order-of-magnitude estimate**: 20 open PRs at the observed ~$0.02–0.03/PR floor is order $0.50/push
event if nothing reaches the resolver; worst case, if every PR maxed its resolver budget, it's
bounded above by `20 × $1.00 = $20`/push event. At 10 merges/day that's a wide range, roughly
$5–$200/day depending on how often PRs actually conflict. The merged-change summary is paid once
per push regardless of PR count and is reported both once and split evenly across PRs "to show the
saving from reuse" (`ledger.rollup`, ledger.py:105-132, PLAN.md §0.6). I'd get Phase 5's eval sweep
built before quoting a real number to a team.

**How would you roll this out to a real team, and what would you measure?**
I'd say honestly that Phase 5 (eval) and Phase 6 (README/demo) aren't built yet, so today the
system has never been measured for accuracy, only demoed for behavior. Before a real repo: (1)
replace the `rebase:approved` label fallback with the proposed GitHub App token (Q2b option 1,
still open) so genuine approvals work normally instead of the self-approval workaround; (2) run
Phase 5's model sweep to get real cost/accuracy numbers before trusting Sonnet-everywhere as the
default; (3) fix the "no tests" and "no flake retry" gaps (§8) before touching any repo without a
solid, fast suite; (4) pilot on one low-stakes internal repo with the confidence floor left
conservative. What to watch, all already captured by the ledger (ledger.py rollups): escalation
rate (too high = no value; too low = suspicious), resolver success rate, **verifier catch rate**
(how often "clean rebase, tests fail" happens — the headline safety metric), and $/PR by stage.

**How was the orchestrator's prompt designed? Show it.**
Quoted in full: [orchestrator.baml](../baml_src/orchestrator.baml). Three deliberate design
choices worth narrating: (1) it states up front "You have NO access to the repository," so the
model doesn't hallucinate file contents it can't see; (2) it explains what happens *after* each
verdict ("a resolver agent rebases... a verifier reruns... any failure escalates") so the model's
cost/benefit judgment is calibrated to the real, layered pipeline rather than treating its own
call as the last word; (3) it explicitly says hard policy is enforced in code afterward and it
"cannot override them, so judge the rest on its merits" (orchestrator.baml:44-45), and gives a
concrete anti-pattern: "a textual conflict by itself is not a reason to escalate"
(orchestrator.baml:51) — since D3's signals already surface `conflict_count`, this stops the
model from being reflexively conflict-averse when a conflict is mechanically trivial for the
resolver.

**How do the tests avoid mocking the LLM, and what is mocked?**
`tests/scenarios/*` (`test_decide.py`, `test_run_pr.py`) call the real BAML client and the real
Claude Agent SDK end to end; without `REBASE_ANTHROPIC_API_KEY` they're `pytest.mark.skipif`'d
(test_run_pr.py:18-24) and reported as **SKIPPED**, never as passed (`ci.yml` runs `pytest -rs` to
surface skip reasons). What *is* mocked: only `tests/unit/test_pipeline.py`, which monkeypatches
`analysts.summarize_change` and `orchestrator.decide` with counting stubs — purely to assert call
counts and wiring (e.g. the merged summary is computed exactly once per run), with the file's own
docstring saying so explicitly: "Real-LLM behavior is in tests/scenarios/" (test_pipeline.py:1-2).
`tests/unit/test_policy.py` uses hand-built `Decision` objects for the same reason — it's testing
the pure `combine()` function, not model output.

---

## 8. Weak spots and edge cases — blunt

- **No-test repos escalate forever.** `pytest` exit code 5 ("no tests collected") reads as
  `tests_passed=False`; nothing special-cases it. A repo with no test suite would fail every PR's
  verifier step, permanently.
- **No flake retry.** One bad test run escalates a genuinely good rebase; nothing re-runs it.
- **Eval harness doesn't exist (Phase 5).** The Haiku/Sonnet/Sonnet/Sonnet model split is a
  reasonable-sounding default, not a measured one.
- **No README, no `docs/demo/`, no `make demo` (Phase 6).** The only runbook is PLAN.md's Handoff
  section (§10 below reproduces it).
- **Eligibility is checked once, at setup, before the whole matrix runs.** If a review gets
  dismissed between setup and a given PR's matrix leg executing — including by our *own* earlier
  force-push on a different PR in the same run, if branch protection dismisses stale approvals —
  that PR is not re-checked and still gets rebased/pushed. This is a different gap from the
  push-race guard, which only protects the branch SHA, not the approval state.
- **The `rebase:approved` label is explicitly a workaround**, not the intended trust model (Q2b) —
  it exists purely because the demo session's own PAT can't self-approve. The docs say this
  outright; worth saying outright too.
- **Symbol overlap is Python-only** (stdlib `ast`) — a polyglot repo degrades to file-level overlap
  only.
- **Symbol overlap is definitions-only, not call sites, by design (Q3)** — which is exactly why
  `semantic_break`/`behavior_change` need the verifier as the real backstop; the signal will never
  catch them on its own.
- **`within_conflicts()` asymmetry (stale.py:85-97):** only *removed* patch lines are re-checked
  against conflict-hunk text; *added* lines only need to be in a conflicted file. I did not find a
  test that exercises a resolver rewriting a line to novel text while staying "within" a
  conflicted file — flagging the code asymmetry as real; whether it's practically exploitable is
  **UNVERIFIED**.
- **No Windows CI.** `ci.yml` runs `ubuntu-latest` only, despite D24 explicitly listing Windows
  fixes found by running the suite locally on this machine — future Windows regressions won't be
  caught automatically.
- **The GitHub App token approach (Q2b option 1)** that would let real approvals coexist with the
  bot's own PR-opening was proposed, never implemented.
- **Confidence floor (0.7) and the 4 forced categories are product judgment calls, not
  data-backed** — `docs/DECISIONS.md` itself still lists the confidence floor as "Q6, still open"
  even though `config.py` ships a hard default.

---

## 9. Discrepancies vs. `DECISIONS.md` / `PLAN.md`

- **`PLAN.md` §0.3's proposed layout lists `signals/overlap.py`** as a separate module; it does
  not exist. File overlap and diff-line counts live inline in `signals/compute.py` +
  `git_ops.py` instead. Minor, but a real naming mismatch if you go looking for that file.
- **`PLAN.md` §0.3 also lists `eval/` and `demo/`** — neither exists yet. Not a contradiction
  (PLAN.md's own status line says Phases 5–6 are next), just don't expect to find them.
- **`DECISIONS.md` D9's text** ("Proceed only if the PR's own patch content is unchanged... Nothing
  fancier") **is superseded by D22** (changes confined to resolved conflicts are allowed). The code
  in `stale.py` implements D22, not D9's original "nothing fancier" framing — D9 itself isn't
  edited to say "superseded," you have to also read D22 (and the changelog) to know that. A doc-
  organization nit, not a code error.
- **Q2b (who authors sandbox PRs) is described as "open"/"resolved for now" in the docs**, with
  hedged language about the label being a fallback; the code treats the label as a first-class,
  permanent mechanism (`github_api.APPROVED_LABEL`, checked first in `eligibility()`) — the code
  reads more finished/final than the docs' own hedging suggests.
- Everything else cross-checked — prices, caps, floor, forced categories, model defaults, the
  resolver's tool list, every scenario's expected outcome and wave assignment, `escalated_by`
  semantics — matched the docs exactly. I did not find a functional discrepancy beyond the ones
  above.

---

## 10. Demo runbook

No `make demo` target exists yet (Phase 6 not built), so this is `docs/PLAN.md`'s own "How to run
the live test" section, reproduced with brief annotations. **These are documented commands from
PLAN.md, not independently re-run by me** (running them calls the real LLM and pushes to GitHub,
both out of scope for this write-up).

**Reset + trigger:**
```bash
export SANDBOX_REPO=zhannahoe34/RebaseSandbox SANDBOX_REPO_TOKEN="$(gh auth token)"
R=https://github.com/zhannahoe34/rebasesandbox
uv run rebase-sandbox generate --push --label-approved --remote $R   # reset: main=base, pr/<s> force-pushed, PRs retargeted/opened, approval label set
uv run rebase-sandbox trigger --wave 1 --remote $R                   # "merge" wave 1 -> fires the workflow
uv run rebase-sandbox trigger --wave 2 --remote $R                   # after wave 1's run has finished
```
- `generate --push` force-resets `main` and every `pr/<name>` branch to the shared base commit,
  then opens/retargets one PR per scenario, and (with `--label-approved`) adds `rebase:approved` to
  approved scenarios and **removes** it from `unapproved` (generator.py:301-313) — so a stale label
  from a previous run can't leak through.
- `trigger --wave N` refuses unless remote `main` is exactly at wave N-1 (generator.py:232-238) —
  re-run `generate --push` to replay from scratch.
- **Watch it:** `gh run list -R $SANDBOX_REPO -w rebase`, `gh run view <id> --log-failed`.

**Show results:** open the sandbox repo's PRs on GitHub and read the bot's comments — each is
rendered by `report.render()` in exactly the structure shown in
`tests/unit/fixtures/report_resolved.md` (§6 fixture): headline → Decision → Policy → Signals →
Resolver → Verifier → Stale-approval check (with a collapsible `git range-diff`) → per-stage +
total cost table.

**Local, no network / no API key needed:**
```bash
uv run pytest tests/unit -q     # 332 passed, ~201s, as of today
```
proves the deterministic/policy/tool-scoping logic without spending anything. To narrate a
"resolved PR" comment without a live call, open `tests/unit/fixtures/report_resolved.md` directly
and walk through it section by section.

**Sanity checks before the interview** (from PLAN.md §5; only the pytest line was actually re-run
by me today — the others are documented, not independently verified this session):
```bash
uv sync && make generate
make baml-smoke     # needs REBASE_ANTHROPIC_API_KEY; not run here (out of scope)
make lint
uv run pytest tests/unit -q   # re-run today: 332 passed
```

**If the live run misbehaves:** be aware going in that **there is no recorded fallback** —
`docs/demo/` doesn't exist (Phase 6 not started), and I found no asciinema cast, saved log, or
screenshot set anywhere in the repo. If the live GitHub Actions run fails or the API key is
unavailable during the interview, the honest fallback is: (1) narrate the code using the §6 tour,
and (2) walk through `tests/unit/fixtures/report_resolved.md` as "this is exactly what a resolved
PR's comment looks like, and it's asserted byte-for-byte by a snapshot test." Say plainly that a
saved recording doesn't exist yet if asked — that matches the "honesty over completeness" rule the
project's own docs set for itself (D17).
