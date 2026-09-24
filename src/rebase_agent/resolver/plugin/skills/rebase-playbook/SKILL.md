---
name: rebase-playbook
description: How to resolve a paused git rebase safely. Load this before touching any file.
---

# Rebase playbook

You are finishing a `git rebase` that stopped on conflicts. The PR's commits are being
replayed onto a newer main. Your job is to resolve the conflicts so that **both** sides'
intent survives, or to escalate.

## Steps
1. Call `conflict_preview` (MCP server `rebase-tools`) with the workdir, `onto` and
   `head` given in the task to see every conflict hunk up front.
   `symbol_overlap` tells you which functions both sides changed.
2. Call `list_conflicts` to see the files git is currently stopped on.
3. For each conflicted file:
   - `read_file` it.
   - Edit **only** the conflict hunks (between `<<<<<<<` and `>>>>>>>`). Keep the
     changes from both sides unless they are truly incompatible. Remove all markers.
   - `write_file` the whole file back.
   - `run_tests`. If tests fail because of your resolution, fix the resolution.
   - `git_add` the file.
4. When no conflicts remain, call `rebase_continue`. If it stops on a new conflict,
   go back to step 2.
5. Finish with one short sentence saying what you kept from each side.

## Rules
- Never change code outside conflict hunks. Never "improve" or refactor anything.
- Never delete or weaken a test to make it pass.
- Never invent behavior neither side had.
- You cannot push, and must not try to.
- If the two sides pursue incompatible goals, if you are unsure what either side
  intended, or if tests still fail after a reasonable fix, call
  `escalate` with a specific reason and stop. Escalating is a correct outcome;
  a wrong resolution is not.
