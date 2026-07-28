# Architecture

How BettyOS fits together **today**. Future capabilities belong in [PRODUCT_VISION.md](PRODUCT_VISION.md) and [ROADMAP.md](ROADMAP.md)—not here.

## Current flow

```text
Streamlit UI (app.py)  or  CLI (main.py)
 ↓
UI wrappers (ui/) / shared helpers (src/)
 ↓
Brand Brain / Production Brain / Review Brain
 ↓
Outputs (outputs/)
```

## What exists

- **Studio UI** — [`app.py`](../app.py) + [`ui/`](../ui/). Primary local interface; review → revision → template workflows live here.
- **CLI** — [`main.py`](../main.py). Typer commands remain as a fallback.
- **Shared helpers** — [`src/`](../src/). Paths, persistence, Brand/Production loaders, package parsing, template registry/classifier/assignments.
- **Templates** — [`templates/template_registry.json`](../templates/template_registry.json). Canonical reusable formats with readiness status.
- **Renderers** — [`renderers/`](../renderers/). Shared Video / Static / Carousel / Copy families (not one engine per piece title).
- **Brand Brain** — [`brands/<brand_id>/`](../brands/). Oh Betty Jaletti is the first pack.
- **Production Brain** — [`production/`](../production/). Visual defaults + legacy piece templates used by video renderers.
- **Review Brain** — [`review/`](../review/). Critique scoring, structured recommendations, revision queue, coverage, versioning.
- **Library** — [`library/`](../library/). Indexed asset records and thumbnails.
- **Outputs** — [`outputs/`](../outputs/). Packages, campaigns, approvals, revision requests, assignments, versioned renders.

## Boundaries

Architecture reflects only the current system. We do not document frameworks, plugins, interfaces, registries, or module boundaries until there is a real implementation that requires them.
