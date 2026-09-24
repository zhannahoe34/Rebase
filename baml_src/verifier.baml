// Verifier intent check (D8): does the rebased PR still do what the PR set out to do?

class IntentCheck {
  intent_preserved bool
  reasons string[] @description("Specific reasons citing the diff. At least one.")
}

function CheckIntent(pr: PRSummary, resolved_diff: string) -> IntentCheck {
  client Sonnet
  prompt #"
    {{ _.role("system") }}
    You check a pull request after it was rebased onto a newer main. You get the PR's
    intent summary (written before the rebase) and the PR's diff as it now stands on
    top of main. Decide whether the rebased diff still implements that intent: every
    behavior change the PR promised is present, nothing the PR did was dropped or
    altered, and nothing unrelated was added. A diff that no longer matches the
    intent, or that changes code the PR never touched, is not preserved.
    Judge only from what you are given.

    {{ _.role("user") }}
    PR intent summary:
    {{ pr }}

    Rebased PR diff (new main..rebased head):
    {{ resolved_diff }}

    {{ ctx.output_format }}
  "#
}
