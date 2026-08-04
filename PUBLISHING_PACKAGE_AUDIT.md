# Publishing Package Audit

**Date:** 4 Aug 2026  
**Scope:** Campaign export / Deliver packaging (`ui/export_service.py` and callers)  
**Regression fixture:** `outputs/2026-07-27_191825_campaign` / latest `*_approved.zip`

## Verdict

Export is **render-version–centric**, not piece- or finish-centric. The gate is
campaign `approvals.json` on **render versions**. Approved Studio finishes are
**bundled alongside** their parent render files and never substitute for them.
There is **no** “one final per content piece” rule, **no** content-hash
deduplication, **no** metadata↔media pairing validation, **no** copy-readiness
gate, and **no** dedicated packaging tests. The default Deliver path hardcodes
`mode="approved"`, which ships every approved version of every template.

---

## End-to-end flow (current)

```
discover_render_versions() → apply_approvals() → build_plan(mode)
  → create_export_package() → ZIP under outputs/exports/
```

| Step | Location |
|------|----------|
| Discovery | `ui/campaign_state.py` — `discover_render_versions`, `_group_versions` |
| Approvals fold-in | `apply_approvals` ← `approvals.json` |
| Studio finishes | `finish_records_for_version` / `approved_finish_records_for_version` |
| Plan + ZIP | `ui/export_service.py` — `build_plan`, `create_export_package` |
| Deliver UI | `ui/screens/workspace.py` — `_stage_deliver` (`mode="approved"`) |
| Advanced Export UI | `ui/screens/export.py` |
| Per-finish Studio ZIP (not publishing) | `studio/package.py` |

---

## 1. How approved assets are selected

Modes in `MODES`:

| Mode | Rule |
|------|------|
| `approved` | Every `RenderVersion` with `approval_status == "approved"` |
| `latest` | Newest version per `(template_id, piece_id)` regardless of approval |
| `selected` | Explicit checkbox keys |
| `archive` | Every version; also includes drafts + JSON metadata |

Deliver always uses `approved`. Studio finish approval alone does **not** unlock
export; campaign `approvals.json` on the render version does.

## 2. Render versions vs finished / Studio versions

| Concept | Identity | Storage |
|---------|----------|---------|
| Render version | integer `v{N}` | Files in piece/template folder |
| Studio finish | `finish_vNNN` | `{folder}/studio/finish_vNNN/` + `finish_metadata.json` |

Bridge: `render_version_id(n) → "render_v{n:03d}"` matched to
`FinishRecord.parent_render_version_id`.

## 3. Where approval attaches

- **Export gate:** render version (`approvals.json` via Approvals / Decide).
- **Finish approval:** separate `FinishRecord.approval_status`.
- Saving a render decision mirrors status onto finishes with
  `status == "ready_for_review"` only (`_mirror_finish_status`).
- Studio `set_finish_approval()` does **not** write campaign `approvals.json`.

**Implication:** Export treats “approved render” as the unit. Finish approval is
only used to decide which finish files to *append*, not which asset is the
canonical publishable file.

## 4. Why multiple versions of one piece enter the ZIP

`approved` mode includes **every** approved version, not “latest approved per
piece.” Regression package includes Cinematic Multi-Clip Reel v1, v3, and v4
because all three are approved.

One content piece can also appear under multiple templates (e.g. carousel +
Instagram caption on the same piece) — those are separate destinations and
should remain distinct after the fix.

## 5. Why duplicate files enter the ZIP

No content hashing. Duplicates arise from:

1. Parent render media **plus** Studio finish outputs (often near-identical).
2. Multiple approved versions of the same piece.
3. Shared unversioned captions attached to every version lacking its own.
4. Archive mode also dumping drafts/metadata.

ZIP arcnames differ even when bytes are identical, so ZipFile stores both.

## 6. Why parent renders remain when an approved Studio finish exists

By design in `_finish_files` + `create_export_package`: finishes are **additive**.
Comment in code: *“an approved one has to travel with the render it was built
from.”* There is no “finish overrides parent” rule.

Regression: ZIP contains `ritual_reel_v1.mp4` **and**
`studio/finish_v001/finished.mp4` **and** `studio/finish_v004/finished.mp4`.

## 7. How copy and metadata artifacts are classified

During `_group_versions`:

| Suffix / name | Bucket | In non-archive export? |
|---------------|--------|------------------------|
| `.mp4/.mov/.png/.jpg/.jpeg` | `media_files` | Yes |
| `.md/.txt` | `support_files` | Yes |
| Unversioned leftover media on latest | `draft_files` | Archive only |
| `.json` | `metadata_files` | Archive only |

Copy templates (`instagram_caption`, `pinterest_caption_metadata`, …) are full
`RenderVersion`s with `kind="copy"` — primary is the `.md` itself.

## 8. Why incomplete Pinterest metadata can enter the package

- Copy renderers always emit Title / Description / CTA scaffolding.
- Export treats an approved copy version like any other approved version.
- **No** field completeness checks.
- **No** “must accompany a pin image” rule.
- Regression pieces 004/005 ship as approved `.md` files whose Description is
  blank and whose body is production instructions (“extract still frame”,
  asset paths, recommended shot order).

## 9. Metadata ↔ media validation

**None.** `create_export_package` only checks: campaign open, plan non-empty,
ZIP write succeeds, file non-zero size.

## 10. Filename / folder generation

- **ZIP name:** `{campaign_folder}_{timestamp}_{mode}.zip`
- **Inside (render):** `{template_id}/{piece_id}/v{N}/{original_filename}`
- **Inside (finish):** `{template_id}/{piece_id}/v{N}/studio/{finish_id}/{original_filename}`
- **Manifest:** root `MANIFEST.md` only

Exposes internal Studio / version folder structure to the user.

## 11. Current manifest structure

Markdown only:

- Campaign / Goal / Contents / Created / Files / Size
- Included labels + nested Studio finish filenames
- Excluded labels + reasons

No per-file inventory, hashes, platforms, pairing IDs, or publish-readiness.

## 12. Current tests

**No tests import or exercise `ui/export_service`.**

Related coverage only:

| File | Touches |
|------|---------|
| `tests/test_experience_2.py` | Nav Export→deliver; ready-to-export continuation |
| `tests/test_persistence.py` | `approvals.json` upsert/reload |
| `tests/test_templates_acceptance.py` | Approval survives reload |
| `tests/test_studio.py` | `build_studio_package` / finish persistence (not campaign ZIP) |

## 13. Migration risks

| Risk | Detail |
|------|--------|
| Selection semantics change | Switching to one-canonical / finish-overrides-parent changes ZIP contents vs historical packages |
| Dual approval | Studio approve ≠ exportable; finish mirror only for `ready_for_review` |
| Finish id bridge | Must keep `render_vNNN` ↔ integer version mapping |
| Shared `studio/` per folder | Multiple finishes share one tree; filter by `parent_render_version_id` |
| Mode rename | Deliver/Export callers hardcode `approved`; alias needed |
| Manifest consumers | Only human-readable MD today; adding JSON is additive |
| No export tests today | High regression risk without new coverage |
| Historical versions | Must remain on disk untouched — packaging only |

---

## Gaps vs decisive publishing package

| Desired | Current |
|---------|---------|
| One canonical final per piece + platform | All approved versions of all templates |
| Finish overrides parent | Parent always included; finish nested beside it |
| Hash dedup | None |
| Validation + pairing | None |
| Clean platform folders + descriptive names | Template/piece/version/studio nesting |
| Human README | Thin `MANIFEST.md` |
| Publishing vs archive | Four modes; Deliver multi-version + parent+finish |
| Summary UI before ZIP | Thin included list; no exclusion detail on Deliver |

---

## Target behavior (this sprint)

1. Default **Publishing Package**: one canonical approved final per content piece
   and platform destination.
2. Latest approved Studio finish wins; exclude parent render media when finish
   ships; retain lineage in manifest.
3. Fallback to latest approved render only when no approved finish exists.
4. Copy-only pieces export when genuinely copy-only and copy-ready.
5. Hash-based dedup; orphaned/incomplete metadata excluded; production notes
   rejected.
6. Clean ZIP layout + README.txt + manifest.json.
7. Archive Package remains a separate advanced mode.
8. Never delete or overwrite historical versions in BettyOS.
