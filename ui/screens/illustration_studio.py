"""Illustration Studio — create, revise, review and export Betty artwork.

Reached from Create and Library (and the active campaign), not from the primary
sidebar: the Experience 2 reduction keeps that list to five destinations.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from src.common import DEFAULT_BRAND_ID
from src.data_dir import data_root, is_configured, is_inside_repo
from ui import nav
from ui.components import (
    blocked_list,
    empty_state,
    key_values,
    note,
    page_header,
    quiet,
    section,
)
from illustration import canon, compositor, service, vault, versions
from illustration.models import (
    CHARACTER_LABELS,
    REFERENCE_ROLES,
    VAULT_CATEGORIES,
    VERIFICATION_STATES,
)
from illustration.provider import ProviderError, ProviderUnavailable, get_provider

BRAND_ID = DEFAULT_BRAND_ID
_OUTCOME_ICON = {"pass": "✅", "warning": "⚠️", "fail": "⛔", "needs_human": "👁"}


def render() -> None:
    page_header(
        "Illustration Studio",
        "Modern Heirloom Editorial artwork from your saved references.",
    )
    if st.button("← Back to Today", key="ill_back"):
        nav.clear_contextual_page()
        nav.goto("Today")

    _storage_banner()

    vault_tab, create_tab, versions_tab = st.tabs(
        ["Brand Asset Vault", "Create", "Versions & Export"]
    )
    with vault_tab:
        _vault_panel()
    with create_tab:
        _create_panel()
    with versions_tab:
        _versions_panel()


# --- storage ---------------------------------------------------------------------


def _storage_banner() -> None:
    root = data_root()
    if not is_configured():
        st.warning(
            f"Private assets are being stored at `{root}`, inside the "
            "repository (gitignored). Set **BETTY_OS_DATA_DIR** to a folder "
            "outside the repo to keep family photographs and product masters "
            "fully separate from this public project.",
            icon="🔒",
        )
    elif is_inside_repo():
        st.warning(
            f"BETTY_OS_DATA_DIR points inside the repository (`{root}`). "
            "Prefer a path outside it.",
            icon="🔒",
        )
    else:
        quiet(f"Private asset root: {root}")


# --- vault -----------------------------------------------------------------------


def _vault_panel() -> None:
    section(
        "Brand Asset Vault",
        "Upload once. Every future generation can select these without "
        "re-uploading.",
    )
    stats = vault.stats(BRAND_ID)
    columns = st.columns(4)
    columns[0].metric("Assets", stats["total"])
    columns[1].metric("Locked marks", stats["locked"])
    columns[2].metric("Private", stats["private"])
    columns[3].metric("Categories", sum(1 for v in stats["by_category"].values() if v))

    with st.expander("Import an asset", expanded=not stats["total"]):
        _import_form()
    with st.expander("Bootstrap from a starter-pack ZIP"):
        _zip_form()

    st.divider()
    _browse_vault()


def _import_form() -> None:
    upload = st.file_uploader(
        "Image, SVG or PDF",
        type=["png", "jpg", "jpeg", "webp", "tif", "tiff", "svg", "pdf"],
        key="ill_vault_upload",
    )
    columns = st.columns(2)
    category = columns[0].selectbox("Category", VAULT_CATEGORIES, key="ill_vault_cat")
    state = columns[1].selectbox(
        "Verification", VERIFICATION_STATES,
        index=VERIFICATION_STATES.index("draft"), key="ill_vault_state",
    )
    display_name = st.text_input("Name", key="ill_vault_name")
    roles = st.multiselect("Reference roles", REFERENCE_ROLES, key="ill_vault_roles")
    tags = st.text_input("Tags (comma separated)", key="ill_vault_tags")
    characters = st.multiselect(
        "Characters", list(CHARACTER_LABELS), format_func=lambda c: CHARACTER_LABELS[c],
        key="ill_vault_chars",
    )
    columns = st.columns(2)
    private = columns[0].checkbox(
        "Private (family photo or proprietary master)", value=True, key="ill_vault_priv"
    )
    opt_in = columns[1].checkbox(
        "Allow sending to a third-party image API", value=False, key="ill_vault_optin",
        help="Required before a private reference is ever uploaded to a provider.",
    )

    if st.button("Import to vault", type="primary", key="ill_vault_import"):
        if upload is None:
            st.error("Choose a file first.")
            return
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / upload.name
            staged.write_bytes(upload.getbuffer())
            try:
                record = vault.import_asset(
                    staged,
                    brand_id=BRAND_ID,
                    category=category,
                    display_name=display_name or Path(upload.name).stem,
                    roles=roles,
                    state=state,
                    tags=[t.strip() for t in tags.split(",") if t.strip()],
                    character_ids=characters,
                    is_private=private,
                    third_party_api_opt_in=opt_in,
                    original_filename=upload.name,
                )
            except vault.VaultError as exc:
                st.error(str(exc))
                return
        st.success(f"Imported {record.display_name} as `{record.asset_id}`.")
        st.rerun()


def _zip_form() -> None:
    archive = st.file_uploader("Starter pack (.zip)", type=["zip"], key="ill_zip")
    default_category = st.selectbox(
        "Category for files the manifest does not name",
        VAULT_CATEGORIES, key="ill_zip_cat",
    )
    if st.button("Import archive", key="ill_zip_import"):
        if archive is None:
            st.error("Choose a ZIP first.")
            return
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / archive.name
            staged.write_bytes(archive.getbuffer())
            try:
                result = vault.import_zip(
                    staged, brand_id=BRAND_ID, default_category=default_category
                )
            except vault.VaultError as exc:
                st.error(str(exc))
                return
        st.success(f"Imported {len(result['imported'])} asset(s).")
        if result["skipped"]:
            st.warning(
                "Skipped:\n"
                + "\n".join(f"- `{s['path']}` — {s['reason']}" for s in result["skipped"])
            )
        st.rerun()


def _browse_vault() -> None:
    columns = st.columns([2, 1, 1])
    text = columns[0].text_input("Search", key="ill_vault_search")
    category = columns[1].selectbox(
        "Category", ["all", *VAULT_CATEGORIES], key="ill_vault_filter_cat"
    )
    state = columns[2].selectbox(
        "State", ["all", *VERIFICATION_STATES], key="ill_vault_filter_state"
    )

    results = vault.search(
        BRAND_ID,
        text=text,
        categories=None if category == "all" else [category],
        states=None if state == "all" else [state],
    )
    if not results:
        empty_state("Nothing in the vault yet", "Import your starter pack above.")
        return

    for asset in results:
        with st.expander(
            f"{asset.display_name} · {asset.category} · {asset.state}", expanded=False
        ):
            left, right = st.columns([1, 2])
            thumb = (
                vault.resolve_data_path(asset.thumbnail_path)
                if asset.thumbnail_path
                else None
            )
            if thumb and thumb.is_file():
                left.image(str(thumb), use_container_width=True)
            elif vault.asset_path(asset).suffix.lower() != ".pdf":
                try:
                    left.image(str(vault.asset_path(asset)), use_container_width=True)
                except Exception:  # noqa: BLE001
                    left.caption("No preview.")
            with right:
                key_values(
                    [
                        ("Asset ID", asset.asset_id),
                        ("Roles", ", ".join(asset.roles) or "—"),
                        ("Dimensions", f"{asset.width}×{asset.height}"
                         if asset.width else "—"),
                        ("SHA-256", asset.sha256[:16] + "…"),
                        ("Characters", ", ".join(asset.character_ids) or "—"),
                        ("Private", "yes" if asset.is_private else "no"),
                        ("API opt-in", "yes" if asset.third_party_api_opt_in else "no"),
                        ("Version", asset.version),
                    ]
                )
                controls = st.columns(3)
                new_state = controls[0].selectbox(
                    "State", VERIFICATION_STATES,
                    index=VERIFICATION_STATES.index(asset.state),
                    key=f"state_{asset.asset_id}",
                )
                if new_state != asset.state:
                    vault.set_state(asset.asset_id, new_state, BRAND_ID)
                    st.rerun()
                if controls[1].checkbox(
                    "API opt-in", value=asset.third_party_api_opt_in,
                    key=f"optin_{asset.asset_id}",
                ) != asset.third_party_api_opt_in:
                    vault.set_api_opt_in(
                        asset.asset_id, not asset.third_party_api_opt_in, BRAND_ID
                    )
                    st.rerun()
                if controls[2].button("Archive", key=f"arch_{asset.asset_id}"):
                    vault.archive_asset(asset.asset_id, BRAND_ID)
                    st.rerun()


# --- create ----------------------------------------------------------------------


def _create_panel() -> None:
    templates = canon.templates(BRAND_ID)
    if not templates:
        empty_state("No templates", "Add brands/<id>/illustration_templates.json.")
        return

    ids = list(templates)
    default_index = next(
        (i for i, t in enumerate(ids) if templates[t].is_default), 0
    )
    template_id = st.selectbox(
        "Template", ids, index=default_index,
        format_func=lambda t: templates[t].display_name, key="ill_template",
    )
    template = templates[template_id]

    products = canon.products(BRAND_ID)
    product_options = ["(none)", *products]
    product_index = (
        product_options.index(template.product_id)
        if template.product_id in products
        else 0
    )
    product_id = st.selectbox(
        "Product", product_options, index=product_index,
        format_func=lambda p: products[p].display_name if p in products else p,
        key="ill_product",
    )
    characters = st.multiselect(
        "Betty roles", list(CHARACTER_LABELS),
        default=template.character_ids,
        format_func=lambda c: CHARACTER_LABELS[c], key="ill_characters",
    )
    scene = st.text_area(
        "Scene", value=" ".join(template.prompt_blocks), height=110, key="ill_scene"
    )
    columns = st.columns(2)
    variations = columns[0].slider("Alternatives", 1, 4, 1, key="ill_variations")
    canvas = columns[1].selectbox(
        "Canvas", list(compositor.CANVAS_PRESETS),
        index=list(compositor.CANVAS_PRESETS).index(template.canvas),
        key="ill_canvas",
    )

    brief = service.build_brief(
        brand_id=BRAND_ID,
        template_id=template_id,
        scene_text=scene,
        character_ids=characters,
        product_id=None if product_id == "(none)" else product_id,
        canvas=canvas,
        variations=variations,
    )
    plan = service.plan_draft(brief, brand_id=BRAND_ID)

    section("Reference tray", "Assembled from the vault — no re-uploading.")
    if plan.generation.reference_tray:
        for row in plan.generation.reference_tray:
            consent = "" if row["api_opt_in"] else " · ⚠ no API opt-in"
            st.markdown(
                f"- `{row['asset_id']}` **{row['display_name']}** — {row['role']} "
                f"({row['state']}); proves {row['proves']}{consent}"
            )
    else:
        quiet("No references matched. Import assets in the Vault tab.")

    with st.expander("Generation brief (what will be sent)", expanded=False):
        st.markdown(plan.generation.human_readable)

    if plan.generation.conflicts:
        for conflict in plan.generation.conflicts:
            text = f"**{conflict.field}** — {conflict.detail}"
            if conflict.severity == "blocking":
                st.error(text)
            else:
                st.warning(text)

    note(f"Provider: **{plan.provider_name}** · {plan.cost.describe()}")

    if not plan.can_generate:
        blocked_list("Cannot generate yet", plan.blockers())
        st.caption(
            "You can still curate the vault, assemble the brief and preview "
            "deterministic overlays."
        )
        return

    if st.button("Generate draft", type="primary", key="ill_generate"):
        with st.spinner("Generating…"):
            try:
                created = service.generate_draft(brief, brand_id=BRAND_ID)
            except (ProviderUnavailable, ProviderError, service.ServiceError) as exc:
                st.error(str(exc))
                return
        st.success(
            f"Created {len(created)} version(s): "
            + ", ".join(v.version_id for v in created)
        )
        st.rerun()


# --- versions --------------------------------------------------------------------


def _versions_panel() -> None:
    records = versions.list_versions(BRAND_ID)
    if not records:
        empty_state("No illustrations yet", "Generate a draft from the Create tab.")
        return

    for version in reversed(records):
        header = f"{version.version_id} · {version.status} · {version.accuracy_status}"
        with st.expander(header, expanded=False):
            _version_detail(version)


def _version_detail(version) -> None:
    image = versions.resolve(version.composited_path or version.source_image_path)
    left, right = st.columns([1, 1])
    if image and image.is_file():
        left.image(str(image), use_container_width=True)
        if st.session_state.get(f"mobile_{version.version_id}"):
            from PIL import Image as PILImage

            with PILImage.open(image) as img:
                left.image(
                    compositor.mobile_crop_preview(img), caption="Mobile 4:5 crop",
                    use_container_width=True,
                )
    left.checkbox("Mobile crop preview", key=f"mobile_{version.version_id}")

    with right:
        key_values(
            [
                ("Template", version.brief.template_id),
                ("Canvas", version.brief.canvas),
                ("Provider / model", f"{version.provider} · {version.model}"),
                ("Source resolution",
                 f"{version.source_width}×{version.source_height}"
                 if version.source_width else "—"),
                ("Parent", version.parent_version_id or "—"),
                ("Layers", ", ".join(version.layer_manifest.names()) or "—"),
            ]
        )
        if version.notes:
            st.caption(version.notes)

    section("Automated checks", "Deterministic only — visual judgement is yours.")
    for check in version.qa_results:
        icon = _OUTCOME_ICON.get(check["outcome"], "•")
        st.markdown(f"{icon} **{check['label']}** — {check.get('detail') or ''}")

    with st.expander("Human checklist before approval"):
        for item in version.human_checklist:
            st.checkbox(item["question"], key=f"{version.version_id}_{item['item_id']}")

    controls = st.columns(4)
    if controls[0].button("Export", key=f"exp_{version.version_id}"):
        try:
            service.export_version(version.version_id, brand_id=BRAND_ID)
        except service.ServiceError as exc:
            st.error(str(exc))
            return
        st.success("Exported.")
        st.rerun()

    product_accurate = controls[1].checkbox(
        "Product-accurate", key=f"acc_{version.version_id}",
        help="Only with a verified current mockup attached.",
    )
    if controls[2].button("Approve", key=f"app_{version.version_id}"):
        versions.approve(
            version.version_id, BRAND_ID, product_accurate=product_accurate
        )
        service.run_qa(version.version_id, brand_id=BRAND_ID)
        st.rerun()
    if controls[3].button("Reject", key=f"rej_{version.version_id}"):
        versions.reject(version.version_id, BRAND_ID)
        st.rerun()

    if version.export_paths:
        section("Exported files")
        for kind, stored in version.export_paths.items():
            path = versions.resolve(stored)
            if path and path.is_file():
                st.caption(f"{path.name} — {path.stat().st_size // 1024} KB")
                with path.open("rb") as handle:
                    st.download_button(
                        f"Download {kind.upper()}", handle, file_name=path.name,
                        key=f"dl_{version.version_id}_{kind}",
                    )
            else:
                st.error(f"{kind}: recorded but missing on disk.")

    _revision_controls(version)


def _revision_controls(version) -> None:
    section("Revise", "Always a new version — the original is never overwritten.")
    instruction = st.text_input(
        "Change only…", key=f"rev_{version.version_id}",
        placeholder="make only the scarf's repeating motif the official four-petal logo",
    )
    region = st.selectbox(
        "Region", ["(whole image)", "eyes", "scarf", "bottle label", "backdrop",
                   "botanical cluster"],
        key=f"reg_{version.version_id}",
    )
    columns = st.columns(2)
    if columns[0].button("Generative revision", key=f"gr_{version.version_id}"):
        if not instruction.strip():
            st.error("Describe the change first.")
            return
        st.caption(
            "A generative edit may alter neighbouring pixels. Locked layers are "
            "re-applied afterwards."
        )
        try:
            child = service.revise(
                version.version_id, instruction, brand_id=BRAND_ID,
                region=None if region.startswith("(") else region,
            )
        except (ProviderUnavailable, ProviderError, service.ServiceError) as exc:
            st.error(str(exc))
            return
        st.success(f"Created {child.version_id} from {version.version_id}.")
        st.rerun()

    if columns[1].button(
        "Re-apply exact artwork (no model)", key=f"dr_{version.version_id}",
        help="Deterministic overlay — nothing else in the image can drift.",
    ):
        try:
            child = service.deterministic_overlay_revision(
                version.version_id, brand_id=BRAND_ID, note=instruction,
            )
        except service.ServiceError as exc:
            st.error(str(exc))
            return
        st.success(f"Created {child.version_id}.")
        st.rerun()
