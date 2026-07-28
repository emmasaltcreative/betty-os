# Integration Audit — AI Revision Engine × Studio

Verification sprint, 28 July 2026. Scope was integration and validation only: no new
features, no UI redesign, no AI image enhancement.

Both sprints were delivered uncommitted into the same working tree, so there was no
merge to resolve in the git sense. The conflicts were behavioural: the two sprints
touched the same screens and the same version model, and each assumed it was the only
writer.

Every claim below was checked through the running application on `localhost:8520`,
not read off the source.

---

## 1. Conflicts found

### 1.1 Studio handed finished work to Review, and Review never looked

Studio's **Send to Review** wrote `studio/review_links.json` next to the render and set
the finish record to `ready_for_review`. Nothing read either. A finished version could be
submitted and would never appear anywhere a reviewer looks, so the
`Send to Review → Approve` half of the workflow had no path through the app.

### 1.2 Approvals showed finishes belonging to other versions

The Approvals screen listed every finish in the render folder against every version of
that render. Because a template folder holds one `studio/` directory shared by all its
versions, `finish_v001` built from version 1 appeared under version 4 as well. Draft
finishes nobody had submitted were also shown as if awaiting sign-off.

### 1.3 Approval decisions never reached the finished version

Approvals wrote its decision to `approvals.json` and `versions.json`. The finish record
kept `approval_status: awaiting_review` forever. A finished version could be approved by
a person and still read "Awaiting Approval" in Studio and Review.

### 1.4 Export ignored Studio output entirely

`ui/export_service.py` planned and packaged render media only. The finished file — the
artefact that would actually ship — was left out of the ZIP and the manifest.

### 1.5 Studio claimed capabilities it had not exercised

`create_finish` recorded a capability success for lighting, colour and crop on every run,
including runs where those controls sat at their defaults. Capability Status reported
"Ready" on the strength of a code path executing, not a setting being applied.

### 1.6 Studio reported unsaved work that did not exist

Three separate causes, all of which made the save state untrustworthy:

- Each editor section wrote its widget values back and then unconditionally marked the
  draft dirty. Merely drawing the editor was recorded as an edit.
- The export section derives `format = "mp4"` and `fps = 0.0` from the media type on
  every redraw. On a video source this changed the configuration on first draw, so even
  a comparison-based dirty check saw a real difference.
- **Save Draft** wrote to disk but did not redraw, and the save-status badge is rendered
  above the button. A successful save still read "Unsaved".

Consequences: opening Studio on a video and changing render version raised
*"Save or discard your draft before switching to a different source"* about work nobody
had done, and the badge could not be used to confirm that a draft had persisted.

### 1.7 Terminology

"Creative Finishing" survived in `studio/__init__.py` and
`STUDIO_IMPLEMENTATION_REPORT.md`.

---

## 2. Files modified

| File | Change |
| --- | --- |
| `ui/campaign_state.py` | Added `finish_records_for_version`, `finished_versions_sent_to_review`, `approved_finish_records_for_version` — the shared read path pairing a finish with its true parent version. |
| `studio/versions.py` | Added `resolve_finish_outputs` and `resolve_finish_preview` so callers resolve recorded outputs without rebuilding paths. |
| `ui/screens/review.py` | Added the "Finished versions from Studio" panel: shows the finished file itself, its parent version, recipe, decision, and a download. Consumes the previously orphaned Send-to-Review contract. |
| `ui/screens/approvals.py` | `_finished_links` now filters by `parent_render_version_id` and shows only `ready_for_review` finishes. |
| `ui/workflow_service.py` | Added `_mirror_finish_status`: an approval decision is carried onto the submitted finishes it covers. Drafts are untouched; only the status field is written, never the media. |
| `ui/export_service.py` | `ExportItem.finish_files`; approved finishes (all, in archive mode) are counted, written into the ZIP under `<template>/v<n>/studio/<finish_id>/`, and listed in the manifest. |
| `ui/screens/export.py` | Plan preview reports how many Studio finishes an item contributes. |
| `studio/service.py` | Added `_touched`; capability success is recorded only when the relevant settings group differs from its defaults. |
| `ui/screens/studio.py` | `_set_config` marks dirty only on a real change; added `_normalise_for_media` to settle media-derived export values once at load; **Save Draft** redraws and carries its confirmation across. |
| `studio/__init__.py`, `STUDIO_IMPLEMENTATION_REPORT.md` | "Creative Finishing" → Studio. |

No renderer, pipeline, or revision-engine logic was changed.

---

## 3. Fixes applied

1. Review consumes Studio's Send-to-Review contract and shows the finished media.
2. Finishes are attached to the render version that produced them, and only when submitted.
3. Approval decisions propagate to the finished versions they cover.
4. Export ships the finished file and records it in the manifest.
5. Capability evidence requires a setting to have been used, not merely a code path run.
6. Studio's dirty tracking reflects actual edits; the save badge can be trusted.
7. Remaining "Creative Finishing" wording replaced.

`57 passed, 8 subtests passed` after the changes.

---

## 4. End-to-end verification

Run against the live app. Every step was observed in the UI and confirmed on disk.

| Step | Result |
| --- | --- |
| Original render | `ritual_reel_v1.mp4`, Cinematic Multi-Clip Reel |
| AI Review | Scored 6.3 overall, six dimensions, three recommendations |
| Generate AI Suggestions | Three suggestions per recommendation, brand-checked |
| Select suggestion | Selection and comparison shown before applying |
| Create new render version | **version 4** created from version 3, `ritual_reel_v4.mp4` + `caption_v4.md` |
| Open Studio | Version 4 offered immediately; source `ritual_reel_v4.mp4` |
| Apply colour recipe | `obj_rainy_reading` ("OBJ Rainy Reading") |
| Apply logo | Primary Logo, asset "Oh Betty Primary", bottom right |
| Save Draft | Written to `studio/drafts/…_render_v004_ritual_reel_v4/finish_config.json`; badge reads "Saved" |
| Create finished version | **`finish_v002`**, parent `render_v004`, `finished.mp4`, 13.6 s, 13,280,233 bytes, validation pass |
| Send to Review | `status: ready_for_review`, `review_links.json` written |
| Review | "Cinematic Multi-Clip Reel — version 4 · finish_v002", built from version 4 |
| Approve | Approved count 2 → 3; recorded in `approvals.json`, `versions.json`, and `finish_v002` |
| Export | `…_143358_approved.zip`, 8 files, 22.7 MB, containing `cinematic_multi_clip_reel/v4/studio/finish_v002/finished.mp4` |

The finish is numbered `finish_v002` rather than `finish_v001` because finish numbering is
per render folder and that folder already held a `finish_v001` built from version 1. The
parentage is explicit in the record, so this is correct behaviour rather than a defect.

### Confirmations

**Original renders are never overwritten.** SHA-256 of every file under `outputs/` and
`brands/` was captured before and after each mutating step.

- Applying the revision: 167 files unchanged; 4 added (`ritual_reel_v4.mp4`,
  `caption_v4.md`, `render_settings_v4.json`, a render config); 3 append-only indexes
  modified (`versions.json`, `revision_requests.json`, `latest_scores.json`). No existing
  media byte changed.
- Creating the finish: 176 unchanged; 6 added under `studio/finish_v002/`; the only
  modification was `capabilities.json`; the draft was removed, having been consumed into
  the finish by design. `ritual_reel_v4.mp4` and the earlier `finish_v001` were untouched.

**Render versions remain immutable.** v1, v2 and v3 media hashes are unchanged after
producing v4 and after approval. Version 4 in the export ZIP is byte-identical to
version 4 on disk.

**Finish versions remain immutable.** Approval modified only the `approval_status` field in
`finish_metadata.json`. `finished.mp4` in the ZIP is byte-identical to `finished.mp4` on
disk (`e45a103a…fbbd`).

**Studio drafts persist after restart.** The process was stopped and restarted with the v4
draft on disk. Studio reopened on version 4 showing recipe "OBJ Rainy Reading", logo role
"Primary Logo" and asset "Oh Betty Primary" — all reloaded from disk, with the badge
reading "Saved".

**Review references the correct finished version.** Review shows `finish_v002` as built
from Cinematic Multi-Clip Reel version 4, and `finish_v001` as built from Editorial Static
Pin version 1. Neither leaks into the other's version.

**Approval status persists.** After restart, Review shows `finish_v002` as "Approved" and
Approvals reports 3 approved / 1 awaiting / 4 needs revision — identical to before.

**Download buttons point to valid files.** `download_file` reads the bytes at draw time and
reports failure visibly. All ten screens were walked: 6 download buttons rendered
(Studio 1, Review 2, Export 3), zero unreadable files, zero errors. The Studio package ZIP
was built and opens cleanly (`testzip()` returns `None`).

**Capability Status reflects actual working functionality.** Every "Ready" entry carries
evidence naming the run that earned it — Video Logo Placement and Colour Recipes point at
`finish_v002`, the static entries at `finish_v001`. Untested controls report
"Not Available / Evidence: Not tested yet". Studio Package Download was "Planned",
was exercised, and flipped to "Working" in Settings on that evidence.

### Persistence after restart

The app was stopped and restarted, then every screen was visited. 186 of 186 file hashes
identical — browsing the restarted app mutates nothing.

| Expected to survive | Result |
| --- | --- |
| Revision history | 2 applied, 1 failed, with chosen replacements, produced versions and timestamps |
| Render versions | 8 versions across 5 templates, lineage intact (v4 ← v3 ← v2 ← v1) |
| Finish versions | `finish_v001` and `finish_v002` with recipes, statuses and validation |
| Studio settings | Draft recipe, logo role and logo asset reloaded from disk |
| Approvals | 3 approved / 1 awaiting / 4 needs revision, and `finish_v002` reads Approved |

---

## 5. Remaining limitations

These are real and were left alone: none of them blocks the workflow, and fixing them
would mean new features or redesign.

**Single-Clip Atmospheric Loop cannot be revised.** One revision request is permanently
`failed`: *"No renderer can build a revised version of Single-Clip Atmospheric Loop."* The
failure is reported honestly, the render was left untouched, and the home screen surfaces
it as a blocker. Fixing it needs a renderer, which is out of scope.

**Some Studio controls have never been demonstrated.** Brand Asset Upload, Static .cube
LUT, Video Vignette, Video Sharpening and Before-and-After Static Preview are implemented
and wired to record evidence, but report "Not Available — not tested yet" because this
verification did not exercise them. This is the capability system being honest, not a
defect; the status will change the first time each is used.

**Panels within the acting screen can lag by one redraw.** Streamlit draws a screen top to
bottom, so a panel above a button shows the state from before the click. After **Create
Finished Version** the Finished-versions list still reads "No finished versions yet", and
after **Send to Review** the status still reads "draft". Both correct themselves on the
next interaction, and the persisted state is right immediately. Save Draft was fixed
because save status is load-bearing for confirming a draft persisted; the rest are
cosmetic and fixing them generally would mean reordering the screen.

**A fresh editor with no draft reads "Unsaved".** When Studio opens a source that has no
saved draft, the badge says "Unsaved" although nothing has been changed and there is
nothing to save. Genuine edits and genuine saves now report correctly; this is the
remaining edge in the label's vocabulary.

**Approval is per render version, not per finish.** One decision covers a render version
and every submitted finish built from it. Approving version 4 approved `finish_v002` with
it. If two finishes from one version ever need separate sign-off, the model would have to
change — deliberately not done here.

**Review scores describe the campaign, not the finish.** The 6.3 shown beside a finished
version is the campaign-wide review score, and the AI review reads render media rather
than finished media. A finish is therefore presented for a decision but not separately
scored.
