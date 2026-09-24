// Toolchain smoke test only: proves generation, import and (with a key) a live call.

class SmokeResult {
  ok bool
  echo string
}

function Smoke(text: string) -> SmokeResult {
  client Haiku
  prompt #"
    Return ok=true and echo the input text exactly.

    Input: {{ text }}

    {{ ctx.output_format }}
  "#
}

test SmokeEcho {
  functions [Smoke]
  args { text "hello" }
}
