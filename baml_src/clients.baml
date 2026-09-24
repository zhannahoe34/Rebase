// One client per model. Agents pick a model at runtime via ClientRegistry
// (see src/rebase_agent/config.py); these names are the static defaults.

client<llm> Haiku {
  provider anthropic
  options {
    model "claude-haiku-4-5-20251001"
    api_key env.ANTHROPIC_API_KEY
  }
}

client<llm> Sonnet {
  provider anthropic
  options {
    model "claude-sonnet-5"
    api_key env.ANTHROPIC_API_KEY
  }
}

client<llm> Opus {
  provider anthropic
  options {
    model "claude-opus-5-5"
    api_key env.ANTHROPIC_API_KEY
  }
}
