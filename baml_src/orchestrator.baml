// Orchestrator: decide whether a PR can be auto-rebased onto the newly merged change.
// Inputs are only the deterministic signals and the two summaries (D5): no repo access.

class TouchInfo {
  merged string[]
  pr string[]
}

class Signals {
  conflict_count int
  conflicted_files string[]
  file_overlap string[]
  symbol_overlap string[]
  diff_lines_merged int
  diff_lines_pr int
  touches map<string, TouchInfo>
}

class Decision {
  action "auto_rebase" | "escalate"
  confidence float @description("0..1: your probability that the automated path ends in a correct, intent-preserving rebase with no human needed.")
  reasons string[] @description("Short, specific reasons that cite the signals or summaries. At least one.")
}

function DecideRebase(signals: Signals, merged: PRSummary, pr: PRSummary) -> Decision {
  client Sonnet
  prompt #"
    {{ _.role("system") }}
    You decide whether an approved pull request should be rebased automatically onto a
    change that was just merged to main, or escalated to a human.

    You have NO access to the repository. You only see deterministic signals computed by
    code and two intent summaries written by analysts. Base every reason on that evidence
    and do not invent facts about the code.

    What happens after your decision:
    - auto_rebase: a resolver agent rebases the PR in a throwaway clone and resolves any
      textual conflicts hunk by hunk, keeping both sides' intent. Then a verifier reruns
      the test suite and checks that the PR's intent is preserved. Only if all of that
      passes is the branch pushed. Any failure along the way escalates.
    - escalate: nothing is rebased or pushed; a human is asked to handle the PR.

    Hard policy rules (migrations, lockfiles, CI config, auth code) are enforced in code
    after you answer; you cannot override them, so judge the rest on its merits.

    Choose escalate when an automated resolution is likely to be wrong or to need judgment
    a human should make, for example: the two changes pursue conflicting goals, one side
    changes an interface or behavior the other side relies on in a way tests may not
    catch, or the overlap is too large to resolve with confidence. Choose auto_rebase when
    the changes are independent, or when conflicts are local and both intents can clearly
    be kept. A textual conflict by itself is not a reason to escalate.

    {{ _.role("user") }}
    Signals:
    {{ signals }}

    Merged change (already on main):
    {{ merged }}

    Pull request to rebase:
    {{ pr }}

    {{ ctx.output_format }}
  "#
}
