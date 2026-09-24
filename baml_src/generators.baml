generator target {
    output_type "python/pydantic"
    // Relative to baml_src/; produces src/rebase_agent/baml_client/
    output_dir "../src/rebase_agent"
    // Must match the pinned baml-py version in pyproject.toml
    version "0.226.2"
    default_client_mode sync
}
