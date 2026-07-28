"""Deterministic static-image finishing pipeline.

Pipeline order (documented):
1. decode and normalize (EXIF orientation, RGB/RGBA)
2. apply geometry (rotate, straighten, crop, aspect fit/fill/pad)
3. apply LUT (if selected)
4. apply light adjustments
5. apply color adjustments
6. apply local tonal approximations (clarity, bloom)
7. apply texture (grain, sharpen, soften, vignette)
8. apply logo
9. resize for export
10. encode
11. validate (caller)
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from studio.brand_assets import get_asset, resolve_asset_path
from studio.luts import apply_cube_to_rgb, get_lut, load_cube_for_record
from studio.models import (
    ASPECT_PRESETS,
    PLATFORM_EXPORT_PRESETS,
    FinishConfiguration,
    LogoConfiguration,
)

SIZE_MODE_PERCENT = {
    "subtle": 12.0,
    "standard": 18.0,
    "prominent": 28.0,
}

PLACEMENT_ANCHORS = {
    "top_left": (0.0, 0.0),
    "top_center": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "center_left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "center_right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom_center": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


def _to_float(img: Image.Image) -> tuple[np.ndarray, np.ndarray | None]:
    if img.mode == "RGBA":
        arr = np.asarray(img).astype(np.float32) / 255.0
        return arr[..., :3], arr[..., 3]
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    return arr, None


def _from_float(rgb: np.ndarray, alpha: np.ndarray | None) -> Image.Image:
    rgb_u8 = (np.clip(rgb, 0, 1) * 255.0).astype(np.uint8)
    if alpha is None:
        return Image.fromarray(rgb_u8, mode="RGB")
    a_u8 = (np.clip(alpha, 0, 1) * 255.0).astype(np.uint8)
    rgba = np.dstack([rgb_u8, a_u8])
    return Image.fromarray(rgba, mode="RGBA")


def load_source_image(path: Path) -> Image.Image:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        elif img.mode == "LA":
            img = img.convert("RGBA")
        elif img.mode == "L":
            img = img.convert("RGB")
        elif img.mode not in {"RGB", "RGBA"}:
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        return img.copy()


def rasterize_logo(path: Path) -> Image.Image:
    path = Path(path)
    if path.suffix.lower() == ".svg":
        png_bytes = _svg_to_png_bytes(path)
        return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return Image.open(path).convert("RGBA")


def _svg_to_png_bytes(path: Path, size: int = 1024) -> bytes:
    """Safe SVG rasterization via rsvg-convert or cairosvg when available."""
    rsvg = _which("rsvg-convert")
    if rsvg:
        proc = subprocess.run(
            [rsvg, "-w", str(size), str(path)],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    try:
        import cairosvg  # type: ignore

        return cairosvg.svg2png(url=str(path), output_width=size)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "SVG logos require rsvg-convert or cairosvg for compositing. "
            "Upload a transparent PNG instead."
        ) from exc


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def apply_geometry(img: Image.Image, cfg: FinishConfiguration) -> Image.Image:
    geo = cfg.geometry
    if abs(geo.rotate_degrees) > 0.01:
        turns = int(geo.rotate_degrees) % 360
        if turns in {90, 180, 270}:
            img = img.rotate(-turns, expand=True)
    if abs(geo.straighten_degrees) > 0.01:
        img = img.rotate(-geo.straighten_degrees, resample=Image.Resampling.BICUBIC, expand=True)

    w, h = img.size
    left = int(np.clip(geo.crop_left, 0, 1) * w)
    top = int(np.clip(geo.crop_top, 0, 1) * h)
    right = int(np.clip(geo.crop_right, 0, 1) * w)
    bottom = int(np.clip(geo.crop_bottom, 0, 1) * h)
    if right <= left + 1 or bottom <= top + 1:
        raise ValueError("Crop region has zero area.")
    if (left, top, right, bottom) != (0, 0, w, h):
        img = img.crop((left, top, right, bottom))

    target_ratio = None
    if geo.aspect_preset != "original" and geo.aspect_preset in ASPECT_PRESETS:
        pair = ASPECT_PRESETS[geo.aspect_preset]
        if pair:
            target_ratio = pair[0] / pair[1]

    preset = PLATFORM_EXPORT_PRESETS.get(geo.platform_preset)
    out_w = geo.output_width
    out_h = geo.output_height
    if preset and preset.get("width") and preset.get("height"):
        out_w = int(preset["width"])
        out_h = int(preset["height"])
        target_ratio = out_w / out_h

    if target_ratio is not None:
        img = _fit_or_fill(img, target_ratio, geo.fit_mode, tuple(geo.pad_color))

    if out_w and out_h:
        img = _resize_exact(img, out_w, out_h, geo.fit_mode, tuple(geo.pad_color))
    return img


def _fit_or_fill(
    img: Image.Image,
    ratio: float,
    mode: str,
    pad_color: tuple[int, int, int],
) -> Image.Image:
    w, h = img.size
    current = w / h
    if mode == "fit":
        if current > ratio:
            new_w = w
            new_h = int(round(w / ratio))
        else:
            new_h = h
            new_w = int(round(h * ratio))
        canvas = Image.new(img.mode if img.mode != "RGB" else "RGB", (new_w, new_h), pad_color + ((255,) if img.mode == "RGBA" else ()))
        if img.mode == "RGBA" and canvas.mode != "RGBA":
            canvas = canvas.convert("RGBA")
        offset = ((new_w - w) // 2, (new_h - h) // 2)
        if img.mode == "RGBA":
            canvas.paste(img, offset, img)
        else:
            canvas.paste(img, offset)
        return canvas
    # fill / crop
    if current > ratio:
        new_w = int(round(h * ratio))
        new_h = h
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, new_h))
    new_w = w
    new_h = int(round(w / ratio))
    top = (h - new_h) // 2
    return img.crop((0, top, new_w, top + new_h))


def _resize_exact(
    img: Image.Image,
    width: int,
    height: int,
    mode: str,
    pad_color: tuple[int, int, int],
) -> Image.Image:
    if mode == "fit":
        fitted = ImageOps.contain(img, (width, height), method=Image.Resampling.LANCZOS)
        canvas_mode = "RGBA" if img.mode == "RGBA" else "RGB"
        fill = pad_color + ((255,) if canvas_mode == "RGBA" else ())
        canvas = Image.new(canvas_mode, (width, height), fill)
        offset = ((width - fitted.width) // 2, (height - fitted.height) // 2)
        if fitted.mode == "RGBA":
            canvas.paste(fitted, offset, fitted)
        else:
            canvas.paste(fitted, offset)
        return canvas
    return ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def apply_light(rgb: np.ndarray, cfg: FinishConfiguration) -> np.ndarray:
    light = cfg.lighting
    out = rgb.copy()
    # Exposure as approximate stops
    if abs(light.exposure) > 1e-6:
        out *= 2.0 ** light.exposure
    if abs(light.brightness) > 1e-6:
        out += light.brightness / 200.0
    if abs(light.contrast) > 1e-6:
        factor = 1.0 + (light.contrast / 100.0)
        out = (out - 0.5) * factor + 0.5
    # Highlights / shadows via luminance masks
    lum = 0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]
    if abs(light.highlights) > 1e-6:
        mask = np.clip((lum - 0.5) * 2.0, 0, 1)[..., None]
        out = out + mask * (light.highlights / 200.0)
    if abs(light.shadows) > 1e-6:
        mask = np.clip((0.5 - lum) * 2.0, 0, 1)[..., None]
        out = out + mask * (light.shadows / 200.0)
    if abs(light.whites) > 1e-6:
        mask = np.clip((lum - 0.7) / 0.3, 0, 1)[..., None]
        out = out + mask * (light.whites / 250.0)
    if abs(light.blacks) > 1e-6:
        mask = np.clip((0.3 - lum) / 0.3, 0, 1)[..., None]
        out = out + mask * (light.blacks / 250.0)
    if abs(light.gamma - 1.0) > 1e-6 and light.gamma > 0.05:
        out = np.power(np.clip(out, 0, 1), 1.0 / light.gamma)
    return np.clip(out, 0, 1)


def apply_color(rgb: np.ndarray, cfg: FinishConfiguration) -> np.ndarray:
    color = cfg.color
    out = rgb.copy()
    if abs(color.temperature) > 1e-6:
        # Warm increases R, decreases B
        t = color.temperature / 200.0
        out[..., 0] += t
        out[..., 2] -= t
    if abs(color.tint) > 1e-6:
        t = color.tint / 200.0
        out[..., 1] -= t
        out[..., 0] += t * 0.5
        out[..., 2] += t * 0.5
    out = np.clip(out, 0, 1)
    if abs(color.saturation) > 1e-6:
        gray = (out[..., 0:1] + out[..., 1:2] + out[..., 2:3]) / 3.0
        out = gray + (out - gray) * (1.0 + color.saturation / 100.0)
    if abs(color.vibrance) > 1e-6:
        sat = out.max(axis=2) - out.min(axis=2)
        protect = np.clip(1.0 - sat, 0, 1)[..., None]
        gray = (out[..., 0:1] + out[..., 1:2] + out[..., 2:3]) / 3.0
        out = gray + (out - gray) * (1.0 + (color.vibrance / 100.0) * protect[..., 0:1])
    if abs(color.fade) > 1e-6:
        fade = color.fade / 100.0
        out = out * (1.0 - fade * 0.35) + fade * 0.35
    if abs(color.black_point_lift) > 1e-6:
        lift = color.black_point_lift / 100.0
        out = out * (1.0 - lift * 0.25) + lift * 0.15
    for i, amount in enumerate((color.red_balance, color.green_balance, color.blue_balance)):
        if abs(amount) > 1e-6:
            out[..., i] += amount / 200.0
    return np.clip(out, 0, 1)


def apply_texture(rgb: np.ndarray, cfg: FinishConfiguration) -> np.ndarray:
    tex = cfg.texture
    out = rgb.copy()
    if abs(tex.clarity) > 1e-6:
        # Local midtone contrast approximation via unsharp of luminance
        img = _from_float(out, None)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=2))
        base = np.asarray(img).astype(np.float32) / 255.0
        blur = np.asarray(blurred).astype(np.float32) / 255.0
        out = np.clip(base + (base - blur) * (tex.clarity / 50.0), 0, 1)
    if abs(tex.bloom) > 1e-6:
        img = _from_float(out, None)
        glow = img.filter(ImageFilter.GaussianBlur(radius=6))
        g = np.asarray(glow).astype(np.float32) / 255.0
        out = np.clip(out * (1.0 - tex.bloom / 200.0) + g * (tex.bloom / 100.0), 0, 1)
    if abs(tex.softening) > 1e-6:
        img = _from_float(out, None)
        soft = img.filter(ImageFilter.GaussianBlur(radius=max(0.3, tex.softening / 25.0)))
        s = np.asarray(soft).astype(np.float32) / 255.0
        mix = min(1.0, tex.softening / 100.0)
        out = out * (1 - mix) + s * mix
    if abs(tex.sharpening) > 1e-6:
        img = _from_float(out, None)
        amount = 1.0 + tex.sharpening / 50.0
        sharp = ImageEnhance.Sharpness(img).enhance(amount)
        out = np.asarray(sharp).astype(np.float32) / 255.0
    if tex.grain_amount > 0.1:
        rng = np.random.default_rng(int(tex.grain_seed))
        h, w, _ = out.shape
        # Scale noise by grain size
        scale = max(1, int(round(tex.grain_size)))
        nh, nw = max(1, h // scale), max(1, w // scale)
        noise = rng.normal(0.0, 1.0, size=(nh, nw, 1)).astype(np.float32)
        if tex.grain_roughness > 0.01:
            chroma = rng.normal(0.0, tex.grain_roughness, size=(nh, nw, 3)).astype(np.float32)
            noise = noise + chroma * 0.35
        noise_img = Image.fromarray(
            ((np.clip(noise[:, :, 0], -3, 3) + 3) / 6 * 255).astype(np.uint8), mode="L"
        )
        noise_img = noise_img.resize((w, h), Image.Resampling.BILINEAR)
        noise_full = (np.asarray(noise_img).astype(np.float32) / 255.0 - 0.5) * 2.0
        strength = tex.grain_amount / 400.0
        out = np.clip(out + noise_full[..., None] * strength, 0, 1)
    if tex.vignette_amount > 0.1:
        h, w, _ = out.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        rx = max(cx, 1.0)
        ry = max(cy, 1.0)
        dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        mid = float(np.clip(tex.vignette_midpoint, 0.05, 0.95))
        feather = max(0.05, float(tex.vignette_feather))
        # Soft falloff beyond midpoint
        t = np.clip((dist - mid) / (feather * (1.2 - mid) + 1e-6), 0, 1)
        strength = (tex.vignette_amount / 100.0) * (t ** 1.5)
        out = out * (1.0 - strength[..., None] * 0.85)
    return np.clip(out, 0, 1)


def logo_box(
    canvas_size: tuple[int, int],
    logo_size: tuple[int, int],
    logo_cfg: LogoConfiguration,
    *,
    safe_margin_px: float,
) -> tuple[int, int]:
    cw, ch = canvas_size
    lw, lh = logo_size
    margin = float(safe_margin_px)
    if logo_cfg.placement == "custom":
        x = int(logo_cfg.custom_x_percent / 100.0 * cw - lw / 2)
        y = int(logo_cfg.custom_y_percent / 100.0 * ch - lh / 2)
    else:
        ax, ay = PLACEMENT_ANCHORS.get(logo_cfg.placement, (1.0, 1.0))
        x = int(ax * (cw - lw))
        y = int(ay * (ch - lh))
        if ax <= 0:
            x = int(margin)
        elif ax >= 1:
            x = int(cw - lw - margin)
        if ay <= 0:
            y = int(margin)
        elif ay >= 1:
            y = int(ch - lh - margin)
    return x, y


def apply_logo(img: Image.Image, cfg: FinishConfiguration, *, brand_id: str) -> Image.Image:
    logo_cfg = cfg.logo
    if logo_cfg.role in {"", "none"} and not logo_cfg.asset_id:
        return img
    asset = None
    if logo_cfg.asset_id:
        asset = get_asset(logo_cfg.asset_id, brand_id)
    elif logo_cfg.role not in {"", "none"}:
        from studio.brand_assets import default_asset_for_role

        asset = default_asset_for_role(logo_cfg.role, brand_id)
    if asset is None:
        return img
    logo = rasterize_logo(resolve_asset_path(asset))

    # Color behavior
    if logo_cfg.color_behavior == "mono_light":
        logo = _monochrome_logo(logo, light=True)
    elif logo_cfg.color_behavior == "mono_dark":
        logo = _monochrome_logo(logo, light=False)
    elif logo_cfg.color_behavior in {"light", "dark"}:
        alt = None
        from studio.brand_assets import default_asset_for_role

        alt = default_asset_for_role(logo_cfg.color_behavior, brand_id)
        if alt is not None:
            logo = rasterize_logo(resolve_asset_path(alt))

    percent = SIZE_MODE_PERCENT.get(logo_cfg.size_mode, logo_cfg.size_percent)
    if logo_cfg.size_mode == "custom":
        percent = logo_cfg.size_percent
    target_w = max(1, int(img.width * (percent / 100.0)))
    aspect = logo.height / max(1, logo.width)
    target_h = max(1, int(target_w * aspect))
    logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Opacity
    if logo_cfg.opacity < 0.999:
        alpha = logo.getchannel("A")
        alpha = alpha.point(lambda p: int(p * float(np.clip(logo_cfg.opacity, 0.1, 1.0))))
        logo.putalpha(alpha)

    if logo_cfg.safe_margin_mode == "percent":
        margin = img.width * (logo_cfg.safe_margin_value / 100.0)
    elif logo_cfg.safe_margin_mode == "pixels":
        margin = logo_cfg.safe_margin_value
    elif logo_cfg.safe_margin_mode == "recipe_default":
        margin = float(cfg.recipe_snapshot.get("logo_defaults", {}).get("safe_margin", asset.default_safe_margin))
    else:
        margin = float(asset.default_safe_margin)

    x, y = logo_box(img.size, logo.size, logo_cfg, safe_margin_px=margin)
    base = img.convert("RGBA")
    base.alpha_composite(logo, dest=(x, y))
    if img.mode != "RGBA":
        return base.convert(img.mode)
    return base


def _monochrome_logo(logo: Image.Image, *, light: bool) -> Image.Image:
    arr = np.asarray(logo).astype(np.float32)
    alpha = arr[..., 3:4] / 255.0
    gray = (0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]) / 255.0
    # Only treat as safe monochrome if chroma is already low or user chose it explicitly
    value = 1.0 if light else 0.0
    rgb = np.full((*gray.shape, 3), value * 255.0, dtype=np.float32)
    out = np.dstack([rgb, alpha[..., 0] * 255.0]).astype(np.uint8)
    return Image.fromarray(out, mode="RGBA")


def process_static_image(
    source: Path,
    config: FinishConfiguration,
    *,
    brand_id: str,
    output_path: Path,
    preview_path: Path | None = None,
    preview_max_edge: int = 1280,
) -> dict[str, Any]:
    """Full-resolution process. Preview proxy is separate and never saved as final."""
    img = load_source_image(source)
    img = apply_geometry(img, config)

    rgb, alpha = _to_float(img)

    if config.lut.lut_id:
        record = get_lut(config.lut.lut_id, brand_id)
        if record is None or record.status != "Ready":
            raise RuntimeError("Selected LUT is not Ready.")
        cube = load_cube_for_record(record)
        rgb = apply_cube_to_rgb(rgb, cube, intensity=config.lut.intensity)

    rgb = apply_light(rgb, config)
    rgb = apply_color(rgb, config)
    rgb = apply_texture(rgb, config)
    img = _from_float(rgb, alpha)
    img = apply_logo(img, config, brand_id=brand_id)

    # Export encode
    fmt = (config.export.format or "png").lower()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    save_img = img
    if fmt in {"jpg", "jpeg"}:
        if save_img.mode == "RGBA":
            background = Image.new("RGB", save_img.size, (250, 247, 241))
            background.paste(save_img, mask=save_img.split()[-1])
            save_img = background
        else:
            save_img = save_img.convert("RGB")
        save_img.save(output_path, format="JPEG", quality=int(config.export.quality), optimize=True)
    elif fmt == "webp":
        save_img.save(
            output_path,
            format="WEBP",
            quality=int(config.export.quality),
            lossless=bool(config.export.preserve_transparency and save_img.mode == "RGBA"),
        )
    else:
        if not config.export.preserve_transparency and save_img.mode == "RGBA":
            background = Image.new("RGB", save_img.size, (250, 247, 241))
            background.paste(save_img, mask=save_img.split()[-1])
            save_img = background
        save_img.save(output_path, format="PNG", optimize=True)

    preview_files: list[Path] = []
    if preview_path is not None:
        preview_path = Path(preview_path)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        proxy = img.copy()
        proxy.thumbnail((preview_max_edge, preview_max_edge), Image.Resampling.LANCZOS)
        if proxy.mode == "RGBA":
            proxy.save(preview_path, format="PNG")
        else:
            proxy.convert("RGB").save(preview_path, format="JPEG", quality=85)
        preview_files.append(preview_path)

    return {
        "ok": True,
        "output_files": [output_path],
        "preview_files": preview_files,
        "width": img.width,
        "height": img.height,
        "technical_notes": {
            "pipeline_order": [
                "decode",
                "geometry",
                "lut",
                "light",
                "color",
                "texture",
                "logo",
                "encode",
            ],
            "preview_max_edge": preview_max_edge,
        },
    }


def process_preview_proxy(
    source: Path,
    config: FinishConfiguration,
    *,
    brand_id: str,
    max_edge: int = 960,
) -> Image.Image:
    """Lower-resolution preview for UI — not used as final output."""
    img = load_source_image(source)
    img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    # Write to memory via pipeline pieces
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Save downscaled as temp source so full pipeline runs at proxy res
        src = tmp_path / "proxy_src.png"
        img.save(src)
        out = tmp_path / "out.png"
        process_static_image(
            src,
            config,
            brand_id=brand_id,
            output_path=out,
            preview_path=None,
            preview_max_edge=max_edge,
        )
        return load_source_image(out)
