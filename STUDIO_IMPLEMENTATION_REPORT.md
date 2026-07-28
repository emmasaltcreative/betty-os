# Studio Implementation Report

Studio sprint (deterministic finishing) — completed 2026-07-28.

## Architecture implemented

Studio is a non-destructive finishing layer beside existing render folders:

```
outputs/<campaign>/<template_id>/[piece_id/]
  <render outputs>
  studio/
    drafts/<draft_id>/finish_config.json
    finish_v001/
      outputs/
      previews/
      finish_config.json
      finish_metadata.json
      validation.json
      studio_package.zip   # on demand
    review_links.json

brands/oh_betty_jaletti/studio/
  brand_assets.json + assets/
  color_recipes.json
  luts.json + luts/
  production_guardrails.json
  capabilities.json
  preview_cache/
```

**Pipeline order (static):** decode → geometry → LUT → light → color → texture → logo → encode → validate.

**Video:** FFmpeg filter graph (eq, colorbalance, noise, unsharp, vignette, lut3d, overlay, fades) with command stored in finish metadata.

Finished versions are assembled in a temp directory under `studio/`, then renamed into `finish_vNNN/`. Source renders are never overwritten.

## Files added

| Path | Role |
|---|---|
| `STUDIO_IMPLEMENTATION_AUDIT.md` | Pre-implementation audit |
| `studio/__init__.py` | Package + supported media |
| `studio/paths.py` | Storage path helpers |
| `studio/models.py` | Finish / brand / recipe / LUT models |
| `studio/brand_assets.py` | Brand asset library |
| `studio/recipes.py` | Color Recipes + 10 OBJ starters |
| `studio/guardrails.py` | OBJ product production rules |
| `studio/luts.py` | `.cube` parse/apply/library |
| `studio/versions.py` | Drafts + immutable finish versions |
| `studio/validation.py` | Source/config/logo/output validation |
| `studio/image_pipeline.py` | Static finishing engine |
| `studio/video_pipeline.py` | FFmpeg finishing engine |
| `studio/apply_recipe.py` | Recipe → config |
| `studio/service.py` | Preview / create / send-to-review |
| `studio/package.py` | Downloads + Studio Package ZIP |
| `studio/capabilities.py` | Persisted capability evidence |
| `ui/screens/studio.py` | Studio workspace UI |
| `tests/test_studio.py` | Targeted Studio tests |

## Files modified

- `app.py` — Studio + Revisions nav routing
- `ui/nav.py` — Studio, Revisions in `NAV_ITEMS`
- `ui/status.py` — Studio in workflow rail
- `ui/campaign_state.py` — ignore `studio/` media; workflow/next-step Studio awareness
- `ui/capability.py` — Studio capability rows; restored `revision_execution_key`
- `ui/screens/create.py` — Open in Studio
- `ui/screens/review.py` — finished versions + Return to Studio
- `ui/screens/approvals.py` — View Finished Version
- `ui/screens/library.py` — Brand Assets + LUTs tabs; guardrails
- `requirements.txt` — added `numpy`

## Dependencies added

- **numpy** — LUT application, grain, color channel math

Optional (not required): `rsvg-convert` or `cairosvg` for SVG logo rasterization. Transparent PNG is preferred and fully supported.

## Data migrations

None destructive. Additive only:

- New `studio/` folders under existing render dirs
- New `brands/*/studio/` JSON + asset stores
- OBJ Color Recipes seeded on first access without overwriting edits

## Static capabilities completed

Ready after successful acceptance run (persisted evidence):

- Brand Asset Upload
- Static Logo Placement
- Static Lighting / Color / Grain / Vignette / Sharpening
- Crop and Resize
- Color Recipes
- Static .cube LUT (implementation + identity LUT tested in unit tests; apply during finish when selected)
- Before-and-After Static Preview
- Finished-Version Persistence
- Static Downloads
- Studio Package Download

## Video capabilities completed

Ready after successful acceptance run:

- Video Logo Placement
- Video Color Adjustment
- Video Grain / Vignette / Sharpening
- Video .cube LUT (via FFmpeg `lut3d`)
- Video Audio Normalization (wired; source in acceptance had no audio)
- Before-and-After Video Preview
- Video Downloads

## Partial capabilities

- **SVG Logo Preview** — works when `rsvg-convert` / cairosvg present; otherwise store SVG and require PNG for compositing
- **Video LUT intensity** — full-strength only (FFmpeg path); static supports blend intensity
- **Before-and-After Video Preview** — separate labeled previews; synchronized scrub not implemented
- **Proxy vs final** — preview may use lower resolution; finished versions always process full-resolution source

## Unavailable / not in sprint

- All generative / AI visual enhancement (intentionally omitted)
- Semantic product verification (rules stored as “Not Automatically Verified”)
- Motion tracking / subject-aware logo avoidance

## Exact tests run

```text
pytest tests/                 → 27 passed
pytest tests/test_studio.py   → 15 passed
```

Manual/programmatic acceptance against `outputs/2026-07-27_191825_campaign`:

**Static**

1. Source `editorial_static_pin_v1.png` validated (1000×1500)
2. Primary logo uploaded / selected
3. OBJ Editorial Lifestyle applied; exposure + grain; bottom-right safe margin
4. Draft saved and reloaded
5. Created `finish_v001` (full-res PNG ~1.9MB)
6. Original render bytes unchanged
7. Studio Package written
8. Sent to Review (`ready_for_review`)
9. Metadata survived reload (recipe, logo, exposure)

**Video**

1. Source `ritual_reel_v2.mp4` probed
2. Logo overlay + brightness/contrast + grain + identity `.cube` LUT
3. Created `finish_v001` MP4 (1080×1920, ~13.6s, decodable)
4. Original video size unchanged
5. Capability evidence updated from real processing

## Known limitations

- Continuous slider split preview is approximated as left/right panels
- Perspective correction not implemented (not claimed)
- Video temperature is an honest FFmpeg `colorbalance` approximation
- Finished-but-not-sent versions use Studio status `draft` until Send to Review sets `ready_for_review`
- Large video finishes can take tens of seconds; UI uses `st.status` stages

## Manual setup required

1. `pip install -r requirements.txt` (includes numpy)
2. FFmpeg + ffprobe on PATH for video Studio
3. Optional: `brew install librsvg` for SVG logo rasterization
4. Upload brand logos under Library → Brand Assets
5. Upload `.cube` files under Library → LUTs when desired

## Final workflow (product)

**Nav:** Home · Campaigns · Create · **Studio** · Review · Revisions · Approvals · Export · Library · Settings

**Path:** Campaign → Create → Studio → Creative Review → Revisions → Approvals → Export

- Create: **Open in Studio**
- Studio: Preview / Save Draft / Create Finished Version / Send to Review / Downloads
- Review: lists finished versions marked `ready_for_review`
- Approvals: **View Finished Version**
- Library: Brand Assets, LUTs, Production guardrails

## Recommended next sprint

Stabilize and deepen the deterministic foundation before any generative work:

1. Interactive crop/straighten canvas in the preview
2. Richer video preview (optional synced scrub)
3. Export packaging that prefers Studio finished versions when present
4. Per-campaign Creative Review scoped to finished versions
5. Only after the above is solid: consider assistive tools that never overwrite Studio outputs

Do **not** start AI enhancement until this deterministic Studio path remains stable under daily use.
