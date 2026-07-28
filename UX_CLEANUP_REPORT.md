# BettyOS UX Cleanup Report

**Date:** 2026-07-28
**Scope:** Streamlit interface only. No renderer capability, AI feature, or template was added.
**Companion document:** `UX_AUDIT.md` (written before any code changed).

The product now has one workflow with one home for every action:

> Campaign → Content → Create → Review → Revise → Approve → Export

---

## 1. Pages changed

The sidebar went from 11 internal-sounding pages to the 8 areas the sprint specified.

| Area | File | What it does now |
|---|---|---|
| Home | `ui/screens/home.py` | Active campaign, stage, progress rail, counts, blockers, latest activity, and one primary action: **Continue Campaign** |
| Campaigns | `ui/screens/campaigns.py` | Campaign management only: open, create, archive, restore. Shows the opened campaign's overview and next action |
| Create | `ui/screens/create.py` | Three steps — **1. Content**, **2. Template**, **3. Render** — over a single focused workspace per content piece |
| Review | `ui/screens/review.py` | Creative critique and the revisions that come out of it. Two sections: **Creative Review**, **Revisions** |
| Approvals | `ui/screens/approvals.py` | The only place a render version is signed off. One decision per version |
| Export | `ui/screens/export.py` | Package approved work and download it |
| Library | `ui/screens/library.py` | Reference only: **Assets**, **Templates**, **Brand Guide**, **Production Rules** |
| Settings | `ui/screens/settings.py` | Real settings, file locations, and the **Capability Status** panel |

`app.py` shrank from roughly 1,050 lines to 85. It is now only the shell: theme, sidebar, active campaign, and routing.

### New supporting modules

| Module | Why it exists |
|---|---|
| `ui/status.py` | One status vocabulary. Replaces five overlapping ones |
| `ui/capability.py` | Honest capability reporting, derived from renderer code rather than registry claims |
| `ui/campaign_state.py` | One campaign state model: stage, pieces, render versions, approvals, blockers, next step, progress |
| `ui/export_service.py` | ZIP packaging — the one workflow step that had no implementation |
| `ui/nav.py` | Navigation and the single active campaign held in session state |
| `.streamlit/config.toml` | Base palette, so Streamlit's own widget accents (radios, toggles, progress) match the jade theme instead of the default red |

---

## 2. Pages removed or merged

| Was | Now |
|---|---|
| Dashboard | **Merged → Home.** Rebuilt as a status page, not an action launcher |
| New Campaign | **Merged → Campaigns** as a "Create Campaign" form that also creates the campaign folder, so a created campaign actually exists |
| Content Package | **Merged → Create, step 1** |
| Templates | **Moved → Library › Templates** (reference, out of the daily path) |
| Template Builder | **Demoted → Library › Templates › "Define a planned template (advanced)"**, collapsed, and honest that it cannot produce a renderer |
| Renders | **Split → Create step 3** (render, preview, history) and **Approvals** (decisions) |
| Creative Review | **Kept → Review › Creative Review** |
| Revision Queue | **Merged → Review › Revisions** |
| Approvals | **Kept → Approvals**, regrouped by render version |
| Brand Brain | **Renamed and moved → Library › Brand Guide** |
| Settings | **Kept**, with implementation detail moved into a collapsed Advanced section |

Two now-dead modules were deleted: `ui/view_models.py` (view builders nothing referenced any more) and `ui/template_pages.py` (the old Templates and Template Builder pages). Neither is imported by the CLI or the tests.

---

## 3. Controls removed

| Removed | Reason |
|---|---|
| 4 navigation-only buttons on Dashboard | Duplicated the sidebar |
| Duplicate render buttons on Dashboard, Content Package, and Renders | Render now lives only in Create |
| Approval controls on the Renders page and the version-compare panel | Final decisions now live only in Approvals |
| Per-page campaign selectboxes (5 of them) | The campaign is chosen once and held in session state |
| Per-page content-package selectboxes | The package follows the campaign |
| Repeated review summaries on Dashboard and Renders | Review results live only in Review |
| `st.json` dumps of scores, recommendations, revision requests, approvals, and template records | Replaced with readable fields |
| Raw absolute file paths in page bodies | Replaced with names; paths remain in Settings › Advanced |
| Per-file approval rows (caption, draft MP4, versioned MP4, metadata as separate items) | Collapsed into one decision per render version |

**Per-action homes now:** render → Create · creative feedback → Review · final approval → Approvals · download → Export · template reference → Library.

---

## 4. Labels changed

| Internal name | Visible label |
|---|---|
| Brand Brain | Brand Guide |
| Production Brain | Production Rules |
| Review Brain | Creative Review |
| Revision Queue | Revisions |
| Template Registry | Templates |
| Content Package | Campaign Content |
| `ritual_reel` | Cinematic Multi-Clip Reel |
| `page_turn_loop` | Single-Clip Atmospheric Loop |
| `awaiting_review` | Awaiting Approval |
| `awaiting_execution` | Ready to Run |
| `manual_completion_required` | Manual Work Required |
| `ready_for_review` | Awaiting Approval |
| `renderer_status: ready / partial / planned / manual_only` | Ready / Partial / Planned / Manual Only |

Statuses were unified into four vocabularies in `ui/status.py` — campaign, content piece, template, action — plus one for revision execution. The same underlying state now always produces the same word and the same colour, on every page.

---

## 5. Workflow additions

**Progress rail.** Every workflow page shows the same seven-step rail (Brief, Content, Create, Review, Revise, Approve, Export) marking completed, current, blocked, and upcoming steps. Steps advance strictly in order, so a later step never shows as done while an earlier one is open.

**Continue Campaign.** Home's single primary action routes to the next incomplete step, deep-linking to the right section within it: no content → Campaigns; content not rendered → Create; renders not reviewed → Review › Creative Review; approved revisions not run → Review › Revisions; versions awaiting a decision → Approvals; approved work → Export. If every piece is blocked, the button is disabled and says why.

**Export.** New. Four modes — Approved Only, Latest Versions, Selected Assets, Full Archive — with a preview of what is in and what is out (and why) before the package is built. Writes to `outputs/exports/` with a `MANIFEST.md` inside, then offers the ZIP for download. Pre-versioning draft files and render metadata are excluded from normal exports so an approved package never ships a draft beside the finished file.

---

## 6. Bugs found and fixed during the sprint

| Problem | Fix |
|---|---|
| Legacy and canonical render folders both appeared, so every migrated render was listed twice | `_render_folders` prefers the canonical folder and picks whichever actually holds media |
| Approvals were saved with two conflicting schemas across three surfaces, and could silently drop records | `save_version_decision` rewrites the whole item list in one verified write, updates every file in the version, and preserves unrelated records. Verified against a backup: the only change is the new records |
| `ritual_reel_draft.mp4` was bundled into approved exports | Draft files are tracked separately and held back unless Full Archive is chosen |
| Folder `2026-07-27_1916_campaign` displayed as 19:01 | Timestamp format is chosen by digit count, since `strptime` reads `1916` as 19:01:06 |
| Timezone-aware and naive timestamps were compared, crashing the activity feed | One `to_naive` conversion used everywhere timestamps are compared |
| Navigation from a page body was silently reverted by the sidebar's own widget state | Destinations are parked in a pending key and applied before the sidebar is drawn |
| Switching step from inside a page raised `StreamlitAPIException` | Same pattern: `nav.request_step` defers the change to the next run |
| Key/value rows overflowed their card in narrow columns | The key column shrinks, values wrap, and list-style content uses a new `item_list` component |
| A copy render showed its own text twice, as preview and as caption | The caption panel is suppressed when the render *is* the copy |

---

## 7. Button behaviour

Every enabled button performs a real action, reports through one `report()` path that shows the outcome and a timestamp, and persists before claiming success. Long actions run inside `st.status` and end labelled complete or error.

Buttons that are deliberately disabled, with the reason shown:

| Button | Disabled when |
|---|---|
| Create render | The template has no renderer, or source media is missing |
| Save template | The choice already matches what is on disk |
| Save decision | Nothing has changed since the last save |
| Run revisions | Nothing is queued, or the campaign has no reel render to revise |
| Create Export Package | Nothing matches the chosen contents |
| Continue Campaign | Every content piece is blocked |

Nothing reports success for a session-state-only change. The one deliberately honest exception is "Define a planned template (advanced)": it saves successfully but says plainly that the definition cannot render until a developer writes a renderer.

---

## 8. Honest capability visibility

Settings › **Capability Status** reports what actually works, with evidence read from disk (newest render manifest, approval file, revision run, export). It is derived from renderer code, not from `template_registry.json`, because the registry overstates what exists.

**Working (5)** — Cinematic Multi-Clip Reel · Creative Review · Approval saving · Template assignment · Export packaging. Each shows its last successful run.

**Partial (5)**

- **Single-Clip Atmospheric Loop** — renders a finished loop, but ignores the source clip you select and always uses one fixed studio clip.
- **Still image templates (12)** — produce a branded image and caption, but template-specific fields (product name, price, quote, testimonial, launch date, question and answer pairs) are not laid out.
- **Carousel templates (4)** — produce three slides and a caption, but all four share one layout with standard copy; your slide copy is not used and the slide count is fixed at three.
- **Copy templates (8)** — write a markdown draft from the fields you supply; not written from the Brand Guide, and several share one generic layout.
- **Revision execution** — clip removal, rebuild, CTA timing, and caption replacement work on the Cinematic Multi-Clip Reel only. Everything else must be done by hand.

**Not Available (2)**

- **Product Detail Reel, Narrative Text Reel, Contrast Reel, Slideshow Reel** — the registry calls them partial, but no video renderer exists. They are marked Not Available, their Render button is disabled, and the reason is shown.
- **Automatic template creation** — BettyOS does not write renderer code.

The registry's own status field was corrected in the interface for 13 templates: 12 that claim `ready` are shown as **Partial** because they share generic layouts, and `founder_note` claims `partial` but is shown as **Ready** because it does what it describes. The registry file itself was not modified.

---

## 9. Known limitations

- **Template status is corrected in the UI, not in the data.** `templates/template_registry.json` still carries the optimistic values. Fixing the file is a data change and was left out of a UX sprint.
- **Video renders are stored per template, not per content piece.** Two pieces assigned to the same video template would collide on disk. The interface attaches such renders to the first matching piece; a render whose template no piece uses appears under "Renders not linked to a content piece" in Approvals. This is a backend layout issue, not a UI one.
- **Review scores are per campaign, not per asset.** Approvals shows the campaign score and labels it "(whole campaign)" rather than implying a per-version score.
- **Stored review text names internal folders.** Existing `latest_scores.json` prose refers to `ritual_reel` and `page_turn_loop` because it was generated before the rename. New reviews will use whatever the review engine is given; the UI does not rewrite saved review text.
- **Legacy duplicate folders still exist on disk.** `src/templates/migration.py` copied rather than moved, so both `ritual_reel/` and `cinematic_multi_clip_reel/` exist. The interface shows each render once. Removing the duplicates is a data migration and was not performed.
- **Theme is fixed.** Settings lists the theme but offers no switcher; there is one visual system.
- **Render configuration is limited to video.** Length and CTA timing are the only options any renderer reads. Other templates say plainly that they have nothing to configure.

---

## 10. Acceptance test results

Walked end to end against the live campaign `2026-07-27_191825_campaign` (5 content pieces, 6 render versions).

| # | Step | Result |
|---|---|---|
| 1 | Open the active campaign | Pass — restored from session state on load; the sidebar names it and shows its stage |
| 2 | Understand its current stage | Pass — "Creating", with the rail marking Brief and Content done and Create current |
| 3 | Click Continue Campaign | Pass — routes to Create › 1. Content, having said why ("3 content pieces are ready to render") |
| 4 | See which pieces are ready or blocked | Pass — every piece shows a status, its template with that template's honest capability, and its render count |
| 5 | Open one content piece | Pass — lands on step 2 with a single focused workspace |
| 6 | Understand its assigned template | Pass — name, status, description, required inputs, output types, sizes |
| 7 | See whether the renderer works | Pass — Ready, Partial with what it actually produces, or a blocked panel naming the reason |
| 8 | Render if available | Pass — step 3 offers length and CTA timing for video, states plainly when there is nothing to configure, and disables the button with a reason when the template cannot render |
| 9 | Review the result | Pass — Review shows 5.5 overall with six category scores, why each was given, highest-impact improvements, and per-recommendation execution badges |
| 10 | Approve a revision | Pass — confirmation panel states what will be produced and that the original is not overwritten, before anything is queued |
| 11 | Execute the revision if supported | Pass — Revisions groups by state and disables the run button with a reason when nothing can run automatically |
| 12 | Approve the final version | Pass — one decision per version, saved to disk and read back; verified against the backup that only the intended records changed |
| 13 | Export it | Pass — Approved Only produced a 4-file, 3.2 MB package, and listed all five excluded versions with the reason for each |
| 14 | Download the package | Pass — download offered immediately, and earlier packages remain downloadable |

**Verification steps 12–14 were performed and then reverted.** One version was approved and one package built to prove the write paths, then `approvals.json` and `approval_summary.md` were restored from `.ux_sprint_backup/` and the test ZIP deleted. The campaign now reads exactly as found: 0 approved, 2 awaiting a decision, 0 export packages.

Empty, blocked, and error states were checked on every area — no campaign selected, no content, no renders, review unavailable before rendering, export unavailable before approval, missing API key, missing FFmpeg. Each names the condition and offers the button that resolves it.

---

## 11. Backend integrity

No CLI command, campaign file, content package, render version, approval record, review file, template assignment, revision request, or output path was changed in shape or location. All 12 existing tests pass. **No migration was required and none was performed.**

State files were snapshotted to `.ux_sprint_backup/` before implementation, since the repository has no commit history. Every write path in the interface goes through `ui/workflow_service.py`, which calls the same backend functions the CLI uses.
