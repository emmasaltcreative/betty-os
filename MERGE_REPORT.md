# Automatic Studio Semantic Merge Report

**Date:** 2026-08-03  
**Merge:** `main` (OURS / PR finishing engine) ← `backup/local-automatic-studio` (THEIRS / local Automatic Studio)  
**Merge base:** `c6f43ca` (Integrate AI revisions, Studio, review, approval, and export)

## Branches

| Side | Ref | Description |
|------|-----|-------------|
| **OURS** | `main` @ `bb19658` | Cursor PR *Automatic Studio finishing engine* — brand-informed Best Edit, structured decisions, learning, Advanced UI |
| **THEIRS** | `backup/local-automatic-studio` @ `9d188f1` | Independently developed local Automatic Studio — richer decision identity, recipe scoring, approval→review, learning schema used on disk |

---

## What existed in each branch

### OURS (`main`)

- Lean `EditDecision` with Brand Guide / Production Rules **file provenance** lists
- Env-based AI cleanup detection (`BETTYOS_AI_CLEANUP_PROVIDER`, Replicate, OpenAI)
- Glob-all `production/*.json` loading
- Execution report as flat `applied_actions` / `not_applied_actions` + `warnings_acknowledged`
- Learning via `approval_status`, embedded `edit_decision`, evidence-keyed preference promotion
- Lean `PerformanceRecord` (`metric_name` / `metric_value`)
- `revise_best_edit` patches parent config then creates a new immutable finish
- `set_finish_approval(..., approval_status=...)`
- UI: automatic controls first; manual path under Advanced expander
- Failure-path persistence of edit decision / execution report on failed finishes
- Always write `edit_decision.json` / `execution_report.json`

### THEIRS (`backup/local-automatic-studio`)

- Identity-rich `EditDecision` (`decision_id`, campaign lineage, `guidance_conflict_resolutions`)
- Weighted `_RECIPE_HINTS` recipe scoring + conflict logging
- Hard gate: Best Edit fails if Brand Guide or Production Rules cannot load
- Stateful `ExecutionReport` (`edit_fully_applied` / `edit_partially_applied` / …)
- Learning schema matching existing brand JSON (`status`, `logo_decision`, `recipe_id`, …)
- Rich `PerformanceRecord` (impressions, views, completion_rate, …)
- `revise_best_edit` re-runs full Best Edit with revision note; honest re-render-only path
- Approve triggers `send_to_review`
- UI: approval-first experience (before/after, score, key decisions, Apply Revision)
- Opinionated logo / export / video-grade mapping from Production Brain

---

## What was preserved (union)

| Concern | How preserved |
|---------|----------------|
| **Opinionated Automatic Studio** | THEIRS recipe scoring + logo rules + Production export presets; OURS content-type override + optional logo when asset exists |
| **Production Brain** | Brand Guide markdown + all Production Rules JSON (preferred named set **and** glob extras); file lists recorded on decisions |
| **Version immutability** | `finish_vNNN` atomic create; revisions always spawn a new version with `parent_finish_version_id`; source bytes untouched |
| **Learning engine** | THEIRS on-disk schema + promotion after ≥3 signals; OURS evidence-key dedupe and lifestyle-logo preference candidates |
| **Approval workflow** | Approve / Needs Revision / Reject; learning events; approve → Send to Review |
| **Revision workflow** | NL parse + supported finish deltas; re-render-only honesty; both API shapes (`finish_version_id` and `parent_finish_version_id`) |
| **UI improvements** | THEIRS approval experience + Advanced demotion; OURS provenance fields in Edit Details |
| **Persistence** | Decision/report JSON always written; failure records keep auto fields; brand learning JSON dual-readable |

---

## Duplicated logic removed

- Duplicate `"Automatic Best Edit"` entry in `STUDIO_CAPABILITIES` (list had both OURS and THEIRS copies)
- Duplicate capability note strings collapsed into one merged description
- Double-write of `edit_decision.json` / `execution_report.json` in `versions.create_finished_version` (write-once, always, after metadata)
- Parallel incompatible learning / decision serializers replaced by one dual-read canonical schema
- Two separate test files’ overlapping coverage merged into one suite (8 tests covering both APIs)

---

## Architectural improvements

1. **Canonical dual-read schemas** in `edit_decision.py` and `learning.py`  
   - Primary fields match THEIRS (and existing brand `approval_events.json`)  
   - Aliases accept OURS shapes (`category`/`recommendation`, `approval_status`, `applied_actions`, lean performance metrics)

2. **Unified service APIs**  
   - `set_finish_approval` accepts `status` **or** `approval_status`  
   - `revise_best_edit` accepts either THEIRS or OURS call shapes  
   - `generate_best_edit` accepts `content_type` and richer piece context

3. **Stronger Best Edit gate + honest cleanup**  
   - Requires Brand Guide + Production Rules (THEIRS)  
   - AI cleanup detection is env-aware (OURS) but never claims applied work without a real provider

4. **Revision returns structured applied actions**  
   - `apply_revision_note_to_config` → `(config, actions)` with `revision:logo_omit` etc., feeding execution reports

5. **Learning loop strengthened**  
   - Event-id dedupe  
   - Both count-based promotion and evidence-key promotion toward the lifestyle logo-omit finding

---

## Conflicted files resolved

| File | Resolution |
|------|------------|
| `studio/edit_decision.py` | Unified schema (THEIRS + OURS provenance + dual-read) |
| `studio/learning.py` | THEIRS persistence + OURS evidence/dedupe + unified PerformanceRecord |
| `studio/auto_edit.py` | THEIRS engine + OURS env cleanup, file lists, dual revision API |
| `studio/service.py` | THEIRS orchestration + dual public APIs |
| `studio/models.py` | Shared FinishRecord auto fields + clarifying comment |
| `ui/screens/studio.py` | THEIRS automatic UI + provenance in Edit Details |
| `tests/test_automatic_studio.py` | Union of both branches’ assertions |

Already auto-merged (then cleaned): `studio/capabilities.py`, `studio/versions.py`

---

## Verification

- **Merge markers:** none remaining under `studio/`, `ui/screens/studio.py`, `tests/`
- **Full test suite:** **65 passed** (8 Automatic Studio + existing suite)
- **Application launch:** Streamlit `app.py` started cleanly (`You can now view your Streamlit app`, port 8765 smoke)
- **Imports:** `app`, `ui.screens.studio`, Automatic Studio service/auto_edit/learning import successfully

---

## Outcome

The merged tree is strictly better than either branch alone: it keeps the local engine’s opinionated Production Brain behavior and on-disk learning compatibility, while retaining the finishing engine’s provenance, env-aware cleanup honesty, dual APIs, failure-path audit artifacts, and test coverage.
