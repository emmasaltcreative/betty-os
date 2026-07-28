# Studio Implementation Audit

Inspected from live BettyOS code on 2026-07-28. Findings cite real modules, not filenames alone.

---

## 1. Streamlit entry point

- **Entry:** `app.py` → `main()`
- **Launch:** `streamlit run app.py` (README); theme from `.streamlit/config.toml`
- **Shell responsibilities:** `st.set_page_config`, `inject_theme()`, `nav.init_state()`, `build_campaign_state()`, sidebar radio → screen `render()`
- **No** multipage `pages/` folder — single-app routing via imported screen modules under `ui/screens/`

---

## 2. Navigation architecture

- **Module:** `ui/nav.py`
- **Current `NAV_ITEMS`:** Home, Campaigns, Create, Review, Approvals, Export, Library, Settings
- **Missing for this sprint:** Studio (primary), Revisions as top-level (today nested under Review)
- **Deep links:** `goto(destination, tab=…)`, `PENDING_NAV` / `PENDING_TAB`, `step_selector()`
- **Workflow rail:** `ui/status.py` → `WORKFLOW_STEPS`: Brief → Content → Create → Review → Revise → Approve → Export  
  **Must insert Studio** between Create and Review
- **Active campaign:** session key `active_campaign` stores folder name under `outputs/`

---

## 3. Render-version model

- **UI model:** `ui/campaign_state.RenderVersion` — template_id, piece_id, version int, kind (`video`|`image`|`copy`), primary_path, media_files, approval fields
- **Discovery:** `discover_render_versions()` groups files by `_vN` in filename (`ui.capability.version_in_filename`)
- **On-disk (dual):**
  - Video: `review/versioning.py` → `versions.json` + `{name}_vN.mp4`
  - Static/carousel/copy: `render_manifest_v{N}.json` + `_vN` outputs via `renderers.primitives.write_render_manifest`
- **Approvals:** `src/templates/approvals_store.py` + `ApprovalRecord` — per-file rows aggregated by UI

Studio must attach finished versions to an existing `RenderVersion` without overwriting its media.

---

## 4. Output-directory conventions

There is **no** top-level `campaigns/` or `renders/`. Layout:

```
outputs/{stamp}_campaign/
  {template_id}/                    # video often flat here
    {piece_id}/                     # static / carousel / copy
      *_vN.png|mp4|md
      render_manifest_vN.json
      versions.json                 # video
  approvals.json
outputs/exports/
outputs/studio_renders/             # orphan fallback when campaign_dir is None
```

**Studio adaptation (compatible, not parallel):**

```
outputs/{campaign}/{template_id}/[piece_id/]studio/
  drafts/{draft_id}/finish_config.json
  finish_v001/
    outputs/
    previews/
    finish_config.json
    finish_metadata.json
    validation.json
```

Brand-level Studio data lives under `brands/{brand_id}/studio/`.

---

## 5. Image-processing dependencies

`requirements.txt`: typer, rich, pydantic, python-dotenv, anthropic, **pillow**, streamlit

- Pillow used in `renderers/primitives.py` and CLI overlays in `main.py`
- **No** OpenCV, numpy, imageio, or moviepy today
- **Add for Studio:** `numpy` (LUT, grain, color math). Optional SVG rasterization via system `rsvg-convert` / cairosvg when available; PNG preferred for logo compositing

---

## 6. FFmpeg utilities

| Location | Role |
|---|---|
| `renderers/primitives.py` | `ensure_ffmpeg()`, `extract_frame()` |
| `ui/data_access.py` | `ffmpeg_available()` (ffmpeg + ffprobe) |
| `main.py` | duration, frame extract, ritual reel / page-turn filter graphs |

Video finishing should reuse subprocess argument lists (no shell interpolation) and store the exact command in finish metadata.

---

## 7. Preview components

- `ui/components.media_preview(version)` — `st.video` / `st.image` / caption text
- Used on Create and Approvals
- Export “preview” is a plan list, not media
- **Reusable** for original source; Studio needs its own before/after comparison UI

---

## 8. Brand-asset storage

- `brands/oh_betty_jaletti/*.md` — Brand Brain only (identity, products, visual language, …)
- `library/assets.json` + thumbnails — shoot media index, not logos
- **No** logo SVG/PNG library exists
- `missing_logo_file` exists only as a revision requirement type

Studio must create persistent brand-asset records under `brands/{id}/studio/`.

---

## 9. Persistence helpers

- `src/persistence.py`: `atomic_write_text`, `atomic_write_json`, `load_json`
- Pattern used by approvals, assignments, versioning, manifests
- **Reuse** for all Studio metadata; finish directories should be assembled in temp then atomically moved into place

---

## 10. Download logic

- `ui/components.download_file(path, label, key, mime)` — reads bytes into `st.download_button`
- Currently Export ZIPs only
- **Reuse** for finished assets, previews, configs, and Studio packages (after integrity checks)

---

## 11. Capability-status system

- `ui/capability.py` → `Capability` dataclass + `capability_report()` grouped Working / Partial / Unavailable
- Shown on Settings; evidence from disk mtimes / JSON stamps
- Status vocabulary in `ui/status.py` (`ready` / `partial` / `planned` / …)
- Studio must extend reporting with **persisted test evidence** under brand studio capabilities — Ready only after real successful process + validation

---

## 12. Functionality that can be reused

- Atomic JSON persistence
- Campaign state / RenderVersion discovery
- `media_preview`, `download_file`, page chrome (`page_header`, `section`, badges)
- FFmpeg availability checks and frame extraction
- Approvals store patterns (reload-after-write)
- Production rules markdown/JSON surfaces in Library
- Non-destructive export packaging philosophy

---

## 13. Code that would conflict with Studio

1. Dual revision systems (legacy global queue vs unwired `services/revision_store`) — do not couple finish versions to either until Send to Review is explicit
2. Dual versioning schemes (versions.json vs render_manifest) — Studio keys off `RenderVersion` + absolute source path
3. Layout asymmetry (flat video vs piece-scoped stills) — path helpers must resolve both
4. Legacy folder aliases (`ritual_reel` ↔ `cinematic_multi_clip_reel`) — use `canonical_template_for_folder`
5. `outputs/studio_renders` orphan path — Studio must not write finished work there for campaign assets
6. Global `latest_scores.json` — Review linkage for finished versions should be campaign-scoped metadata, not overwrite global scores
7. No existing logo assets — upload path is required before logo placement can be Ready

---

## 14. Migration risks

- Adding `studio/` under existing render folders is additive and safe
- Discovery must ignore `studio/` when collecting render media (update `NON_RENDER_ENTRIES` / walk filters)
- Workflow step insertion must not break `STEP_DESTINATION` deep links
- Do not migrate or delete existing renders, drafts, or approvals
- Brand studio JSON files are new; seed OBJ recipes on first access without clobbering user edits

---

## 15. Implementation plan

### Phase 1 — Data and persistence
- Brand assets, Color Recipes (incl. 10 OBJ starters), finish drafts, immutable finish versions, atomic writes, path helpers, ignore `studio/` in render discovery

### Phase 2 — Static Studio
- Source selection UI, proxy preview, logo/light/color/texture/geometry, validation, full-res process, downloads

### Phase 3 — LUTs
- Library LUTs, `.cube` parse/validate, static apply, video `lut3d` via FFmpeg

### Phase 4 — Video Studio
- Metadata, overlay, grading filters, grain/vignette/sharpen, export presets, validation, download

### Phase 5 — Workflow
- Nav + Studio page, Library Brand Assets / LUTs tabs, Send to Review, capability evidence, Studio Package, tests, report

### Out of scope (do not scaffold)
- Generative retouch, AI fill/extend, provider abstractions, fake capability buttons

---

## Dependencies to add

| Package | Justification |
|---|---|
| `numpy` | Deterministic LUT apply, grain, color channel math on static images |

SVG compositing: prefer transparent PNG; rasterize SVG when a safe converter is available; otherwise Partial capability.

---

## Environment notes

- FFmpeg + ffprobe present at `/opt/homebrew/bin/` on audit machine
- Pillow 12.3.0 installed
- Sample static render: `outputs/2026-07-27_191825_campaign/editorial_static_pin/.../editorial_static_pin_v1.png`
- Sample video renders under campaign `ritual_reel` / `cinematic_multi_clip_reel`
