# Architecture Decisions

Decided architecture for the agentic rebase system, condensed from the kickoff brief. **Do not redesign without updating this file.** Future sessions: read this file and `docs/PLAN.md` before touching the repo.

Items marked **Decided** come from the brief. Items marked **Proposed** are how PLAN.md reads something the brief left open. They are pending review and are also listed as open questions in PLAN.md.

---

## Goal

When `main` moves, automatically rebase approved PRs. Low-risk rebases run automatically. Risky ones go to a human. The goal is a shorter time from approval to merge, and fewer interruptions for developers.

This is an interview demo (deadline **Mon Sept 28, 4 PM**). It must visibly show:
- multi-agent orchestration
- an MCP server and client
- API data access (GitHub)
- an agent skill

## D1 — Stack (Decided)
- Python 3.12, `uv` for dependencies, `pytest`, `ruff`.
- **BAML** for every single-shot structured LLM call: the analysts, the orchestrator and the verifier's intent check. Use an exact pinned version, and follow that version's docs for `baml-py` / `baml_client` generation. Phase 1 includes a toolchain smoke test. If the smoke test fails, stop and report.
- **Claude Agent SDK (Python)** for the resolver only, because it is the one real tool-using agent loop.
- The model for each agent is configurable (Haiku / Sonnet / Opus). Never hardcode a model.

## D2 — Repos and credentials (Decided)
- `Rebase` (this repo) holds the system.
- `RebaseSandbox` is a separate GitHub repo. Our sandbox generator fills it with seeded scenarios. Never test against a real work repo.
- `ANTHROPIC_API_KEY` is the LLM key.
- `SANDBOX_REPO_TOKEN` is a PAT or GitHub App token with contents and pull-request write on the sandbox repo.
- Never use the default `GITHUB_TOKEN` for pushes, because its pushes don't retrigger CI.

## D3 — Deterministic signals (Decided)
Plain code, no LLM. The signals are:
- dry-run merge conflict count
- file overlap and symbol overlap between the merged change and the PR
- diff size
- whether either side touches lockfiles, migrations, CI files or config files

## D4 — Analyst agents (Decided)
Two BAML functions:
- One summarizes the intent of the newly merged change. It runs **once per run** and the result is reused for every open PR.
- The other summarizes the intent of each open PR.

## D5 — Orchestrator (Decided)
A BAML function. Its only inputs are the signals and the two summaries. It has no repo access. It outputs:

`Decision {action: auto_rebase | escalate, confidence: float, reasons: list[str]}`

## D6 — Policy guardrails (Decided)
Hard rules in plain code, outside the LLM, that force escalation: migrations, auth paths, lockfiles and CI config.

The final action is `escalate` if **either** the policy or the orchestrator says escalate. The LLM can escalate more often than the policy, never less. This is enforced in code and covered by tests.

## D7 — Resolver (Decided)
An Agent SDK loop:
- Runs only when the final action is `auto_rebase`.
- Works in a throwaway clone in a temp dir. Its tools are scoped to that dir, and it has no way to push.
- Loads the `rebase-playbook` skill.
- Connects as an MCP client to our MCP server.
- Has hard caps on turns and on spend (spend is tracked from reported usage). Hitting either cap returns `escalated` with a reason. It never fails silently.

## D8 — Verifier (Decided)
1. Reruns the test suite on the resolved branch.
2. Runs a BAML intent check that compares the resolved diff with the original PR intent summary.

Its most important job is catching rebases that apply cleanly but are semantically broken.

## D9 — Stale-approval check (Decided)
Run `git range-diff` between the PR before and after the rebase. Proceed only if the PR's own patch content is unchanged. Otherwise escalate. Nothing fancier.

**Proposed reading of "unchanged":** each commit has the same added and removed lines. Context lines and hunk headers are ignored. Without this, any conflict resolution would count as a change (see PLAN.md Q4).

## D10 — Push and report (Decided)
- Push with `git push --force-with-lease`, using the PAT or App token.
- Post a PR comment on **every** outcome, escalations included. It states the decision, the reasons, the signals and the cost.

## D11 — MCP server (Decided)
One small custom stdio server that exposes `conflict_preview` and `symbol_overlap`. We build it on purpose. Do not use the off-the-shelf GitHub MCP server.

## D12 — Skill (Decided)
One short `skills/rebase-playbook/SKILL.md`, used by the resolver.

## D13 — Trigger (Decided)
GitHub Actions on push to `main`:
- A setup job lists open PRs and computes the merged-change summary once.
- A matrix job runs once per open PR.

There is no standalone server.

**Proposed:** the workflow lives in the sandbox repo (that's where `main` moves) and checks out this repo to run the CLI.

## D14 — Eval harness (Decided)
Runs every scenario against a small model sweep: Haiku, Sonnet and Opus for the orchestrator, and possibly fewer models for the resolver. It writes a markdown table with these columns:
- decision correctness
- resolution success
- verifier catches
- cost
- latency

## D15 — Seeded scenarios (Decided)
Each scenario is a base commit, a change merged to main, and an open PR. Its expected outcome is also its acceptance test.

| # | Scenario | Setup | Expected |
|---|----------|-------|----------|
| 1 | `trivial` | Files don't overlap | `auto_rebase` → resolves → verifies → pushes |
| 2 | `real_conflict` | Textual conflict in the same function, resolvable | `auto_rebase` → resolver fixes it → tests pass |
| 3 | `semantic_break` | Main changes a function signature; the PR adds a call using the old signature. Applies cleanly, tests fail | The verifier catches it and escalates (**headline demo case**) |
| 4 | `migration_collision` | Both sides add a migration with the same number | The policy forces escalation; the resolver is never called |
| 5 | `lockfile_touch` | Main updates a lockfile | The policy escalates |

The generator is idempotent: rerunning it resets the sandbox to a known state.

## D16 — Build order (Decided)
Local first, GitHub Actions last:
1. Sandbox generator and signal CLI
2. Analysts, orchestrator and policy
3. MCP server, skill, resolver, verifier and stale check
4. Actions wiring
5. Eval harness
6. README, diagram, recorded demo and `make demo`

The whole pipeline must work as a CLI against a local clone before Phase 4.

## D17 — Working rules (Decided)
- One PR per phase. Each PR says what works, what doesn't, and the exact commands to verify it.
- Honesty over completeness. Never weaken, skip or fake a test, and never mock the LLM in scenario acceptance tests. If something isn't working, say so plainly.
- Phases 1, 4 and 6 run end to end. Phases 2 and 3 are review gates: stop and wait for review.
- Token discipline: read `docs/PLAN.md` and `docs/DECISIONS.md` first, and keep both updated.
- Cut scope, not quality: one MCP server, one skill, a small sweep, and range-diff only for stale approvals.

---

## Changelog
- 2026-09-24: Initial version from the kickoff brief.
