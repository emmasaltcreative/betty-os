# BettyOS Experience 2 Audit

**Date:** 2026-08-03  
**Scope:** Live Streamlit product (`app.py`, `ui/`) against persisted campaign/Studio/review/export state.  
**Purpose:** Establish the current experience debt and the information architecture for the Guided Creative Operating System sprint — before implementation.

This audit changes no code. Prior audits (`UX_AUDIT.md`, `UX_CLEANUP_REPORT.md`, `STUDIO_IMPLEMENTATION_AUDIT.md`, `INTEGRATION_AUDIT.md`) describe earlier cleanups. This document describes **what users see today** after those cleanups, and why it still feels like a pipeline dashboard.

---

## 0. Verdict

BettyOS already has substantial working backend capability. The previous cleanup correctly collapsed eleven internal pages into a linear workflow and introduced a shared campaign state model (`ui/campaign_state.py`).

The remaining problem is structural, not stylistic:

- Pipeline stages are still **primary navigation destinations**.
- Home answers “what is the status of everything?” instead of “what should I do next?”
- Create, Studio, Review, Revisions, Approvals, and Export compete as separate apps.
- The user is still asked to configure, select, and route work that BettyOS can decide.
- Dual approval paths (Studio finish vs Approvals render) create false confidence that work is done.

**North star for this sprint:** hide machinery; one recommendation; one guided campaign workspace; five stable destinations.

---

## 1. Current visible navigation

Sidebar radio (`app.py` → `ui/nav.py` `NAV_ITEMS`):

| # | Label | Module | Primary-nav role today |
|---|-------|--------|------------------------|
| 1 | Home | `ui/screens/home.py` | Status dashboard |
| 2 | Campaigns | `ui/screens/campaigns.py` | Campaign list + create |
| 3 | Create | `ui/screens/create.py` | Content / template / render |
| 4 | Studio | `ui/screens/studio.py` | Automatic + advanced finishing |
| 5 | Review | `ui/screens/review.py` | Creative Director Review |
| 6 | Revisions | `ui/screens/review.py` (forced tab) | Same module, second step |
| 7 | Approvals | `ui/screens/approvals.py` | Render-version sign-off |
| 8 | Export | `ui/screens/export.py` | ZIP packaging |
| 9 | Library | `ui/screens/library.py` | Reference material |
| 10 | Settings | `ui/screens/settings.py` | Config + capability tables |

**Missing from primary nav (and from product):** Today (as a recommendation hero), Insights, Creative Journal, guided campaign workspace.

**Sidebar extras:** active campaign name, stage badge, progress bar. No brand-level Insights summary. Campaign shown is session `ACTIVE_CAMPAIGN` (good) — auto-defaults to newest folder on first load.

---

## 2. Every current page and tab

### 2.1 Home
- Progress rail: Brief → Content → Create → Studio → Review → Revise → Approve → Export (`ui/status.py` `WORKFLOW_STEPS`)
- Stat strip: Content pieces, Ready to render, Rendered, Needs revision, Awaiting approval, Approved
- “Next: {label}” + Continue Campaign
- Needs your attention (blockers + revision/approval tallies)
- Latest activity (last 6 technical events)

**Problem:** Dense status board. Multiple counters compete with the next action. Not conversational. Does not present one opportunity with why / what is needed / time / aftermath.

### 2.2 Campaigns
- Current campaign overview with goal, platforms, piece/render/approval counts, blockers, next action
- Other campaigns: Open / Archive
- Create Campaign expander: name, goal, production time, piece count, platforms, media folder path, index checkbox, notes
- Archived restore

**Problem:** Overview still exposes render counts and technical blockers. Opening a campaign goes to Home, not a guided workspace at the correct stage. Media folder is a raw path field.

### 2.3 Create — three steps
1. **Content** — piece cards with status badges, platform, objective, template, render counts, missing inputs; Open
2. **Template** — template selectbox (raw `template_id` values), needs/produces/sizes, renderer caveats, Save template, Continue to Render
3. **Render** — duration/CTA timing for video, Create render, batch “Render all ready pieces”, version history, Open in Studio

**Problem:** Pipeline stage as a destination. User chooses templates and timing BettyOS should choose. Stat counters on Content. Technical template status language.

### 2.4 Studio — single scroll + Advanced expander
- Source render version + output asset selectboxes
- Context panel (piece, goal, platform, template, finish IDs)
- Primary: Generate Best Edit
- Finished draft: before/after, finish_version_id, scores, key decisions, applied/not applied lists
- Inline Approve / Needs Revision / Reject on **finish versions**
- Finished versions panel with recipe IDs, Build Studio package
- Advanced: recipe, logo placement/size/opacity/timing, light, color, texture, crop, LUT, video, export settings

**Problem:** Correct Automatic Studio path exists, but Advanced is still prominent; IDs and scores leak; Studio approval is **not** the Export gate (misleading). No contextual logo-upload resume flow when a logo is required but missing.

### 2.5 Review — two sections
1. **Creative Review** — Run Creative Review; overall + six dimension scores; why-each-score expander; highest-impact improvements; Studio finished versions; recommendation cards with capability tallies; AI / Ready / Human panels
2. **Revisions** — five status counters; grouped revision requests with Retry / Apply / Review Options / etc.

**Problem:** Scorecard-first, not Creative Director language. Revisions is also a sidebar destination. Exposes recommendation/capability/revision request statuses. Global `latest_scores.json` (not per-campaign).

### 2.6 Approvals
- Stat strip: Render versions / Awaiting / Approved / Needs revision / Rejected
- Filter: show only awaiting
- Per-version decision radio + note + Save decision
- Links into Studio finishes

**Problem:** Correct Export authority, but feels like a queue dashboard. Competes with Studio’s Approve. Campaign-wide review score repeated on every card.

### 2.7 Export
- Stat strip + mode radio: Approved Only / Latest Versions / Selected Assets / Full Archive
- Plan preview (included / left out)
- Create Export Package + download + earlier packages

**Problem:** ZIP mode configuration in ordinary path. Archive mode exposes metadata intent. Should be “Download Publishing Package” by default.

### 2.8 Library — six tabs
Assets | Brand Assets | LUTs | Templates | Brand Guide | Production Rules

**Brand Assets:** upload (png/jpg/svg), display name, role, default, rename, archive, usage rules (min width, opacity, size %, safe margin).  
**Templates:** Ready/Partial/Planned/Manual Only + advanced planned-template form.  
**Assets:** indexed media search/filter with missing-from-disk counters.

**Problem:** Good home for reference, but Brand Setup completeness is not a first-class setup checklist. Usage rules ask for placement detail too early. Six tabs is heavy; LUTs should demote to Advanced Brand Setup. No “Brand Setup” completeness section as specified.

### 2.9 Settings
- Configuration (brand, API, FFmpeg, version, theme)
- Friendly file locations
- Capability Status tables (Working / Partial / Not Available) with evidence
- Advanced raw paths

**Problem:** Capability tables belong under Diagnostics, not the main Settings body. Otherwise aligned.

### 2.10 Insights
**Does not exist.** Learning data exists on disk (`approval_events.json`, `creative_preferences.json`, `performance_records.json`) but has no product surface.

---

## 3. Repeated controls and campaign selectors

| Pattern | Where | Notes |
|---------|-------|-------|
| Progress rail | Home, Create, Studio, Review, Approvals, Export | Repeats pipeline map everywhere |
| Stat strips | Home, Create, Review/Revisions, Approvals, Export, Library | Counter grids |
| Campaign gate empty states | Every workflow page | Correct pattern, but each page re-explains the pipeline |
| Piece / version selectboxes | Create, Studio, Approvals | User re-selects objects BettyOS already knows |
| Dual Approve / Needs Revision / Reject | Studio finishes **and** Approvals renders | Two authorities |
| Open in Studio / Go to Approvals / Continue | Scattered deep links | Compensates for fragmented IA |
| Active campaign | Session once (good) | No longer reselected per page — prior cleanup fixed this |

**Campaign selector duplication:** largely fixed by `ACTIVE_CAMPAIGN`. Remaining selection burden is content piece, render version, finish version, and export mode.

---

## 4. Status counters (inventory)

| Screen | Counters shown |
|--------|----------------|
| Home | 6 campaign stats + revision tallies in attention |
| Create Content | Pieces, Ready, Rendered, Missing inputs, Unsupported |
| Review Revisions | Awaiting decision, Ready to apply, Needs human, Failed, Applied |
| Approvals | Render versions, Awaiting, Approved, Needs revision, Rejected |
| Export | Approved, Awaiting, Render versions, Packages made |
| Library Assets | Indexed, Types, Missing from disk |
| Library Templates | Ready / Partial / Planned / Manual only |
| Settings | Working / Partial / Not available capability counts |
| Sidebar | Stage badge + progress fraction |

All of these violate the “one primary recommendation” rule when shown on Today/Home.

---

## 5. Raw technical details exposed

| Exposure | Locations |
|----------|-----------|
| `template_id` as select values | Create Template step |
| `finish_version_id`, `decision_id`, `draft_id`, `recipe_id` | Studio |
| `renderer_module` / status caveats | Create, Library Templates |
| File paths as select values / captions | Studio asset picker; Settings Advanced; missing-file messages |
| ISO timestamps | Studio finished versions |
| Score dimensions (0–10) | Review, Studio |
| Capability keys / evidence | Review recommendations, Settings |
| Revision request statuses (`proposed`, `options_ready`, …) | Review (mapped labels still pipeline-shaped) |
| ZIP mode internals / archive metadata | Export |
| JSON filenames | Settings Advanced, code comments in Review |
| Guardrail counts | Studio context |

---

## 6. Decisions the user makes that BettyOS could make

| User decision today | BettyOS should |
|---------------------|----------------|
| Which template to assign | Auto-assign best supported template; override only in Advanced Planning |
| Video duration / CTA timing | Choose from Production Rules + template defaults |
| Which render asset to finish | Auto-select latest relevant render |
| LUT / grain / exposure / logo placement | Automatic Studio Best Edit |
| Export mode (approved/latest/selected/archive) | Default to approved publishing package |
| Which recommendation to start from scorecard | Present one Creative Director judgment |
| Navigate Create → Studio → Review → Approvals → Export | Continue Campaign / Today resolver |
| Whether to open Revisions vs Review | Same Decide stage |
| Logo placement coordinates | Decide use / omit / blocked; upload only when missing |

---

## 7. Pages that are pipeline stages, not true destinations

Remove from primary navigation (keep as contextual stages):

| Nav item | Becomes |
|----------|---------|
| Create | Create stage inside campaign workspace |
| Studio | Substage of Create (Automatic Studio) |
| Review | Substage of Create / Decide (Creative Director Review) |
| Revisions | Substage of Decide |
| Approvals | Decision inside Decide |
| Export | Deliver stage |

True primary destinations after redesign: **Today, Campaigns, Library, Insights, Settings**.

---

## 8. Disabled, partial, or misleading actions

| Issue | Detail |
|-------|--------|
| Dual approval | Studio Approve does not unlock Export; Approvals does. User can believe work is approved when it is not exportable. |
| Implicit Send to Review | Studio Approve auto-calls `send_to_review()`; no labelled step. |
| Preview modes dead code | `PREVIEW_MODES` / `ZOOM_MODES` defined in Studio, never wired. |
| Save template / Save decision disabled when unchanged | Correct, easy to misread as broken. |
| Home Continue disabled when all pieces blocked | Only help-text on hover. |
| Global review scores | `outputs/latest_scores.json` can make the wrong campaign look reviewed. |
| Package fallback | `package_for_campaign()` may attach latest global package if `render_settings.json` missing. |
| Hardcoded CTA in render path | `copy_fields_for_piece` waitlist CTA not editable in Create. |
| Human revision dead end | Some revisions dismiss with “needs change to BettyOS itself.” |
| Revisions as duplicate nav | Same module as Review with forced tab — feels like two destinations. |
| Partial templates selectable | User can pick Partial and fail later. |

---

## 9. Backend functions that must remain accessible

All current `ui/workflow_service.py` and `ui/export_service.py` entry points remain required. Contextual UI may call them; nothing may be deleted.

### Campaign
`create_campaign_folder`, `archive_campaign`, `restore_campaign`, `run_plan_campaign`, `run_ingest_folder`, `run_repurpose_package`

### Create / render
`save_piece_template_override`, `copy_fields_for_piece`, `render_piece`, `render_ready_pieces`

### Studio (via `studio/service.py`)
`generate_best_edit`, `revise_best_edit`, `create_finish`, `set_finish_approval`, `send_to_review`, preview/draft helpers, brand asset upload APIs

### Review / revisions
`run_creative_review`, `persist_recommendation_status`, `dismiss_recommendation`, `classify_recommendations`, full revision lifecycle (`start_revision` … `apply_revision_request`), `revision_preview`

### Approvals / export
`save_version_decision`, `build_plan`, `create_export_package`, `list_existing_packages`

### Library / advanced
`register_planned_template`, brand asset / LUT CRUD, capability recording

### Read model
`build_campaign_state` and helpers in `ui/campaign_state.py` — extend, do not fork into a disagreeing second model.

---

## 10. Dependencies between Create, Studio, Review, Revisions, Approvals, Export

```
Campaigns (brief + package)
    → Create (assign template + render → render versions on disk)
        → Studio (Best Edit → finish_vNNN under render folder studio/)
            → Studio Approve → send_to_review → Review finished panel
        → Review Creative Review → latest_scores.json + recommendations
            → Revisions (revision_requests.json) → new render version
        → Approvals (approvals.json) ← Export gate for render versions
            → mirrors finish approval when ready_for_review
        → Export (ZIP of approved renders + approved finishes)
```

**Join keys that must survive consolidation:**
- Campaign folder name under `outputs/`
- Content package + assignments
- `RenderVersion` (template_id, piece_id, version)
- `parent_render_version_id` ↔ finish records
- `approvals.json` as Export authority (until explicitly unified)

**Learning side channel:** Studio finish approvals write brand `approval_events.json` → creative preferences → future Best Edit. Must keep writing even if UI moves.

---

## 11. Brand-asset and logo-upload functionality

**Library › Brand Assets** (`studio/brand_assets.py` + `library.py`):
- Upload SVG / PNG / JPG
- Display name, role, set default, rename, replace/archive, usage rules
- Roles cover primary/secondary/light/dark/emblem-style marks via `ROLE_LABELS`
- Paths stored under `brands/{brand}/studio/`; UI shows names (Advanced shows paths)

**Studio Advanced Logo:** pick role/asset/placement/size/opacity/timing.

**Gaps vs sprint:**
- No Brand Setup completeness checklist (Ready / Missing / Optional)
- No contextual “Add Logo → upload → resume interrupted Create” flow
- Automatic Studio decides logo use/omit, but missing-logo blocker is not a guided resume loop
- Usage rules appear during setup (too early)

---

## 12. Campaign-context persistence

| Concern | Mechanism | Persistence |
|---------|-----------|-------------|
| Active campaign | `st.session_state[ACTIVE_CAMPAIGN]` | Session only; defaults to newest |
| Selected piece | `SELECTED_PIECE` | Session |
| Nav / pending tab | `NAV`, `PENDING_NAV`, `PENDING_TAB` | Session |
| Studio editor draft | Studio session keys + optional disk draft | Mixed; refresh can lose unsaved advanced draft |
| Campaign artifacts | Disk under `outputs/{campaign}/` | Durable |
| Package link | `render_settings.json` → content_package name | Durable if present |
| Approvals / revisions / finishes | Disk | Durable |
| Brief form defaults | `campaign_goal`, `campaign_platforms` | Session defaults only |

**Gap:** Active campaign and interrupted workflow (e.g. logo upload return) are not written to a durable campaign context file. Restart recovers campaign via newest-folder default, not necessarily last-opened, and does not restore Studio selection / interrupted action.

---

## 13. Routing and query-parameter behavior

- No URL query parameters. No shareable deep links.
- Routing is session radio + `goto()` deferred pending nav/tab.
- Deep links assume current page names (`Create`, `Studio`, `Review`, `Approvals`, `Export`).
- `Revisions` is a fake page that forces Review’s second tab.
- Cross-page handoff keys: `studio_pending_version_key`, flash messages, `export_result`.

**Migration:** All `nav.goto("Create"|"Studio"|"Review"|"Revisions"|"Approvals"|"Export")` call sites must retarget the campaign workspace stage API. Keep internal stage keys stable.

---

## 14. Risks of consolidating pages

| Risk | Mitigation |
|------|------------|
| Dual approval desync | Keep Approvals as Export authority; Studio decide UI writes through `save_version_decision` (or explicit mirror) so one decision advances Deliver |
| `ready_for_review` gate hides draft finishes | Decide stage only presents finishes ready for judgment; Advanced shows drafts |
| Shared `studio/` per template folder | Always filter finishes by `parent_render_version_id` |
| Global `latest_scores.json` | Prefer campaign-scoped review when available; do not imply cross-campaign currency |
| Wrong package attachment | Prefer campaign-bound package; surface Blocked if unbound |
| Lost Studio session on refresh | Persist interrupted workflow context to disk |
| Deep link breakage | Compatibility map from old destinations → workspace stages |
| Legacy render folder twins | Keep `_render_folders()` dedupe; never delete legacy folders |
| Export ZIP structure expectations | Default Approved Only; Advanced Delivery Options retain modes |
| Test assumptions on page names | Update UI tests; keep backend tests untouched |

---

## 15. Migration requirements

**Do not rename or move:**
- `outputs/{campaign}/` trees
- `finish_vNNN/` layouts
- `approvals.json`, `revision_requests.json`, brand studio JSON
- template registry, assignments, render manifests
- learning files (`approval_events.json`, preferences, performance schemas)

**Allowed:**
- New read-only resolver module (`ui/today.py` / `ui/continue_campaign.py`) deriving from `CampaignState`
- New session + optional disk context for interrupted workflows
- New Creative Journal aggregator reading existing events (no parallel noisy log)
- Nav label changes and screen composition changes
- Status label remaps in `ui/status.py` (keep raw backend values)

**If a new campaign context file is introduced:**
1. Backup affected campaigns
2. Write migration report
3. Keep old identifiers resolvable
4. Default to deriving state when file absent (existing campaigns remain compatible)

**No data destruction.** No renderer rewrites. No new templates. No platform publishing.

---

## 16. Proposed information architecture

### Primary navigation (only)

1. **Today** — one recommendation
2. **Campaigns** — manage / reopen campaigns
3. **Library** — Assets, Brand Setup, Templates, Brand Guide, Production Rules
4. **Insights** — what BettyOS has learned
5. **Settings** — app/account configuration + Diagnostics

### Contextual (not primary nav)

Guided **Campaign Workspace** stages:

```
Brief → Plan → Capture → Create → Decide → Deliver
```

| Stage | Absorbs today’s pages |
|-------|----------------------|
| Brief | Campaign create / goal |
| Plan | Content package recommendation (was Create › Content + planning) |
| Capture | Shot list + footage upload (missing inputs / human revision assets) |
| Create | Render + Automatic Studio + Creative Director Review (auto) |
| Decide | Draft presentation, Needs Revision, Approve/Reject |
| Deliver | Export packaging |

Advanced / Diagnostics remain reachable from workspace header, Studio draft, Decide details, Deliver, and Settings.

---

## 17. Proposed guided workflow

```
BettyOS recommends (Today)
  → user provides required human input (Capture / Brief / logo)
  → BettyOS creates (Create: render + Best Edit + review)
  → BettyOS explains meaningful decisions (Decide)
  → user Approves / Requests Changes / Rejects
  → BettyOS continues
  → performance/approvals improve next recommendation (Insights)
```

**Continue Campaign resolver** (single source, extending `build_campaign_state`):

```json
{
  "campaign_id": "...",
  "current_stage": "draft_ready",
  "headline": "Your Reading Hour reel is ready.",
  "message": "...",
  "why": "...",
  "required_from_user": [],
  "primary_action": {"label": "Review Draft", "destination": "workspace", "context": {}},
  "secondary_actions": [],
  "blockers": [],
  "confidence": 0.91
}
```

Today states: `NO_ACTIVE_CAMPAIGN`, `CAMPAIGN_NEEDS_BRIEF`, `CONTENT_PLAN_READY`, `HUMAN_INPUT_REQUIRED`, `READY_TO_CREATE`, `PROCESSING`, `DRAFT_READY`, `REVISION_NEEDED`, `AWAITING_APPROVAL`, `READY_TO_EXPORT`, `BLOCKED`.

---

## 18. Terminology changes

| Internal / current UI | User-facing |
|-----------------------|-------------|
| Brand Brain | Brand Guide (already mostly done) |
| Production Brain | Production Rules |
| Review Brain / Creative Review scores | Creative Director Review |
| Content Package | Campaign Content |
| Render | Draft (user-facing); keep “render” internally |
| Finish Version | Finished Draft / Version |
| Revision Request | Requested Change |
| Template Registry | Template Library |
| Capability Status | What BettyOS Can Do (Diagnostics) |
| Home | Today |
| Generate Best Edit | Create Best Draft |
| Ready to Render | Ready to Create / Needs Footage as appropriate |

Technical IDs only in Advanced / Diagnostics / View Technical Details.

---

## 19. Screens to remove from primary navigation

- Create
- Studio
- Review
- Revisions
- Approvals
- Export

Also retire “Home” label in favor of **Today**.

---

## 20. Screens to merge

| Merge | Into |
|-------|------|
| Home | Today (recommendation engine, not dashboard) |
| Create + Studio + auto review | Campaign Workspace › Create |
| Review + Revisions + Approvals decision UI | Campaign Workspace › Decide |
| Export | Campaign Workspace › Deliver |
| Library Brand Assets + completeness | Library › Brand Setup |
| LUTs + advanced logo rules | Advanced Brand Setup |
| Settings capability tables | Settings › Diagnostics / What BettyOS Can Do |

---

## 21. Backend tools remaining only contextually

- Template override
- Manual render timing
- Advanced Studio finishing stack
- Raw Creative Review scorecard
- Full revision queue machinery
- Export modes beyond Approved Package
- Planned template registration
- Capability evidence
- Version metadata / manifests
- Studio package ZIP (non-publishing)

Accessible via Advanced / View Details / Diagnostics — collapsed by default.

---

## 22. Advanced / debug controls (hidden but available)

| Entry | Contents |
|-------|----------|
| Campaign → Advanced / Diagnostics | IDs, paths, raw stage, package binding |
| Create draft → Advanced Controls | Current Studio advanced stack |
| Decide → View Creative Review Details | Dimension scores, recommendation IDs |
| Decide → Version History | Full finish/render history |
| Deliver → Advanced Delivery Options | Latest / Selected / Archive modes |
| Settings → Diagnostics | Paths, capability evidence, FFmpeg detail |
| Library → Advanced Brand Asset Rules | Placement opacity/size rules |
| Library → Advanced Planning | Template override / planned templates |

---

## 23. Creative Journal (new, lightweight)

Aggregator over existing durable events — not a second write path for every technical step:

Sources: approval decisions, revision outcomes, Studio edit decisions (meaningful only), export completion, creative preference promotions.

Shown in campaign workspace; optional 1–3 line summary on Today.

---

## 24. Implementation sequence (for the sprint)

1. Ship this audit (done when committed with the sprint).
2. Introduce Continue Campaign / Today resolver on top of `CampaignState` (no second conflicting model).
3. Reduce `NAV_ITEMS` to five; route old destinations into workspace stages.
4. Build Campaign Workspace shell (header + Brief→Deliver progression).
5. Rebuild Today as single recommendation.
6. Rewrite Plan / Capture / Create / Decide / Deliver experiences using existing services.
7. Add Library Brand Setup completeness + contextual logo resume.
8. Add Insights from learning JSON; Creative Journal aggregator.
9. Hide technical machinery; remap status language.
10. Tests for nav, resolver, persistence, flows, journal; run full suite.
11. End-to-end acceptance walkthrough against criteria §36–37 of the sprint brief.

---

## 25. Design acceptance criteria (checklist)

- [x] Primary nav: Today, Campaigns, Library, Insights, Settings only
- [x] Today: one clear recommendation (why, need, time, aftermath, one CTA)
- [x] Active campaign: one guided workspace
- [x] Studio / Review / Revisions / Approvals / Export not top-level
- [x] Those capabilities still function contextually (Advanced / Diagnostics)
- [x] One visually dominant primary action per main screen (Today + workspace stages)
- [x] No loss of historical versions, approvals, exports, learning records
- [x] Advanced controls remain accessible but collapsed
- [x] Existing campaigns open and continue correctly after restart (workspace context file)

---

*End of audit. Implementation begins from §16–24.*
