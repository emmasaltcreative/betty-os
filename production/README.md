# Production Brain

Shared visual language for every BettyOS export (Reels, Pins, Stories, Shorts, and future templates).

## Inheritance model

1. **Load globals first** — every renderer reads:
   - `global_defaults.json`
   - `typography.json`
   - `colors.json`
   - `layout.json`
   - `animation.json`
   - `exports.json`
   - `safe_zones.json`
2. **Then load the template** — e.g. `templates/page_turn_loop.json`
3. **Resolve** — template fields override globals only when present; everything else inherits.

Templates should contain **only** what is unique to that piece:

- source media path
- target duration
- copy (hook / footer / CTA lines)
- which platforms’ safe zones to respect

Do **not** put fonts, colors, fade lengths, crop strategy, export codec, or safe-zone pixels in a template unless you are intentionally overriding the global brain.

## Adding a future template

1. Create `production/templates/<name>.json` with piece-specific fields only.
2. Point a renderer at that template.
3. Call the shared Production Brain loader before render.
4. Prefer global values; override sparingly.

## Style guide

Editorial rules live in `style_guide.md`. Configuration files encode those rules as data; the style guide explains the intent.
