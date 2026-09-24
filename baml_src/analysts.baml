// Analyst: summarize the intent of one change (the merged change, or an open PR).
// Mirrors rebase_agent.models.PRSummary field for field.

class PRSummary {
  intent string @description("One or two sentences: what the change is for, in behavioral terms.")
  touched_areas string[] @description("Modules, functions, files or subsystems the change touches.")
  behavior_changes string[] @description("Observable behavior or interface changes: signatures, return values, defaults, schemas, dependencies. Empty if none.")
  risk_notes string[] @description("Anything that could break other in-flight work built on the old code. Empty if none.")
}

function SummarizeChange(title: string, body: string, diff: string) -> PRSummary {
  client Haiku
  prompt #"
    {{ _.role("system") }}
    You are a code-review analyst. Summarize the intent of one code change so that a
    separate reviewer, who will NOT see the diff, can reason about how it interacts with
    other changes. Be concrete: name functions, parameters and files. Describe what the
    code actually does; if the title or description disagrees with the diff, trust the diff
    and say so in risk_notes.

    {{ _.role("user") }}
    Title: {{ title }}

    Description:
    {{ body }}

    Diff:
    {{ diff }}

    {{ ctx.output_format }}
  "#
}

test SummarizeSmall {
  functions [SummarizeChange]
  args {
    title "Rename helper"
    body "Renames foo to bar."
    diff "-def foo():\n+def bar():"
  }
}
