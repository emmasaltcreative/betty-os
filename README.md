# BettyOS

**Version:** v1.0.0-beta

BettyOS is a local-first **Creative Operations System** for planning, producing, reviewing, and approving brand content. Brand knowledge lives on disk under `brands/`. **Oh Betty Jaletti** is the first brand pack shipped with BettyOS.

The recommended MVP experience is the local Streamlit studio UI. The CLI remains fully available for scripting and power users.

## Installation

Requirements: Python 3.11+, ffmpeg (for video ingest and rendering).

```bash
cd betty-os
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a local `.env` file with your Anthropic API key:

```bash
ANTHROPIC_API_KEY=your_key_here
```

Install ffmpeg on macOS:

```bash
brew install ffmpeg
```

## Quick start (recommended)

Launch the local studio:

```bash
streamlit run app.py
```

From the UI you can:

1. Open a campaign and generate or reuse a content package
2. Assign templates and create versioned renders on **Create**
3. Finish static and video renders non-destructively in **Studio** (logos, Color Recipes, light/color/texture, crop, real `.cube` LUTs)
4. Run Creative Review against finished work, manage **Revisions**, then **Approvals** and **Export**
5. Manage brand logos and LUTs under **Library**

Decisions, Studio drafts, finished versions, template assignments, approvals and revision requests save to disk and survive Streamlit reruns and full app restarts.

## CLI (still available)

```bash
python3 main.py
python3 main.py ingest ./assets/reading-hour-shoot
python3 main.py repurpose
python3 main.py create all
python3 main.py review
python3 main.py approve
```

## Typical workflow

In the Streamlit studio (recommended):

1. **Dashboard** — see package, campaign, readiness, approvals, and revision queue at a glance.
2. **New Campaign** — fill a guided brief; BettyOS plans the session.
3. **Content Package** — generate and read the campaign package.
4. **Renders** — render supported pieces, inspect Template Coverage, preview videos, compare versions.
5. **Creative Review** — run the critique pass, then Approve / Edit / Dismiss recommendations.
6. **Revision Queue** — execute safe renderer revisions into versioned outputs (never overwrites the original).
7. **Approvals** — mark assets approved or needs revision (saved on disk).

CLI users can still run the same planning/render/review steps with `python3 main.py …` as a fallback. Revision queue management is Studio-first.

Brand Brain (`brands/oh_betty_jaletti/`) guides plan, repurpose, and review. Production Brain (`production/`) guides rendering. Approval never alters media files.

## Available commands

| Command | What it does |
|---------|----------------|
| `python3 main.py` | Plan a production session (default) |
| `python3 main.py ingest <folder>` | Index photos/videos into the asset library |
| `python3 main.py ingest <folder> --force` | Re-analyze already indexed assets |
| `python3 main.py repurpose` | Generate a content package from the library |
| `python3 main.py create page-turn-loop` | Render the Page Turn Loop draft |
| `python3 main.py create ritual-reel` | Render the Ritual Reel draft |
| `python3 main.py create all` | Queue and render every supported piece into one campaign folder |
| `python3 main.py review` | Critique the latest package and renders |
| `python3 main.py approve` | Human approval pass on the latest campaign |

Use `-h` / `--help` on any command for details.

## Outputs

Artifacts land in `outputs/` with predictable timestamps (`YYYY-MM-DD_HHMMSS`):

| Pattern | Meaning |
|---------|---------|
| `*_session.json` / `*_plan.md` | Planning |
| `*_content_package.md` | Repurpose package |
| `*_page_turn_loop/` / `*_ritual_reel/` | Single-render drafts |
| `*_campaign/` | `create all` campaign folder |
| `*_campaign/ritual_reel/` | Campaign Ritual Reel draft |
| `*_campaign/page_turn_loop/` | Campaign Page Turn Loop draft |
| `*_campaign/render_queue_summary.md` | Queue result summary |
| `*_campaign/approvals.json` | Approval decisions |
| `*_campaign/approval_summary.md` | Grouped approval summary |
| `latest_review.md` / `latest_scores.json` | Latest Review Brain output |

Campaign folders are the canonical place for batch renders + approval. Single-render commands still write top-level draft folders when you need one piece only.

## Project structure

```text
betty-os/
  app.py                  # Streamlit studio UI
  main.py                 # CLI entry point
  ui/                     # UI data access, view models, workflow wrappers
  src/                    # Shared helpers (paths, brains, package parsing)
  brands/oh_betty_jaletti/  # Brand Brain
  production/             # Production Brain + templates
  review/                 # Review Brain
  library/                # Indexed asset library
  assets/                 # Source media
  outputs/                # Generated artifacts (gitignored)
  docs/                   # Principles, vision, roadmap, architecture
```

## Brand Brain & Production Brain

- **Brand Brain** — `brands/oh_betty_jaletti/*.md` loaded by plan, repurpose, and review.
- **Production Brain** — `production/*.json` + `style_guide.md` loaded by renderers.
- **Review Brain** — `review/` critiques packages and renders; does not rewrite copy.

## Future roadmap

Near-term focus after v1.0.0-beta:

- Stronger brand QA against Brand Brain
- Additional platform-specific workflows as real production needs appear
- More render templates only when a campaign piece repeatedly needs them

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md).

## Project philosophy

- Build only what today's sprint requires.
- Build the smallest thing that works.
- Prefer readability over cleverness.
- Keep the engine generic; keep brand knowledge in brand profiles.
- Local-first: files on disk, no required cloud.

Full constitution: [docs/PROJECT_PRINCIPLES.md](docs/PROJECT_PRINCIPLES.md).

## Docs

- [Project Principles](docs/PROJECT_PRINCIPLES.md)
- [Product Vision](docs/PRODUCT_VISION.md)
- [Roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Production Brain](production/README.md)
