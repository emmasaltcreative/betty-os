"""Oh Betty Jaletti Color Recipes — restrained starting presets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from src.common import DEFAULT_BRAND_ID
from src.persistence import atomic_write_json, load_json
from studio.models import ColorRecipe, utc_now_iso
from studio.paths import color_recipes_path

# Starting points — not calibrated film emulations.
_OBJ_STARTERS: list[dict[str, Any]] = [
    {
        "recipe_id": "obj_editorial_lifestyle",
        "display_name": "OBJ Editorial Lifestyle",
        "description": (
            "Upper West Side literary apartment; French atelier restraint; "
            "quiet warmth; editorial rather than cottagecore."
        ),
        "lighting": {
            "exposure": 0.05,
            "brightness": 4,
            "contrast": -8,
            "highlights": -12,
            "shadows": 10,
            "whites": -4,
            "blacks": 6,
            "gamma": 1.02,
        },
        "color": {
            "temperature": 8,
            "tint": 2,
            "saturation": -6,
            "vibrance": 4,
            "fade": 6,
            "black_point_lift": 4,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 8,
            "grain_size": 1.0,
            "grain_roughness": 0.35,
            "grain_seed": 101,
            "sharpening": 8,
            "softening": 0,
            "clarity": 4,
            "bloom": 0,
            "vignette_amount": 8,
            "vignette_feather": 0.65,
            "vignette_midpoint": 0.55,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.8},
    },
    {
        "recipe_id": "obj_rainy_reading",
        "display_name": "OBJ Rainy Reading",
        "description": (
            "Warm interior against cooler rainy exterior; peaceful, inhabited, "
            "emotionally comforting."
        ),
        "lighting": {
            "exposure": 0.0,
            "brightness": 2,
            "contrast": -4,
            "highlights": -18,
            "shadows": 14,
            "whites": -6,
            "blacks": 4,
            "gamma": 1.0,
        },
        "color": {
            "temperature": 4,
            "tint": -2,
            "saturation": -10,
            "vibrance": 2,
            "fade": 4,
            "black_point_lift": 3,
            "red_balance": 0,
            "green_balance": -2,
            "blue_balance": 2,
        },
        "texture": {
            "grain_amount": 10,
            "grain_size": 1.1,
            "grain_roughness": 0.4,
            "grain_seed": 202,
            "sharpening": 6,
            "softening": 2,
            "clarity": 2,
            "bloom": 0,
            "vignette_amount": 6,
            "vignette_feather": 0.7,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_left", "size_mode": "subtle", "opacity": 0.75},
    },
    {
        "recipe_id": "obj_morning_window",
        "display_name": "OBJ Morning Window",
        "description": "Gentle moving sunlight; quiet morning; soft editorial clarity.",
        "lighting": {
            "exposure": 0.15,
            "brightness": 8,
            "contrast": -10,
            "highlights": -8,
            "shadows": 8,
            "whites": 2,
            "blacks": 4,
            "gamma": 1.03,
        },
        "color": {
            "temperature": 6,
            "tint": 0,
            "saturation": -2,
            "vibrance": 3,
            "fade": 2,
            "black_point_lift": 2,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 5,
            "grain_size": 0.9,
            "grain_roughness": 0.3,
            "grain_seed": 303,
            "sharpening": 10,
            "softening": 0,
            "clarity": 6,
            "bloom": 2,
            "vignette_amount": 4,
            "vignette_feather": 0.7,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "standard", "opacity": 0.85},
    },
    {
        "recipe_id": "obj_product_flatlay",
        "display_name": "OBJ Product Flatlay",
        "description": (
            "Polished editorial product arrangement; natural material visibility; quiet luxury."
        ),
        "lighting": {
            "exposure": 0.05,
            "brightness": 4,
            "contrast": 4,
            "highlights": -10,
            "shadows": 8,
            "whites": 0,
            "blacks": 0,
            "gamma": 1.0,
        },
        "color": {
            "temperature": 0,
            "tint": 0,
            "saturation": 0,
            "vibrance": 2,
            "fade": 0,
            "black_point_lift": 2,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 3,
            "grain_size": 0.8,
            "grain_roughness": 0.25,
            "grain_seed": 404,
            "sharpening": 12,
            "softening": 0,
            "clarity": 10,
            "bloom": 0,
            "vignette_amount": 2,
            "vignette_feather": 0.6,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.7},
    },
    {
        "recipe_id": "obj_pinterest_editorial",
        "display_name": "OBJ Pinterest Editorial",
        "description": (
            "Compelling vertical editorial imagery; strong mobile readability; "
            "atmospheric but not muddy."
        ),
        "lighting": {
            "exposure": 0.08,
            "brightness": 6,
            "contrast": 2,
            "highlights": -8,
            "shadows": 6,
            "whites": 0,
            "blacks": 2,
            "gamma": 1.0,
        },
        "color": {
            "temperature": 4,
            "tint": 0,
            "saturation": -4,
            "vibrance": 4,
            "fade": 3,
            "black_point_lift": 2,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 7,
            "grain_size": 1.0,
            "grain_roughness": 0.35,
            "grain_seed": 505,
            "sharpening": 10,
            "softening": 0,
            "clarity": 6,
            "bloom": 0,
            "vignette_amount": 10,
            "vignette_feather": 0.6,
            "vignette_midpoint": 0.45,
        },
        "logo": {"placement": "bottom_center", "size_mode": "standard", "opacity": 0.8},
        "geometry": {"aspect_preset": "2:3", "fit_mode": "fill"},
    },
    {
        "recipe_id": "obj_email_hero",
        "display_name": "OBJ Email Hero",
        "description": (
            "Clean, quick-loading visual; refined brand atmosphere; readable when smaller."
        ),
        "lighting": {
            "exposure": 0.1,
            "brightness": 6,
            "contrast": 0,
            "highlights": -6,
            "shadows": 4,
            "whites": 2,
            "blacks": 0,
            "gamma": 1.0,
        },
        "color": {
            "temperature": 2,
            "tint": 0,
            "saturation": -2,
            "vibrance": 2,
            "fade": 0,
            "black_point_lift": 0,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 2,
            "grain_size": 0.8,
            "grain_roughness": 0.25,
            "grain_seed": 606,
            "sharpening": 8,
            "softening": 0,
            "clarity": 4,
            "bloom": 0,
            "vignette_amount": 0,
            "vignette_feather": 0.5,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.85},
        "geometry": {"platform_preset": "email_hero", "fit_mode": "fit"},
        "export": {"format": "jpg", "quality": 85},
    },
    {
        "recipe_id": "obj_clean_product",
        "display_name": "OBJ Clean Product",
        "description": (
            "Faithful product representation; accurate materials and color; "
            "manufacturer- and commerce-safe clarity."
        ),
        "lighting": {
            "exposure": 0.0,
            "brightness": 2,
            "contrast": 2,
            "highlights": -8,
            "shadows": 4,
            "whites": 0,
            "blacks": 0,
            "gamma": 1.0,
        },
        "color": {
            "temperature": 0,
            "tint": 0,
            "saturation": 0,
            "vibrance": 0,
            "fade": 0,
            "black_point_lift": 0,
            "red_balance": 0,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 1,
            "grain_size": 0.7,
            "grain_roughness": 0.2,
            "grain_seed": 707,
            "sharpening": 10,
            "softening": 0,
            "clarity": 8,
            "bloom": 0,
            "vignette_amount": 0,
            "vignette_feather": 0.5,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.7},
    },
    {
        "recipe_id": "obj_autumn_reading",
        "display_name": "OBJ Autumn Reading",
        "description": "Fall warmth without orange overload; literary and urban; not rustic farmhouse.",
        "lighting": {
            "exposure": 0.0,
            "brightness": 2,
            "contrast": -4,
            "highlights": -6,
            "shadows": 10,
            "whites": -2,
            "blacks": 4,
            "gamma": 1.01,
        },
        "color": {
            "temperature": 10,
            "tint": 2,
            "saturation": -4,
            "vibrance": 3,
            "fade": 4,
            "black_point_lift": 3,
            "red_balance": 2,
            "green_balance": 0,
            "blue_balance": -2,
        },
        "texture": {
            "grain_amount": 8,
            "grain_size": 1.0,
            "grain_roughness": 0.35,
            "grain_seed": 808,
            "sharpening": 6,
            "softening": 0,
            "clarity": 3,
            "bloom": 0,
            "vignette_amount": 8,
            "vignette_feather": 0.65,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.8},
    },
    {
        "recipe_id": "obj_winter_ritual",
        "display_name": "OBJ Winter Ritual",
        "description": (
            "Intimate winter light; refined contrast; warm practical light with neutral product color."
        ),
        "lighting": {
            "exposure": -0.05,
            "brightness": 0,
            "contrast": 4,
            "highlights": -4,
            "shadows": 6,
            "whites": -2,
            "blacks": -2,
            "gamma": 1.0,
        },
        "color": {
            "temperature": -4,
            "tint": 0,
            "saturation": -4,
            "vibrance": 2,
            "fade": 2,
            "black_point_lift": 1,
            "red_balance": 1,
            "green_balance": 0,
            "blue_balance": 0,
        },
        "texture": {
            "grain_amount": 6,
            "grain_size": 0.95,
            "grain_roughness": 0.3,
            "grain_seed": 909,
            "sharpening": 8,
            "softening": 0,
            "clarity": 4,
            "bloom": 0,
            "vignette_amount": 12,
            "vignette_feather": 0.6,
            "vignette_midpoint": 0.45,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.8},
    },
    {
        "recipe_id": "obj_vintage_film",
        "display_name": "OBJ Vintage Film",
        "description": (
            "Restrained film character; nostalgic editorial image; never novelty-filtered. "
            "Not a professional film emulation."
        ),
        "lighting": {
            "exposure": 0.0,
            "brightness": 2,
            "contrast": -12,
            "highlights": -10,
            "shadows": 8,
            "whites": -4,
            "blacks": 10,
            "gamma": 1.04,
        },
        "color": {
            "temperature": 6,
            "tint": 4,
            "saturation": -12,
            "vibrance": -2,
            "fade": 12,
            "black_point_lift": 8,
            "red_balance": 2,
            "green_balance": 0,
            "blue_balance": -2,
        },
        "texture": {
            "grain_amount": 14,
            "grain_size": 1.2,
            "grain_roughness": 0.45,
            "grain_seed": 1010,
            "sharpening": 4,
            "softening": 4,
            "clarity": 0,
            "bloom": 3,
            "vignette_amount": 14,
            "vignette_feather": 0.7,
            "vignette_midpoint": 0.5,
        },
        "logo": {"placement": "bottom_right", "size_mode": "subtle", "opacity": 0.7},
    },
]


def _starter_to_recipe(raw: dict[str, Any], brand_id: str) -> ColorRecipe:
    now = utc_now_iso()
    return ColorRecipe(
        recipe_id=raw["recipe_id"],
        brand_id=brand_id,
        display_name=raw["display_name"],
        description=raw["description"],
        suitable_media_types=["static", "video"],
        suitable_content_types=["editorial", "product", "lifestyle"],
        suitable_platforms=["instagram", "pinterest", "email"],
        lighting_defaults=dict(raw.get("lighting") or {}),
        color_defaults=dict(raw.get("color") or {}),
        texture_defaults=dict(raw.get("texture") or {}),
        geometry_defaults=dict(raw.get("geometry") or {}),
        logo_defaults=dict(raw.get("logo") or {}),
        export_defaults=dict(raw.get("export") or {}),
        version=1,
        active=True,
        created_at=now,
        updated_at=now,
        history=[],
    )


def ensure_default_recipes(brand_id: str = DEFAULT_BRAND_ID) -> list[ColorRecipe]:
    """Seed OBJ starters if missing; never overwrite existing recipe bodies."""
    path = color_recipes_path(brand_id)
    data = load_json(path, default={"recipes": []}) or {"recipes": []}
    existing = {r.get("recipe_id") for r in data.get("recipes") or [] if isinstance(r, dict)}
    changed = False
    for raw in _OBJ_STARTERS:
        if raw["recipe_id"] in existing:
            continue
        recipe = _starter_to_recipe(raw, brand_id)
        data.setdefault("recipes", []).append(recipe.to_dict())
        changed = True
    if changed or not path.is_file():
        data["updated_at"] = utc_now_iso()
        atomic_write_json(path, data)
    recipes = [ColorRecipe.from_dict(r) for r in data.get("recipes") or [] if isinstance(r, dict)]
    return recipes


def list_recipes(
    brand_id: str = DEFAULT_BRAND_ID,
    *,
    include_archived: bool = False,
) -> list[ColorRecipe]:
    ensure_default_recipes(brand_id)
    data = load_json(color_recipes_path(brand_id), default={"recipes": []}) or {"recipes": []}
    recipes = [ColorRecipe.from_dict(r) for r in data.get("recipes") or [] if isinstance(r, dict)]
    if include_archived:
        return recipes
    return [r for r in recipes if r.active]


def get_recipe(recipe_id: str, brand_id: str = DEFAULT_BRAND_ID) -> ColorRecipe | None:
    for recipe in list_recipes(brand_id, include_archived=True):
        if recipe.recipe_id == recipe_id:
            return recipe
    return None


def _write_all(recipes: list[ColorRecipe], brand_id: str) -> None:
    atomic_write_json(
        color_recipes_path(brand_id),
        {
            "brand_id": brand_id,
            "updated_at": utc_now_iso(),
            "recipes": [r.to_dict() for r in recipes],
        },
    )


def save_new_recipe(
    *,
    brand_id: str,
    display_name: str,
    description: str,
    lighting: dict[str, Any],
    color: dict[str, Any],
    texture: dict[str, Any],
    geometry: dict[str, Any] | None = None,
    logo: dict[str, Any] | None = None,
    export: dict[str, Any] | None = None,
) -> ColorRecipe:
    recipes = list_recipes(brand_id, include_archived=True)
    now = utc_now_iso()
    recipe = ColorRecipe(
        recipe_id=f"recipe_{uuid4().hex[:10]}",
        brand_id=brand_id,
        display_name=display_name.strip() or "Untitled Recipe",
        description=description.strip(),
        suitable_media_types=["static", "video"],
        suitable_content_types=["editorial"],
        suitable_platforms=["instagram", "pinterest"],
        lighting_defaults=dict(lighting),
        color_defaults=dict(color),
        texture_defaults=dict(texture),
        geometry_defaults=dict(geometry or {}),
        logo_defaults=dict(logo or {}),
        export_defaults=dict(export or {}),
        version=1,
        active=True,
        created_at=now,
        updated_at=now,
        history=[],
    )
    recipes.append(recipe)
    _write_all(recipes, brand_id)
    return get_recipe(recipe.recipe_id, brand_id) or recipe


def update_recipe(recipe_id: str, brand_id: str, **updates: Any) -> ColorRecipe:
    """Update recipe values and bump version; prior values go into history."""
    recipes = list_recipes(brand_id, include_archived=True)
    target = None
    for recipe in recipes:
        if recipe.recipe_id == recipe_id:
            target = recipe
            break
    if target is None:
        raise KeyError(f"Recipe not found: {recipe_id}")

    snapshot = {
        "version": target.version,
        "lighting_defaults": deepcopy(target.lighting_defaults),
        "color_defaults": deepcopy(target.color_defaults),
        "texture_defaults": deepcopy(target.texture_defaults),
        "geometry_defaults": deepcopy(target.geometry_defaults),
        "logo_defaults": deepcopy(target.logo_defaults),
        "export_defaults": deepcopy(target.export_defaults),
        "archived_at": utc_now_iso(),
    }
    target.history.append(snapshot)
    target.version += 1
    for key, value in updates.items():
        if hasattr(target, key) and key not in {"recipe_id", "brand_id", "history", "version"}:
            setattr(target, key, value)
    target.updated_at = utc_now_iso()
    _write_all(recipes, brand_id)
    return get_recipe(recipe_id, brand_id) or target


def duplicate_recipe(recipe_id: str, brand_id: str = DEFAULT_BRAND_ID) -> ColorRecipe:
    source = get_recipe(recipe_id, brand_id)
    if source is None:
        raise KeyError(recipe_id)
    return save_new_recipe(
        brand_id=brand_id,
        display_name=f"{source.display_name} (copy)",
        description=source.description,
        lighting=source.lighting_defaults,
        color=source.color_defaults,
        texture=source.texture_defaults,
        geometry=source.geometry_defaults,
        logo=source.logo_defaults,
        export=source.export_defaults,
    )


def rename_recipe(recipe_id: str, display_name: str, brand_id: str = DEFAULT_BRAND_ID) -> ColorRecipe:
    return update_recipe(recipe_id, brand_id, display_name=display_name.strip())


def archive_recipe(recipe_id: str, brand_id: str = DEFAULT_BRAND_ID) -> ColorRecipe:
    return update_recipe(recipe_id, brand_id, active=False)


def restore_recipe(recipe_id: str, brand_id: str = DEFAULT_BRAND_ID) -> ColorRecipe:
    return update_recipe(recipe_id, brand_id, active=True)


def recipe_snapshot(recipe: ColorRecipe) -> dict[str, Any]:
    """Exact values used at finish time so later recipe edits cannot rewrite history."""
    return {
        "recipe_id": recipe.recipe_id,
        "display_name": recipe.display_name,
        "version": recipe.version,
        "lighting_defaults": deepcopy(recipe.lighting_defaults),
        "color_defaults": deepcopy(recipe.color_defaults),
        "texture_defaults": deepcopy(recipe.texture_defaults),
        "geometry_defaults": deepcopy(recipe.geometry_defaults),
        "logo_defaults": deepcopy(recipe.logo_defaults),
        "export_defaults": deepcopy(recipe.export_defaults),
    }
