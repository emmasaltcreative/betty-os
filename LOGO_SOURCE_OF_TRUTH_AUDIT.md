# Logo Source-of-Truth Audit (BettyOS Alpha)

## Verdict

The failing test `test_seed_jade_rectangle_is_not_a_suitable_mark` did **not** mean
the jade rectangle was accepted. The jade seed still fails suitability analysis.
The test failed because it assumed `select_best_logo_asset()` returns `None`, while
a real Settings/Library emblem (`ba_1ce4b91d16`, four-petal knockout SVG) is now
present and suitable.

## Canonical source

- **Storage:** `brands/<brand_id>/studio/assets/` + `brand_assets.json`
- **Active pointer:** `active_brand_mark_id` + `active_brand_mark_selected_at` in the
  brand assets index
- **Resolver:** `services/active_logo.py` → `resolve_active_logo()`
- **UI:** Settings › Active Brand Mark (also Library Brand Setup via Set as Default)

## Consumers (must use resolver)

| Surface | Behavior |
|---|---|
| Studio auto finish | `select_best_logo_asset` prefers active mark |
| Revisions | inherit finish logo decision / omit path |
| Brand Check | `evaluate_brand_mark` |
| Campaign PDF/DOCX | embed rasterized active mark |
| Delivery manifest | `active_brand_mark.asset_id` (no absolute paths) |

## Historical immutability

Previously rendered pixels, approvals, and archived packages are not rebuilt when
the active mark changes. New drafts, revisions, finishes, and newly generated
documents resolve the current active mark.

## Jade placeholder protection

`analyze_mark_pixels` / `evaluate_logo_suitability` continue to reject solid
rectangular badges. Filename and seed-path checks are not the sole gate.
