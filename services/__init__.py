"""BettyOS services — reusable revision logic shared by the UI and the CLI.

Nothing in this package imports Streamlit. Each module does one job:

- `revision_types`     the vocabulary: capability levels, revision types, fields
- `revision_context`   what is true right now: current copy, render config, assets
- `revision_classifier` which capability level a recommendation belongs to
- `ai_revision_service` proposed rewrites, as structured options
- `revision_validation` brand safety and quality checks on those options
- `revision_store`     persisted revision requests, per campaign
- `revision_apply`     turning an approved option into a new render version
- `copy_documents`     reading and rewriting one field of a copy document
"""
