# BettyOS UX Audit

**Date:** 2026-07-28
**Scope:** Streamlit interface (`app.py`, `ui/`) audited against the backend it drives (`main.py`, `renderers/`, `review/`, `src/`).
**Purpose:** Establish what exists, what duplicates, what misleads, and what the information architecture should become — before any code changes.

This audit changes no code. It is the input to the cleanup sprint.

---

## 1. Current page inventory

The sidebar exposes 11 pages. None of them are named for a step in the user's actual workflow.

| # | Page | Intended job | Job clear? | Primary action | Verdict |
|---|------|--------------|-----------|----------------|---------|
| 1 | Dashboard | Campaign status at a glance | No — it is an action launcher, not a status page | Ambiguous: 8 competing buttons | **Merge → Home** |
| 2 | New Campaign | Brief intake + session plan | Partly — "campaign" here means a *plan file*, not a campaign folder | Create campaign plan | **Merge → Campaigns** |
| 3 | Content Package | Read the package + assign templates | No — two unrelated jobs on one page | Unclear (read? assign?) | **Merge → Create, Step 1 + 2** |
| 4 | Templates | Browse template registry | Yes, but it is reference material placed in the workflow | Browse | **Move → Library** |
| 5 | Template Builder | Register a new planned template | Yes, but it is an authoring tool for a developer, not a daily user | Save definition | **Demote → Library (advanced)** |
| 6 | Renders | Render, preview, compare versions, approve | No — this page does four jobs | Ambiguous: 4+ competing actions | **Split → Create + Approvals** |
| 7 | Creative Review | Critique pass + recommendation decisions | Mostly yes | Run review | **Keep → Review** |
| 8 | Revision Queue | Execute approved recommendations | Partly — the page describes itself as a JSON control surface | Execute revisions | **Merge → Review (Revisions tab)** |
| 9 | Approvals | Final asset decisions | Yes, but competes with two other approval surfaces | Save approvals | **Keep → Approvals** |
| 10 | Brand Brain | Read brand guidance | Yes, but the name is an internal code name | Read | **Rename + move → Library / Brand Guide** |
| 11 | Settings | Environment readiness | Yes | None (read-only) | **Keep → Settings** |

**Missing entirely:** there is no Campaigns list, no Export step, and no Library. The workflow dead-ends after Approvals — an approved asset cannot be packaged or downloaded anywhere in the product.

---

## 2. Full control inventory

### 2.1 Dashboard — 8 buttons, 4 metrics

| Control | Type | Real action? | Feedback? |
|---|---|---|---|
| Start New Campaign | button | Navigation only | n/a |
| Generate Content Package | button | Yes (Anthropic call) | Spinner + success |
| Render Supported Pieces | button | Yes (`run_create_all`) | Spinner + success |
| Open Renders | button | Navigation only | n/a |
| Run Creative Review | button | Yes (Anthropic call) | Spinner + success |
| Open Creative Review | button | Navigation only | n/a |
| Open Revision Queue | button | Navigation only | n/a |
| Open Templates | button | Navigation only | n/a |

Metrics shown: Brand, Indexed assets, Rendered pieces, Readiness.

**Problems.** Four of eight buttons only duplicate the sidebar. The metrics answer none of the four questions a home page must answer — there is no campaign stage, no count of what needs attention, no next step. "Readiness" is a review score from `latest_scores.json` presented as if it were campaign progress. A static "Review → revision path" numbered list at the bottom is documentation compensating for unclear IA.

### 2.2 New Campaign — 1 form

Fields: campaign name, goal, available production time, platforms, notes, asset folder path, "index assets" checkbox. Submit runs asset ingest then an Anthropic planning call.

**Problems.** "Campaign name" is written into session state and prepended into plan notes as free text — it never becomes a campaign identity. The real campaign identity is the `outputs/*_campaign/` folder created later by rendering. So a user can "create a campaign" and then find no campaign exists. Asset folder path is a raw filesystem text field.

### 2.3 Content Package — 1 selectbox + N×(1 selectbox + 1 button)

**Problems.**
- `show_save_state("saved", …)` renders a green **Saved** badge on page load, before the user has saved anything (`app.py:319`). This is a false success signal.
- Dead code: `assignments = {pid: assignments[pid] for pid in assignments}` (`app.py:314-317`) is a no-op copy.
- Exposes `Confidence`, `Rationale`, `Alternatives`, and the filename `…assignments.json` — internal classifier output presented as user-facing content.
- Section is titled "Template classification" and captioned "Each content piece gets one canonical `template_id`".

### 2.4 Templates — 3 filter selectboxes + N buttons

**Problems.**
- "View Template" reads the button's own return value out of session state (`ui/template_pages.py:103`), so the raw registry JSON appears for exactly one rerun and then vanishes. The button has no coherent state.
- Renderer internals surfaced verbatim: `Renderer: {renderer_family} / {renderer_module}`.
- Filter values are raw enum strings (`multi_frame`, `manual_only`).
- **Most serious:** the page reports `renderer_status` from the registry as truth. That status is wrong for many templates (see §5).

### 2.5 Template Builder — 1 form

Asks the user for `template_id (snake_case)`, `Renderer family` (`VideoRenderer`/`StaticRenderer`/…), comma-separated input lists. Writes a `planned` registry entry, then dumps the saved record as raw JSON.

**Problems.** This is a developer authoring tool sitting at the same level as the daily workflow. It creates registry rows that can never render, and the resulting `planned` templates then appear in the per-piece template picker on Content Package as selectable options.

### 2.6 Renders — the worst offender: 5 global buttons + N×4 per-piece buttons + N×(3 selectboxes + radio + input + button)

Global: campaign folder selectbox, "Render all supported pieces", "Render Ritual Reel (legacy)", "Render Page Turn Loop (legacy)", "Migrate legacy folders".

Then Template Coverage, which renders a **disabled** `Create Template · Planned` button once per supported template *and* once per unsupported piece.

Then "Render by assigned template", per piece: approval note input, **Render**, **Approve**, **Needs Revision**, **Reject**.

Then "Existing campaign outputs", per folder: asset preview with a raw-JSON "Render details" expander, a 2-selectbox version comparer, a "Version to review" selectbox, a Decision radio, a Note input, and "Save version decision".

**Problems.**
- Four jobs on one page: rendering, template coverage reporting, final approval, version review.
- The word "legacy" is in two button labels. "Migrate legacy folders" exposes a one-time data migration as a routine user action.
- Per-piece Approve / Needs Revision / Reject hardcode `render_version_id="v1"` (`app.py:533`, `550`, `567`) regardless of which version actually exists. On a campaign that already has v2, these write incorrect version metadata.
- Per-piece **Render** is enabled whenever template status is `ready` *or* `partial` (`app.py:501`). Four `partial` video templates always raise on render (see §5). The button looks actionable and can only fail.
- "Save version decision" writes to `versions.json` **and** `approvals.json` (`app.py:643-658`), making this the third place final approval can be set.
- `show_save_state("saved", …)` again renders on load (`app.py:466`).

### 2.7 Creative Review — 2 selectboxes + 1 button + N×(textarea + 2 buttons + confirm/cancel) + 2 nav buttons

**Problems.**
- Two more selectboxes (content package, campaign) that do not share state with any other page.
- Raw scores JSON behind a "View source data" expander.
- The confirmation panel reports `Overwrites original: False` and `Copy changes: None` — literal Python values rendered as UI copy.
- Two navigation-only buttons at the bottom duplicating the sidebar.
- The Approve/Dismiss decision is about *revision instructions*, but nothing on the page distinguishes that from final asset approval.

### 2.8 Revision Queue — 1 selectbox + 4 metrics + 1 execute button + 1 nav button

**Problems.**
- Page caption states: *"This page is the visual control surface for `revision_requests.json`"* (`app.py:843`). The product describes itself in terms of its own storage file.
- `show_revision_queue` always renders all six status buckets, printing "None" under each empty one.
- The page then repeats "Ready for review" and "Manual Completion Required" as separate sections below, restating what the buckets already showed.
- Button label "Execute awaiting **Ritual Reel** revisions" leaks an internal template name and silently reveals the real constraint: execution only works for one folder.

### 2.9 Approvals — 1 selectbox + N×(selectbox + textarea) + 1 button

**Problems.**
- Approval items are **per file**, not per render version. Live data from `outputs/2026-07-27_191825_campaign/approvals.json` shows six separate approval rows for one reel:

  ```
  ritual_reel/caption.md              needs_revision  v1  caption
  ritual_reel/ritual_reel_draft.mp4   needs_revision  v1  video
  ritual_reel/ritual_reel_v1.mp4      needs_revision  v1  video
  ritual_reel/ritual_reel_v2.mp4      needs_revision  v2  video
  page_turn_loop/caption.md           needs_revision  v1  caption
  page_turn_loop/page_turn_loop_draft.mp4  needs_revision v1 video
  ```

  The draft and v1 are both labelled `v1`, so one asset occupies two rows at the same version. This is precisely the "caption.md, MP4, and metadata as different approval items" problem.
- "Included files" expander prints raw relative paths.
- "Saved file summary" expander prints raw JSON.
- Save has no timestamp, no per-item confirmation, and no reload-verify visible to the user.

### 2.10 Brand Brain — tabs of raw markdown. No actions. Name is an internal code name.

### 2.11 Settings — read-only card printing absolute filesystem paths in monospace. No capability information.

### 2.12 Sidebar

`st.radio` over 11 page names, brand name caption, latest campaign folder name caption, a conditional revision count caption, and the line "Studio is the primary workflow surface." The campaign shown in the sidebar is always `find_latest_campaign_dir()` — it is **not** the campaign the user selected on any page, so the sidebar and the page body can disagree.

---

## 3. Redundancies found

### 3.1 Repeated campaign selectors — 4 independent copies

Renders (`renders_campaign_select`), Creative Review (unkeyed), Revision Queue (`revision_queue_campaign`), Approvals (unkeyed). None share state. The sidebar shows a fifth, different value (always the newest folder). A user moving Create → Review → Approvals must reselect the campaign three times and has no guarantee the sidebar agrees.

### 3.2 Repeated content-package selectors — 2 copies

Content Package and Creative Review. Renders infers the package a third way, by reading `content_package` out of `render_settings.json`.

### 3.3 Duplicate render triggers — 5 entry points

Dashboard "Render Supported Pieces"; Renders "Render all supported pieces" (identical call); Renders "Render Ritual Reel (legacy)"; Renders "Render Page Turn Loop (legacy)"; Renders per-piece "Render".

### 3.4 Duplicate approval controls — 3 surfaces, 2 schemas

1. Renders per-piece Approve / Needs Revision / Reject → `upsert_approval` with hardcoded `v1`.
2. Renders "Save version decision" → `set_version_review_status` **and** `upsert_approval`.
3. Approvals page "Save approvals" → `write_approvals` rebuilt from **discovered files only**.

Surface 3 rebuilds the entire `items` array from files found on disk (`ui/workflow_service.py:267-288`). Any record written by surface 1 whose `file_path` is not discovered as a campaign file is **silently dropped**. Three write paths, one unlocked file, last writer wins.

### 3.5 Repeated review summaries — 2 places

Dashboard "Readiness" metric and Creative Review overall score read the same `latest_scores.json`.

### 3.6 Repeated revision-queue counts — 3 places

Sidebar caption, Dashboard right-hand card, Revision Queue metrics.

### 3.7 Repeated template lists — 3 places

Templates page, the per-piece template picker on Content Package, and the template grouping headers on Renders.

### 3.8 Repeated content-piece information — 3 places

Content Package expander (platform, objective, format, hook, caption, CTA, notes), Renders per-piece expander (title, template, platform, source assets), Approvals group (title, caption). The user must locate the same piece in three places to move it one step forward.

### 3.9 Navigation-only buttons — 7

Dashboard ×4, Creative Review ×2, Revision Queue ×1. All duplicate the sidebar without adding routing intelligence.

### 3.10 Duplicated data on disk producing duplicated UI

`src/templates/migration.py` **copies** legacy folders to canonical names rather than moving them. Live campaigns therefore contain both:

```
outputs/2026-07-27_191825_campaign/
  ritual_reel/                    ← legacy, still populated
  cinematic_multi_clip_reel/      ← canonical copy of the same files
  page_turn_loop/                 ← legacy
  single_clip_atmospheric_loop/   ← canonical copy
```

Renders lists both folders, so the *same video appears twice under two different names*. Approvals does the same. This is a data-shaped redundancy the UI faithfully reproduces.

---

## 4. Confusing flows

**No workflow spine.** The product is Campaign → Content → Create → Review → Revise → Approve → Export. The sidebar order is Dashboard, New Campaign, Content Package, Templates, Template Builder, Renders, Creative Review, Revision Queue, Approvals, Brand Brain, Settings. Nothing tells the user where they are or what comes next.

**"Campaign" means three different things.** A session/plan pair (`*_session.json`, `*_plan.md`) created by New Campaign; an `outputs/*_campaign/` render folder created by rendering; and a `campaign` string field inside `revision_requests.json`. The user is asked to select "campaign" from the third meaning while having created the first.

**A content piece must be found three times** to get from idea to render: on Content Package (to assign a template), on Renders (to render it), on Approvals (to approve it). Each page identifies it differently — by title, by title under a template header, by folder name.

**Two kinds of approval are never distinguished.** "Approve Revision" on Creative Review approves an *instruction*. "Approve" on Renders and Approvals approves a *finished asset*. Both are green buttons labelled Approve.

**The workflow dead-ends.** After approving, there is nothing to do. No export, no download, no package. The last step of the product does not exist.

**Revision execution silently covers one case.** `execute_ritual_revisions` requires `{campaign}/ritual_reel/` to exist and filters for `affected_asset == "Ritual Reel"` (`review/revision_execute.py:44-45`, `221`). Clip removal is hardcoded to drop `IMG_2549.mov` and keep `IMG_2545`/`IMG_2547` (`review/revision_execute.py:67-75`); rerender is hardcoded to a two-clip 15-second rebuild (`:77-90`); CTA timing is hardcoded to 10.0s (`:92-100`). Nothing in the UI says that a revision to a static pin, a carousel, a copy asset, or the Page Turn Loop can never run automatically.

---

## 5. Honesty gaps — where the UI over-promises

The registry's `renderer_status` is treated as truth by the UI. It is not. Evidence from the renderer modules:

| Registry claim | Reality | Evidence |
|---|---|---|
| `product_detail_reel`, `narrative_text_reel`, `contrast_reel`, `slideshow_reel` = **partial** | **Always raise.** `dispatch.py` allows `partial` through (`dispatch.py:31-39`), then `video.py` rejects any video template outside its two implemented IDs (`video.py:47-51`). The Render button is enabled and can only fail. | `dispatch.py:31-39`, `video.py:47-51` |
| `single_clip_atmospheric_loop` = **ready** | Validates the user's `source_assets`, then **ignores them** and renders a hardcoded clip (`PAGE_TURN_SOURCE`). | `video.py:61-66` then `video.py:153`, `main.py:1124-1128` |
| `editorial_carousel`, `product_detail_carousel`, `story_sequence` = **ready** | All four carousel templates run the identical generic 3-slide loop with hardcoded headline text. `slide_copy_set` is never read. Only the aspect ratio differs. | `carousel.py:59-74` |
| `editorial_static_pin`, `product_feature_pin`, `pinterest_collage_pin`, `waitlist_announcement`, `product_reveal`, `bundle_overview` = **ready** | One generic canvas with three text-placement variants. Registry input names (`quote_text`, `product_name`, `bundle_items`, `launch_date_text`) are never read; the code reads `headline`/`hook_text`/`title`/`cta_text` and falls back to the literals `"The Reading Hour"` / `"Join the waitlist"`. | `static.py:90-113`, `static.py:94-109` |
| `founder_note` = **partial** | Fully wired — identical implementation to `email_letter`, which is marked `ready`. The registry *under*-rates this one. | `copy.py:44-51` |
| `cinematic_multi_clip_reel` = **ready** | Genuinely implemented. Requires ffmpeg, a content package, and source clips inside the project root. | `video.py:82-148` |

Only **one** template (`cinematic_multi_clip_reel`) is fully and faithfully implemented. Four are guaranteed failures with an enabled button. Roughly twenty produce generic placeholder output while the UI reports "ready".

Other honesty gaps:

- **False "Saved" badges** on page load, before any save (`app.py:319`, `app.py:466`).
- **Review markdown and scores are not written atomically** and are never read back (`review/review_engine.py:263-278`), unlike approvals and assignments which do verify. The user gets identical success messaging for both.
- **No file locking anywhere.** Three approval write paths race on one file.
- **Capability is undiscoverable.** Nothing in the product tells the user what works, what half-works, and what is only registered.

---

## 6. Technical detail exposed unnecessarily

Internal code names in visible UI: **Brand Brain**, **Production Brain**, **Review Brain**, **Revision Queue**, **Content Package**, **Template Registry**, **Template Builder**.

Raw identifiers and schema names in visible UI: `template_id`, `renderer_status`, `renderer_module`, `renderer_family`, `piece_id`, `revision_requests.json`, `latest_scores.json`, `*.assignments.json`, `versions.json`, `render_settings.json`, `multi_frame`, `manual_only`, `awaiting_execution`, `manual_completion_required`.

Raw data presentation: five `st.json` call sites, absolute filesystem paths in Settings, per-asset path lists in three places, and `traceback.format_exc()` behind a "Diagnostics" expander on every failure.

The word "legacy" appears in two button labels.

---

## 7. Status vocabulary is inconsistent

Five separate, overlapping status vocabularies exist, each with its own labels and its own visual treatment:

| Source | Values |
|---|---|
| `ui/components.py:22` `STATUS_LABELS` | approved, needs_revision, rejected, awaiting_review |
| `ui/components.py:29` `REC_STATUS_LABELS` | proposed, approved, dismissed, in_progress, completed, failed |
| `review/revision_queue.py:31` `QUEUE_LABELS` | awaiting_execution, in_progress, ready_for_review, completed, failed, manual_completion_required |
| `review/coverage.py:14` `COVERAGE_STATUSES` | ready_to_render, template_needed, missing_source_asset, invalid_configuration |
| `ui/template_pages.py:12` `SAVE_STATE_LABELS` | saved, unsaved_changes, saving, save_failed |

"Approved" means three different things depending on which list it came from. Every one of them renders through the same undifferentiated `betty-pill` CSS class, so a blocking failure and a successful save look identical.

---

## 8. Empty, loading, error, and success states

| State | Current coverage |
|---|---|
| Empty | `empty_state()` used on 6 of 11 pages. Renders, Revision Queue, and Settings have none. Templates prints nothing when a filter matches zero rows. |
| Loading | `st.spinner` on long calls only. No skeletons, no disabled-while-running. |
| Success | `st.success(message)` plus an optional saved-path caption. No timestamps. |
| Error | `st.error(message)` plus a raw traceback expander. |
| Blocked | **Does not exist.** A partial video template that cannot render, a review that needs renders, an export with nothing approved — all render as ordinary enabled UI. |

---

## 9. Proposed information architecture

Eight areas, matching the workflow spine.

| Area | Job | Primary action | Absorbs |
|---|---|---|---|
| **Home** | Where am I, what needs attention, what next | **Continue Campaign** | Dashboard |
| **Campaigns** | Manage campaigns; open one | Open Campaign | Dashboard cards, New Campaign |
| **Create** | Content → Template → Render, one workspace per piece | Render | Content Package, Renders, Templates (picker) |
| **Review** | Creative critique + revision decisions | Run Creative Review | Creative Review, Revision Queue |
| **Approvals** | The only final asset decision | Approve | Renders (approval controls) |
| **Export** | Package approved work | Create Export Package | *new — did not exist* |
| **Library** | Reference: Assets, Templates, Brand Guide, Production Rules | Browse | Templates, Template Builder, Brand Brain |
| **Settings** | Environment + honest capability status | None | Settings |

**Progress rail** on every page: Brief → Content → Create → Review → Revise → Approve → Export, showing completed / current / blocked / next.

**One active campaign** held in session state, set on Campaigns, displayed in the sidebar, and read by every page. No page-level campaign selectors.

### Pages removed or merged

| Page | Disposition |
|---|---|
| Dashboard | Replaced by Home |
| New Campaign | Becomes the "Create Campaign" form inside Campaigns |
| Content Package | Becomes Create → Step 1 (Content) |
| Templates | Becomes Library → Templates |
| Template Builder | Becomes a collapsed advanced block inside Library → Templates |
| Renders | Split: rendering → Create; approval → Approvals; version compare → Approvals |
| Creative Review | Becomes Review → Creative Review |
| Revision Queue | Becomes Review → Revisions |
| Brand Brain | Becomes Library → Brand Guide |

Net: 11 pages → 8 areas, with Export added.

### Terminology changes

| Internal (code, unchanged) | Visible label |
|---|---|
| Brand Brain | Brand Guide |
| Production Brain | Production Rules |
| Review Brain | Creative Review |
| Revision Queue | Revisions |
| Template Registry | Templates |
| Content Package | Campaign Content |
| `renderer_status` | Template status badge |
| `awaiting_execution` | Ready to Run |
| `manual_completion_required` | Manual Work Required |
| `ready_for_review` | Awaiting Approval |
| `multi_frame` | Multi-Frame |
| `manual_only` | Manual Only |

### Unified status system

Four vocabularies, one visual treatment, used everywhere:

- **Campaign:** Planning · Creating · Reviewing · Revising · Awaiting Approval · Approved · Exported · Blocked
- **Content piece:** Draft · Ready to Render · Missing Inputs · Rendering · Rendered · Needs Revision · Awaiting Approval · Approved · Rejected · Unsupported
- **Template:** Ready · Partial · Planned · Manual Only
- **Action:** Saving · Saved · Failed · Running · Complete · Blocked

---

## 10. Risk areas

**Approval data loss (highest risk).** `save_grouped_approvals` rebuilds `items` from discovered files, dropping records for undiscovered paths (`ui/workflow_service.py:267-288`). Consolidating to one approval surface must keep writing per-file records through the existing `upsert_approval` / `write_campaign_approvals` path so the CLI `approve` command and existing `approvals.json` files keep working. **Mitigation:** group at the presentation layer only; never change the on-disk schema.

**Legacy/canonical folder duplication.** Hiding the legacy twin is a display decision. The files must stay on disk — `execute_ritual_revisions` depends on `{campaign}/ritual_reel/` existing (`review/revision_execute.py:44-45`), and `find_latest_render_dirs` looks for `ritual_reel` and `page_turn_loop` by name (`src/common.py:86`). **Deleting legacy folders would break revision execution and review context.** Display-only deduplication; no file moves.

**Version identity.** Versioned files inside canonical folders carry the *legacy* prefix (`cinematic_multi_clip_reel/ritual_reel_v2.mp4`) because migration copied them. Version detection must parse `_v(\d+)` from any media filename, not assume `{folder}_v{N}`.

**Template registry is data.** Its `renderer_status` values are wrong for ~20 templates, but rewriting them is a data migration. **Mitigation:** add a UI-level capability layer that shows the registry status *plus* an honest caveat, and gate the Render button on real renderability rather than registry status. No registry edits.

**Disabling buttons changes behaviour.** Correctly disabling Render for the four always-failing video templates removes an action a user could previously click. It could only ever produce an error, so this is a fix — but it must be labelled with the reason, not silently greyed out.

**Export is genuinely new.** No ZIP or packaging code exists anywhere. Building it adds `outputs/exports/`. It reads approved renders and writes a new archive; it modifies no existing artifact. Treated as completing the required IA, not as a new renderer capability.

**No migration required.** Every existing file keeps its schema and location: `approvals.json`, `versions.json`, `*.assignments.json`, `revision_requests.json`, `latest_scores.json`, `latest_review.md`, `render_settings.json`, campaign folders, CLI commands. The only additive path is `outputs/exports/`.

**Test baseline:** 12 tests pass before changes (`tests/test_persistence.py`, `tests/test_templates_acceptance.py`). They cover piece parsing, template assignment, static/copy/carousel rendering, approval round-trip, and migration. All must still pass.

**Version control:** the repository has no commits — every file is untracked. There is no rollback point. A backup of mutable state should be taken before implementation.
