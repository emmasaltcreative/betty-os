"""Apply a Color Recipe into a FinishConfiguration."""

from __future__ import annotations

from studio.models import (
    ColorConfiguration,
    ExportConfiguration,
    FinishConfiguration,
    GeometryConfiguration,
    LightingConfiguration,
    LogoConfiguration,
    TextureConfiguration,
)
from studio.recipes import ColorRecipe, recipe_snapshot


def apply_recipe_to_config(recipe: ColorRecipe, base: FinishConfiguration | None = None) -> FinishConfiguration:
    cfg = base or FinishConfiguration()
    lighting = {**cfg.lighting.to_dict(), **(recipe.lighting_defaults or {})}
    color = {**cfg.color.to_dict(), **(recipe.color_defaults or {})}
    texture = {**cfg.texture.to_dict(), **(recipe.texture_defaults or {})}
    geometry = {**cfg.geometry.to_dict(), **(recipe.geometry_defaults or {})}
    logo = {**cfg.logo.to_dict(), **(recipe.logo_defaults or {})}
    export = {**cfg.export.to_dict(), **(recipe.export_defaults or {})}
    # Preserve pad_color tuple
    if isinstance(geometry.get("pad_color"), list):
        geometry["pad_color"] = tuple(geometry["pad_color"])
    return FinishConfiguration(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.version,
        recipe_snapshot=recipe_snapshot(recipe),
        logo=LogoConfiguration.from_dict(logo),
        lighting=LightingConfiguration.from_dict(lighting),
        color=ColorConfiguration.from_dict(color),
        texture=TextureConfiguration.from_dict(texture),
        geometry=GeometryConfiguration.from_dict(geometry),
        lut=cfg.lut,
        export=ExportConfiguration.from_dict(export),
        video=cfg.video,
        acknowledged_warnings=list(cfg.acknowledged_warnings),
    )
