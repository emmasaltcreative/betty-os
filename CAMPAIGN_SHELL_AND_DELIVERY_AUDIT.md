# Campaign Shell and Delivery Audit

**Date:** 2026-08-05  
**Scope:** Live BettyOS Streamlit shell — navigation, campaign identity, Create flow, Deliver packaging.  
**Method:** Code-path verification. `reportlab` present; `python-docx` absent before this sprint.

---

## Verdict

BettyOS collapsed pipeline pages into five destinations plus a contextual workspace, but the product still behaves like an asset queue with a campaign label. Critical gaps: sidebar cannot leave workspace, campaign names are timestamps, Approve always jumps to Deliver, Create Best Draft requires two clicks, and packages still surface TXT/MD/JSON as primary human documents.

---

## 1. Global navigation and routing

| Destination | Module | Works? | Notes |
|-------------|--------|--------|-------|
| Today | `ui/screens/today.py` | Yes | One continuation card |
| Campaigns | `ui/screens/campaigns.py` | Yes | List/create; Continue → workspace |
| Library | `ui/screens/library.py` | Yes | Assets/brand/templates |
| Insights | `ui/screens/insights.py` | Partial | Learning ledger only; no connected performance |
| Settings | `ui/screens/settings.py` | Yes | Config + strategy rules |
| Workspace | `ui/screens/workspace.py` | Yes | Contextual; Brief→Deliver |

**Critical bug:** When `_contextual_page == "workspace"`, `app.py` always renders workspace and **ignores** sidebar radio changes. Clicking Campaigns/Library/Insights/Settings updates the radio but not the main pane unless `clear_contextual_page()` is called.

**Rerun persistence:** Session keys + `betty_workspace_context.json` for stage/piece/version. Survives restart for the same folder.

---

## 2. Active-campaign sidebar

Shows: name (timestamp), status badge, unlabeled `st.progress`. Not clickable. No objective, deliverable counts, runway, or next action.

---

## 3. Campaign naming

`campaign_display_name` formats folder stamps as `Campaign — 4 Aug 2026, 16:56`. Goal/theme not used. Folder id remains the persistence key.

---

## 4. Stage navigation (duplicate layers)

Competing: focus bar, stage segmented control, progress rail (full view), timeline toggle, Campaigns Timeline tab. Workflow stages act as a second app menu.

---

## 5. Asset selection / next asset

`resolve_continuation` picks first missing → first ready → review/export. After Approve, workspace **always** `goto_workspace("deliver")` — does not continue to the next piece or explain campaign progress.

---

## 6. Deliver selection

`build_publishing_plan` selects canonical latest approved finish/render/copy per piece::template. UI says “Campaign Ready” whenever any publishable items exist — not based on planned deliverable coverage. Partial packages are the default mental model.

---

## 7. Package structure (current)

```
{slug}_publishing-package/
  {platform}/media + captions (.txt)
  Campaign Overview.txt
  Production Brief.pdf (optional)
  Campaign Brief.md (optional)
  README.txt
  Manifest.json / manifest.json
```

Overview language is defensive (“latest approved only… excluded”).

---

## 8. PDF / DOCX

- reportlab: yes (Production Brief)
- python-docx: no
- No Campaign Copybook; captions often `.txt`

---

## 9. Timeline

`ui/timeline.py` milestones exist. “Published” falsely completes when a package exists. Not the primary campaign shell.

---

## 10. Campaign intelligence / Production Brief

Integrated in Brief/Plan/Today/package docs. Parallel to session goal; not a full campaign container UI.

---

## 11. Create Best Draft double-click

`_run_create_best`: if no version, renders base then returns to Create — user must click again for `generate_best_edit`. Button never disables. `PROCESSING` state never emitted.

---

## 12. Migration / compatibility risks

- Dual goal sources (session vs package vs intelligence)
- Dual approval (Studio finish vs campaign approvals.json)
- Sidebar/workspace desync
- Timestamp ZIP and campaign names
- Existing packages/history must remain readable
- Do not break `test_publishing_package.py` / Experience 2 tests without updating expectations carefully

---

## Implementation approach (this sprint)

1. Persist `campaign.json` meta (display title, objective, planned deliverables, completion) beside existing folder.
2. Campaign shell: Overview / Creative / Publishing / Timeline as primary in-campaign destinations.
3. Fix sidebar routing; demote Insights; enrich active-campaign panel.
4. One-click Create with job id + processing state.
5. Coverage-based Ready to Deliver vs Incomplete.
6. Human-ready delivery: PDF+DOCX copybook, platform copy sheets, visuals, BettyOS Data/ for JSON; positive overview language; readable ZIP names.
