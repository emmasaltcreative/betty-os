# Campaign Intelligence Audit

**Date:** 2026-08-04  
**Scope:** Existing BettyOS campaign, planning, package, and learning architecture before adding Campaign Intelligence and Production Briefs.  
**Constraint:** Extend the existing campaign workflow. Do not create a second campaign system.

---

## 0. Verdict

BettyOS already has a working guided campaign path (Brief → Plan → Capture → Create → Decide → Deliver), filesystem-backed campaign folders, content packages, shot guidance derived from missing assets, Brand Guide, Production Rules, publishing ZIPs, and a learning schema foundation.

What it lacks for proactive campaign intelligence is **structured planning context**: objectives as data, milestones and commerce calendar, lead-time rules, portfolio recommendations, content runway, and a concise Production Brief PDF with reliable download UX.

Persistence is filesystem JSON/Markdown under `outputs/`, `brands/`, `production/`, and `library/` — not a database. Intelligence must attach to existing campaign folders.

---

## 1. What already exists

| Area | Location | Notes |
|------|----------|-------|
| Campaign identity | `outputs/{stamp}_campaign/` | Folder is the campaign; no Pydantic Campaign entity |
| Campaign state | `ui/campaign_state.py` | Derived `CampaignState`: goal, pieces, stage, blockers |
| Continuation resolver | `ui/continue_campaign.py` | Today / workspace next action |
| Guided workspace | `ui/screens/workspace.py` | Brief → Deliver stages |
| Campaign list/create | `ui/screens/campaigns.py` | Goal, platforms, time available, piece count |
| Content pieces | `src/templates/models.py`, `pieces.py` | Parsed from content package markdown |
| Content package | `main.py` / `*_content_package.md` | Goal, platforms, pieces, rhythm as prose |
| Production plan | `*_plan.md` | LLM shot list; not wired as Capture checklist |
| Capture shots | `continue_campaign._shot_list_for`, workspace | Missing-asset derived |
| Brand Guide | `brands/oh_betty_jaletti/*.md` | Identity, audience, products, voice, strategy |
| Production Rules | `production/*.json`, `style_guide.md` | Render/pacing/typography — not strategy lead times |
| Asset library | `library/assets.json` | Indexed media with quality/uses |
| Publishing packages | `ui/export_service.py` | ZIP under `outputs/exports/` |
| Downloads | Streamlit `st.download_button` with file bytes | ZIP only; no PDF; no Finder reveal |
| Approvals / revisions | Campaign `approvals.json`, `revisions/` | Immutable revision history |
| Performance learning | `studio/learning.py` | Schema present; no live platform ingest |
| Atomic persistence | `src/persistence.py` | `atomic_write_json` / `atomic_write_text` |
| Timestamps | `src/common.py` `timestamp_stamp()` | File naming; ISO on sessions |

---

## 2. What is missing

| Required capability | Status |
|---------------------|--------|
| Business objective as structured field | Missing (goal is free text / package markdown) |
| Milestone / launch / inventory / shipping dates | Missing as data |
| Filming availability & duration as planning inputs | Partial (create form time selectbox only) |
| Commerce / opportunity calendar | Missing |
| Brand-relevant vs excluded holidays | Missing |
| Configurable lead-time rules | Missing (not in Production Rules) |
| Work-back start-by dates | Missing |
| Opportunity / deadline / risk alerts | Missing |
| Supporting campaign portfolio recommendations | Missing |
| Combined production session planning | Missing as structured data |
| Deliverable ranges & content runway | Missing (effort ≈ `3+2n` minutes only) |
| Posting cadence recommendations | Prose only in packages |
| Pre-shoot / post-capture estimate history | Missing |
| Concise Production Brief PDF | Missing |
| Production Brief History (not Package History) | Missing |
| Show in Finder | Missing |
| Strategy settings (buffers, cadence defaults) | Missing |
| Estimate-vs-actual learning records | Missing |
| Honest evidence labels (assumption vs forecast) | Partial in Insights; not in planning |

---

## 3. What to add to existing models (not duplicate)

Attach to the **existing campaign folder**:

| File | Purpose |
|------|---------|
| `{campaign}/intelligence.json` | Objectives, milestones, inputs, portfolio decisions, alerts snapshot |
| `{campaign}/estimates.json` | Pre-shoot / post-capture / final runway and deliverable estimates |
| `{campaign}/production_briefs/` | Generated PDF (+ optional CSV) with index |
| `{campaign}/production_briefs/index.json` | Newest + history metadata |
| `{campaign}/learning_outcomes.json` | Estimated vs actual operational outcomes |

Global / brand config (do not scatter in UI):

| File | Purpose |
|------|---------|
| `production/strategy_rules.json` | Lead times, buffers, cadence defaults, capacity |
| `brands/<id>/calendar_rules.json` | Included/excluded events, brand relevance weights |

Do **not** duplicate:

- Campaign folders or a parallel “intelligence campaign” entity
- Content piece parsing / assignments
- Publishing Package / export ZIP pipeline
- Studio finishes, approvals, revisions
- Brand Guide markdown pack
- Continue Campaign state machine (extend Today presentation only)

---

## 4. Current planning assumptions

1. One active campaign at a time (sidebar).
2. “Plan” means content pieces exist in a package — not a strategic portfolio.
3. Accept Plan advances workflow; no persisted plan-decision record.
4. Brief goal in workspace is session-scoped unless baked into a new package.
5. Package↔campaign link is weak (`render_settings` or latest package).
6. Capture shot list ≈ missing source assets, not combined multi-campaign shoot plan.
7. Effort estimate is linear minutes from missing-input count.
8. Performance forecasts are not connected; Insights says so honestly.
9. Default brand is Oh Betty Jaletti; inventory is waitlist-only per Brand Guide.

---

## 5. Current date handling

- Filesystem stamps: `%Y-%m-%d_%H%M%S`
- ISO timestamps on sessions, approvals, workspace context
- Display: `%-d %b %Y, %H:%M`
- Today greeting by hour-of-day
- **No** holiday calendar, floating-date engine, lead-time offsets, or timezone-aware planning display for milestones

---

## 6. Package and download utilities

| Utility | Path | Role |
|---------|------|------|
| `create_export_package` | `ui/export_service.py` | Publishing / archive ZIP |
| `list_existing_packages` | same | Package History expander |
| `st.download_button` + `Path.read_bytes()` | workspace Deliver | Correct pattern to reuse for briefs |
| Studio ZIP | `studio/package.py` | Finish packages |

Gaps for Production Brief:

- No PDF generator
- No guaranteed “generate then enable Download” success state for briefs
- Newest deliverable buried in Package History pattern (must not reuse that UX for briefs)
- No macOS Finder reveal helper

---

## 7. Persistence requirements

- Use `atomic_write_json` / `atomic_write_text` for all intelligence writes
- Store brief PDF bytes on disk under the campaign folder before offering Download
- Index newest brief path so it survives Streamlit reruns and process restarts
- Keep intelligence optional: campaigns without `intelligence.json` must still resolve stages and export packages
- Prefer additive fields with defaults; dual-read where older campaigns lack new files

---

## 8. Migration risks

1. Changing `WORKSPACE_STAGES` labels/order can break Experience 2 nav tests — add Production Brief as success state / document, not a permanent top-level stage.
2. Altering `build_campaign_state` stage completion rules risks `test_experience_2.py` and continuation tests.
3. Touching export ZIP naming / Package History risks `test_publishing_package.py`.
4. Markdown piece heading fragility — intelligence must not depend on re-parsing packages differently.
5. Learning dual-compat shapes in `studio/learning.py` — keep campaign operational learning separate under campaign folders.
6. Session-only brief goal today — migrating to durable intelligence must not erase existing package goals.

---

## 9. Tests that must remain intact

| File | Why |
|------|-----|
| `tests/test_experience_2.py` | Nav, Brief→Deliver rail, continuation, workspace persistence |
| `tests/test_publishing_package.py` | Publishing selection, ZIP, history, regressions |
| `tests/test_automatic_studio.py` | Brand Guide, Production Rules, learning schema |
| `tests/test_studio.py` | Finishes, downloads |
| `tests/test_persistence.py` | Atomic writes, approvals, assignments |
| `tests/test_templates_acceptance.py` | Piece parse, assign, render, approval |
| `tests/test_revisions.py` | Revision store and brand validation |
| `tests/test_em_dash.py` | Publishing copy form regressions |

New tests land in `tests/test_campaign_intelligence.py` (and helpers as needed). Full suite must pass after implementation.

---

## 10. Implementation approach (post-audit)

1. Add `src/campaign_intelligence/` pure library (calendar, lead times, scheduling, recommendations, estimates, brief PDF, store).
2. Add `production/strategy_rules.json` and brand `calendar_rules.json`.
3. Extend Brief / Plan / Capture / Today / Settings / Campaign details additively.
4. On Accept Plan: generate Production Brief, persist, show download success state.
5. After Capture analysis hook: revise runway estimate while keeping pre-shoot history.
6. Preserve Create, Decide, Deliver, and Publishing Package unchanged except shared download helpers if extracted carefully.
