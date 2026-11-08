# Illustration Studio

Generative Betty illustration and PDP artwork, layered additively on the
existing BettyOS Studio. Nothing in the prior image, video, planning, revision
or CLI workflows was changed.

---

## 1. Where things live — and why

The GitHub repository is **public**. Family photographs, proprietary product
masters and generated illustration bytes must never be committed to it.

| What | Where | In git? |
|---|---|---|
| Style, canon, product truth, templates | `brands/oh_betty_jaletti/illustration_*.{md,json}` | **Yes** — text specs only |
| Code | `illustration/`, `ui/screens/illustration_studio.py` | Yes |
| Vault originals, thumbnails, index | `$BETTY_OS_DATA_DIR/brands/<id>/vault*` | **No** |
| Generated drafts, composites, exports | `$BETTY_OS_DATA_DIR/brands/<id>/illustration/` | **No** |

Set the data root before first use:

```bash
export BETTY_OS_DATA_DIR="$HOME/BettyOS-Private"
```

If it is unset, the app falls back to `./.betty_data`, which is gitignored, and
the Studio shows a banner telling you so. `brands/*/studio/assets/*` is now
gitignored too, so runtime Brand Asset uploads can no longer be committed by
accident. (The one seed logo already tracked before this change stays tracked.)

Private paths are never written to logs verbatim — `src.data_dir.redact()`
renders them as `<data_root>/…/name`.

---

## 2. Launch and test

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Open **Create → Illustration Studio** or **Library → Open Illustration Studio**.
It is deliberately *not* a sidebar item: the Experience 2 UX reduction keeps the
primary nav minimal, so this is a contextual destination like the workspace.

```bash
python3 -m pytest tests -q
```

---

## 3. The three tabs

**Brand Asset Vault** — import single files or a starter-pack ZIP with a
`manifest.json`. Each asset gets a stable `asset_id`, SHA-256 checksum,
category, roles, verification state, tags, product/character links and a
derived thumbnail. Full originals are always preserved. Imports are restricted
to safe types, SVGs are sanitised (scripts, event handlers, entities and frames
are rejected outright), and identical bytes dedupe rather than piling up.
Replacing an asset creates a new version and archives the parent — history is
never deleted.

**Create** — pick a template, product, Betty roles and a scene. The reference
tray is assembled automatically from saved vault assets, so **nothing is ever
re-uploaded**. The full generation brief is shown before any paid call, with
non-negotiable product facts, what each reference is allowed to prove,
conflicts, and a cost estimate.

**Versions & Export** — per-version QA, the human checklist, approval, export,
targeted revision and lineage.

---

## 4. Precedence

When sources disagree, the earlier wins:

```
official exact file > verified product spec > approved character anchor
> approved style anchor > user scene instruction > generic invention
```

A style board labelled `style_only` cannot be used to prove product facts, and
a `rejected` asset can never anchor a new generation — both are blocking
conflicts, surfaced before anything is sent.

---

## 5. Two-stage generation

**Stage A — painterly scene.** A swappable provider adapter
(`illustration/provider.py`). With no key configured, `NullProvider` reports
itself unavailable and *raises* — the UI never shows a false "Generate"
success. You can still curate assets, write a brief and preview deterministic
overlays.

```bash
export BETTY_OS_IMAGE_PROVIDER=openai
export OPENAI_API_KEY=...
export BETTY_OS_IMAGE_MODEL=<a model your account can actually call>
export BETTY_OS_IMAGE_MODEL_DRAFT=<faster model for drafts>
export BETTY_OS_IMAGE_PRICE_USD=0.17     # drives the cost estimate
```

Model ids are configuration, never hardcoded — verify the current Images API
docs and your account's model list before trusting any default.

**Stage B — deterministic truth layer.** Labels, house marks, the signature and
exact product text are composited from source artwork
(`illustration/compositor.py`), never generated. The model is explicitly
instructed to leave the label area clear and unlettered.

---

## 6. What is guaranteed, mechanically

Each of these is asserted in `tests/test_illustration_compositor.py` and
recorded in the per-version layer manifest:

- Label negative space has **alpha 0**, so the amber glass shows through.
- The ghosted repeating four-petal mark sits at **~0.5 alpha**, not a cream fill.
- Title, `EAU DE PARFUM` and `10 mL` are white; mark and signature are gold.
- The signature is **below** the EDP/size text.
- Copy runs **lengthwise** along the cylinder.
- A notes line is drawn **only** when the approved label actually has one.
- Official marks keep their aspect ratio in every box. Never stretched.
- Both gold end components exist as separate, assertable render layers.
- Exports are real, decodable files at the exact canvas size.

---

## 7. Importing the starter pack

Library → **Open Illustration Studio** → **Brand Asset Vault** → *Bootstrap
from a starter-pack ZIP*.

Put a `manifest.json` at the archive root to assign category, verification
state, roles and tags per file. A worked template with the real Oh Betty
Jaletti asset types lives at
`brands/oh_betty_jaletti/starter_pack_manifest.template.json`.

**Preview (no changes)** runs a dry run first: it lists exactly what would
import and where, which files the manifest does not describe, which manifest
paths are missing from the archive, and what would be skipped and why. Nothing
is written until you press Import.

The manifest is what marks the official flower, signature and seal as
`locked`, which is what lets the compositor use them as exact source artwork.
Without it everything lands as `draft` and no label is composited.

## 8. Review and Approvals

Illustrations go through the same machinery as renders, not a parallel one.

**Send to Review** copies the version's exported files into the active
campaign's `outputs/<campaign>/illustrations/` folder — a copy, so the private
original never moves — and registers the version in that campaign's approvals
store as `awaiting_review`. It refuses outright if the version has no real
exported file yet, rather than queueing something that cannot be looked at.

**Record decision** writes `approved` / `needs_revision` / `rejected` to the
campaign approvals store and emits a standard `ApprovalEvent`, so Insights and
the learning engine treat illustration feedback like any other.

`Product-accurate` is only honoured when the product profile is itself
verified. Tick it against an unverified product and the UI tells you it was
refused.

## 9. Status ladder

```
Draft → Needs Accuracy Review → Approved for Editorial Use → Exported
```

`Product-Accurate Verified` is tracked **separately** and is refused while the
product profile is unverified, even if a user ticks the box. Rejected versions
stay reachable but never anchor future work.

---

## 10. Honest limitations

- **No verified product mockup is attached yet.** `A Woman Remembered 10 mL`
  ships with `spec_verified: false`; exact dimensions, production components,
  the label print file and a current mockup are all `unverified`. Every draft is
  therefore flagged *Requires product verification*.
- **The bottle is a schematic.** Without a verified mockup, the label is
  previewed on a deterministic amber cylinder drawn from the product profile. It
  is a label-geometry preview, not product photography, and QA records its
  geometric accuracy as `approximate` with a `needs_human` check.
- **The cylindrical warp is shading, not photogrammetry.**
- **No image provider is configured by default**, so Generate is honestly
  disabled rather than faking a result.
- **The official marks are not in the repo.** The locked quatrefoil and
  signature SVGs must be imported into the vault before any label is composited;
  until then no label layer is drawn and QA says so.
- **SVG rasterisation needs `cairosvg`** (and the system cairo library). Without
  it, SVG marks raise a clear error asking for a PNG master — a model is never
  used as a substitute.
- **Visual semantics are left to a person.** Whether five Bettys are
  recognisable, whether a flower is jasmine and not gardenia, and whether the
  art reads as Modern Heirloom Editorial are human checklist items. No RGB
  heuristic pretends to settle them.
