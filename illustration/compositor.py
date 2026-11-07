"""Deterministic truth layer.

Anything that must be *exactly* right — the official house mark, the handwritten
signature, the printed label, the product's own geometry — is composited here
from source artwork. It is never asked of a generative model.

Guarantees this module makes:

* Official marks are scaled with their aspect ratio preserved. Never stretched.
* The perfume label is genuinely transparent: alpha is 0 in its negative space
  so the amber glass shows through, and the ghosted repeating house flower sits
  at ~0.5 alpha rather than being painted onto a cream fill.
* Label copy runs lengthwise along the cylinder's long axis.
* The signature is placed below the eau de parfum / size text.
* A notes line is only drawn when the approved label actually has one.
* Every placement is recorded in a :class:`LayerManifest` so QA can assert on
  what was really drawn rather than guessing from pixels.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from illustration.models import CANVAS_PRESETS, LabelSpec, LayerManifest, ProductTruth

# --- font resolution ------------------------------------------------------------

_SERIF_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Georgia.ttf",
)
_SANS_CANDIDATES = (
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


class CompositorError(Exception):
    """A required piece of source artwork is missing or unusable."""


def _font(size: int, *, serif: bool = True) -> ImageFont.FreeTypeFont:
    for path in _SERIF_CANDIDATES if serif else _SANS_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise CompositorError(f"Bad colour: {value}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


HARDWARE_HEX = {
    "gold": "#C9A227",
    "brushed gold": "#BFA14A",
    "silver": "#C0C0C0",
    "chrome": "#CFD4D8",
    "rose gold": "#B76E79",
}


def hardware_hex(finish: str) -> str:
    """Hex for a named hardware finish; gold is the house default."""
    return HARDWARE_HEX.get((finish or "").strip().lower(), "#C9A227")


# --- source artwork -------------------------------------------------------------

def svg_rasterization_available() -> bool:
    try:
        import cairosvg  # noqa: F401, PLC0415
    except Exception:  # noqa: BLE001
        return False
    return True


def load_mark(
    path: Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> Image.Image:
    """Load official artwork as RGBA, preserving aspect ratio.

    Exactly one of ``target_width`` / ``target_height`` drives the scale; the
    other is derived. The house mark is never stretched to fit.
    """
    path = Path(path)
    if not path.is_file():
        raise CompositorError(f"Official artwork is missing: {path.name}")

    if path.suffix.lower() == ".svg":
        if not svg_rasterization_available():
            raise CompositorError(
                f"{path.name} is an SVG but SVG rasterization is unavailable. "
                "Install `cairosvg` (it needs the system cairo library), or add "
                "a high-resolution transparent PNG master of this mark to the "
                "vault. The mark is never re-created by a model."
            )
        import cairosvg  # noqa: PLC0415

        # Never pass BOTH dimensions to the rasteriser: it would scale the mark
        # to the box and distort it. Rasterise on one axis, then contain-fit.
        kwargs: dict[str, int] = {}
        if target_width and target_height:
            kwargs["output_width"] = int(target_width)
        elif target_width:
            kwargs["output_width"] = int(target_width)
        elif target_height:
            kwargs["output_height"] = int(target_height)
        else:
            kwargs["output_width"] = 1024
        payload = cairosvg.svg2png(url=str(path), **kwargs)
        image = Image.open(io.BytesIO(payload)).convert("RGBA")
        if target_width and target_height:
            return _fit_preserving_aspect(image, target_width, target_height)
        return image

    image = Image.open(path).convert("RGBA")
    if target_width and target_height:
        return _fit_preserving_aspect(image, target_width, target_height)
    if target_width:
        ratio = target_width / image.width
        return image.resize(
            (int(target_width), max(1, round(image.height * ratio))), Image.LANCZOS
        )
    if target_height:
        ratio = target_height / image.height
        return image.resize(
            (max(1, round(image.width * ratio)), int(target_height)), Image.LANCZOS
        )
    return image


def _fit_preserving_aspect(image: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Contain inside the box without distortion."""
    scale = min(box_w / image.width, box_h / image.height)
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )


def tint(image: Image.Image, color: str) -> Image.Image:
    """Recolour artwork while keeping its alpha — for approved colourways."""
    rgba = image.convert("RGBA")
    solid = Image.new("RGBA", rgba.size, (*_hex_to_rgb(color), 255))
    solid.putalpha(rgba.getchannel("A"))
    return solid


def set_opacity(image: Image.Image, opacity: float) -> Image.Image:
    """Scale an image's existing alpha by ``opacity``."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
    rgba.putalpha(alpha)
    return rgba


# --- the label ------------------------------------------------------------------

@dataclass
class LabelGeometry:
    width: int
    height: int
    ghost_tile_px: int = 96
    margin_px: int = 28


def build_ghost_repeat(
    mark: Image.Image,
    geometry: LabelGeometry,
    opacity: float,
    *,
    color: str | None = None,
    coverage: float = 0.62,
) -> Image.Image:
    """Repeating four-petal house flower behind the text.

    The result is transparent everywhere the mark is not, so the amber glass
    still reads through. The motif's own alpha is scaled to ``opacity``
    (~0.5) — it is emphatically not a cream fill.
    """
    tile_size = max(8, geometry.ghost_tile_px)
    # The motif occupies only part of its tile, so the repeat reads as a fine
    # ghosted pattern rather than a dense field that fights the text.
    motif_px = max(4, int(tile_size * max(0.1, min(1.0, coverage))))
    tile_mark = _fit_preserving_aspect(mark, motif_px, motif_px)
    if color:
        tile_mark = tint(tile_mark, color)
    tile = Image.new("RGBA", (tile_size, tile_size), (0, 0, 0, 0))
    tile.paste(
        tile_mark,
        (
            (tile_size - tile_mark.width) // 2,
            (tile_size - tile_mark.height) // 2,
        ),
        tile_mark,
    )
    tile = set_opacity(tile, opacity)

    layer = Image.new("RGBA", (geometry.width, geometry.height), (0, 0, 0, 0))
    for y in range(0, geometry.height, tile_size):
        offset = (tile_size // 2) if (y // tile_size) % 2 else 0
        for x in range(-tile_size, geometry.width + tile_size, tile_size):
            layer.alpha_composite(tile, (x + offset, y))
    return layer


def build_label(
    product: ProductTruth,
    geometry: LabelGeometry,
    *,
    mark: Image.Image | None = None,
    signature: Image.Image | None = None,
    manifest: LayerManifest | None = None,
) -> Image.Image:
    """Compose the transparent label in its natural reading orientation.

    Returned image is a wide strip: text reads left-to-right. Rotate it to run
    lengthwise along a vertical cylinder.
    """
    spec: LabelSpec = product.label
    manifest = manifest if manifest is not None else LayerManifest()

    # Fully transparent base — the amber glass is what shows through.
    label = Image.new("RGBA", (geometry.width, geometry.height), (0, 0, 0, 0))
    manifest.add(
        "label_base",
        transparent=True,
        alpha_in_negative_space=0,
        width=geometry.width,
        height=geometry.height,
    )

    if spec.transparent is not True:
        raise CompositorError(
            "This product's label spec is not transparent; the amber "
            "show-through rule does not apply. Check the product profile."
        )

    # Ghosted repeating house flower behind the text.
    if mark is not None:
        ghost = build_ghost_repeat(
            mark,
            geometry,
            spec.ghost_motif_opacity,
            color=spec.ghost_motif_color,
        )
        label.alpha_composite(ghost)
        manifest.add(
            "ghost_motif_repeat",
            opacity=spec.ghost_motif_opacity,
            tile_px=geometry.ghost_tile_px,
            color=spec.ghost_motif_color,
            source="official_mark",
        )

    draw = ImageDraw.Draw(label)
    inner_w = geometry.width - 2 * geometry.margin_px
    cursor_y = geometry.margin_px

    # Gold primary flower mark, aspect preserved.
    if mark is not None:
        mark_h = int(geometry.height * 0.22)
        primary = tint(load_mark_like(mark, target_height=mark_h), spec.mark_color)
        label.alpha_composite(
            primary, ((geometry.width - primary.width) // 2, cursor_y)
        )
        manifest.add(
            "house_mark",
            color=spec.mark_color,
            width=primary.width,
            height=primary.height,
            aspect_preserved=True,
        )
        cursor_y += primary.height + int(geometry.height * 0.04)

    # White primary title.
    title_font = _font(max(12, int(geometry.height * 0.155)), serif=True)
    title_rgb = _hex_to_rgb(spec.title_color)
    _draw_centered(draw, spec.title_text, title_font, geometry.width, cursor_y, title_rgb)
    title_h = _text_height(draw, spec.title_text, title_font)
    manifest.add("label_title", text=spec.title_text, color=spec.title_color)
    cursor_y += title_h + int(geometry.height * 0.035)

    # White EAU DE PARFUM / size lines.
    sub_font = _font(max(9, int(geometry.height * 0.072)), serif=False)
    sub_rgb = _hex_to_rgb(spec.subtitle_color)
    edp_bottom_y = cursor_y
    for line in spec.subtitle_lines:
        spaced = " ".join(line) if line.isupper() and len(line) <= 20 else line
        _draw_centered(draw, spaced, sub_font, geometry.width, cursor_y, sub_rgb)
        line_h = _text_height(draw, spaced, sub_font)
        cursor_y += line_h + int(geometry.height * 0.018)
        edp_bottom_y = cursor_y
    manifest.add(
        "label_subtitles",
        lines=list(spec.subtitle_lines),
        color=spec.subtitle_color,
        bottom_y=edp_bottom_y,
    )

    # Gold handwritten signature — strictly BELOW the EDP / size text.
    if signature is not None:
        sig_w = int(inner_w * 0.62)
        sig = tint(load_mark_like(signature, target_width=sig_w), spec.signature_color)
        sig_y = edp_bottom_y + int(geometry.height * 0.02)
        max_y = geometry.height - geometry.margin_px - sig.height
        sig_y = min(sig_y, max(edp_bottom_y, max_y))
        label.alpha_composite(sig, ((geometry.width - sig.width) // 2, sig_y))
        manifest.add(
            "house_signature",
            color=spec.signature_color,
            y=sig_y,
            edp_bottom_y=edp_bottom_y,
            below_edp=sig_y >= edp_bottom_y,
            aspect_preserved=True,
        )

    # A notes line is drawn only when the approved label truly has one.
    if spec.notes_line:
        notes_font = _font(max(8, int(geometry.height * 0.055)), serif=False)
        _draw_centered(
            draw,
            spec.notes_line,
            notes_font,
            geometry.width,
            geometry.height - geometry.margin_px - _text_height(draw, spec.notes_line, notes_font),
            sub_rgb,
        )
        manifest.add("label_notes_line", text=spec.notes_line, invented=False)
    else:
        manifest.add("label_notes_line", text=None, invented=False, omitted=True)

    manifest.add("label_orientation", orientation=spec.copy_orientation)
    return label


def load_mark_like(
    image: Image.Image,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> Image.Image:
    """Rescale an already-loaded mark, preserving aspect ratio."""
    if target_width:
        ratio = target_width / image.width
        return image.resize(
            (int(target_width), max(1, round(image.height * ratio))), Image.LANCZOS
        )
    if target_height:
        ratio = target_height / image.height
        return image.resize(
            (max(1, round(image.width * ratio)), int(target_height)), Image.LANCZOS
        )
    return image.copy()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    width: int,
    y: int,
    color: tuple[int, int, int],
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) // 2 - box[0], y - box[1]), text, font=font, fill=(*color, 255))


def _text_height(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[3] - box[1]


# --- cylinder placement ---------------------------------------------------------

def cylindrical_warp(label: Image.Image, *, curvature: float = 0.22) -> Image.Image:
    """Shade a flat label so it reads as wrapped on a cylinder.

    Columns toward the silhouette edges darken and compress slightly. This is a
    shading/compression approximation for preview use — it is not a claim of
    photogrammetric accuracy, and QA records it as such.
    """
    rgba = label.convert("RGBA")
    width, height = rgba.size
    if width < 4:
        return rgba

    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    strip = max(1, width // 64)
    for x in range(0, width, strip):
        column = rgba.crop((x, 0, min(x + strip, width), height))
        # Normalised distance from centre, 0 at middle, 1 at the edges.
        t = abs(((x + strip / 2) / width) * 2 - 1)
        shade = 1.0 - curvature * (t ** 1.6)
        column = ImageEnhance.Brightness(column).enhance(max(0.45, shade))
        # Horizontal compression toward the edges.
        new_w = max(1, int(column.width * (1.0 - 0.35 * (t ** 2))))
        column = column.resize((new_w, height), Image.LANCZOS)
        offset = x + (strip - new_w) // 2
        out.alpha_composite(column, (max(0, offset), 0))
    return out


def place_label_lengthwise(
    base: Image.Image,
    label: Image.Image,
    *,
    bottle_box: tuple[int, int, int, int],
    manifest: LayerManifest | None = None,
    curvature: float = 0.22,
) -> Image.Image:
    """Place the label running along the cylinder's long axis.

    ``bottle_box`` is ``(left, top, right, bottom)`` of the bottle's glass body
    in ``base``. For an upright bottle the label strip is rotated so its copy
    reads lengthwise rather than around the circumference.
    """
    manifest = manifest if manifest is not None else LayerManifest()
    left, top, right, bottom = bottle_box
    box_w, box_h = right - left, bottom - top
    if box_w <= 0 or box_h <= 0:
        raise CompositorError("Bottle bounds are empty; cannot anchor the label.")

    upright = box_h >= box_w
    strip = cylindrical_warp(label, curvature=curvature)
    if upright:
        strip = strip.rotate(90, expand=True, resample=Image.BICUBIC)

    # Fit inside the glass body without distortion.
    target_w = int(box_w * 0.74)
    target_h = int(box_h * 0.56)
    strip = _fit_preserving_aspect(strip, target_w, target_h)

    out = base.convert("RGBA").copy()
    x = left + (box_w - strip.width) // 2
    y = top + (box_h - strip.height) // 2
    out.alpha_composite(strip, (x, y))

    manifest.add(
        "product_label",
        orientation="lengthwise",
        rotated_degrees=90 if upright else 0,
        anchored_to_bottle_bounds=True,
        bottle_box=[left, top, right, bottom],
        placed_at=[x, y],
        size=[strip.width, strip.height],
        warp="cylindrical_shading_approximation",
        geometric_accuracy="approximate",
    )
    return out


# --- schematic preview (no verified mockup) -------------------------------------

def render_bottle_schematic(
    product: ProductTruth,
    size: tuple[int, int] = (720, 1800),
    *,
    manifest: LayerManifest | None = None,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """A deterministic amber cylinder with gold hardware at both ends.

    This is a **schematic**, drawn from the product profile so label geometry
    can be previewed and QA can assert both gold ends exist as real layers. It
    is explicitly not a product photograph and never earns
    ``product_accurate_verified``.
    """
    manifest = manifest if manifest is not None else LayerManifest()
    width, height = size
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    cap_h = int(height * 0.13)
    body_top, body_bottom = cap_h, height - cap_h
    amber = (173, 103, 32, 255)
    amber_light = (214, 148, 61, 255)
    gold = _hex_to_rgb(hardware_hex(product.hardware_finish))

    # Amber glass body with a soft vertical gradient for roundness.
    for x in range(width):
        t = abs((x / max(1, width - 1)) * 2 - 1)
        blend = t ** 1.5
        color = tuple(
            int(amber_light[i] * (1 - blend) + amber[i] * blend) for i in range(3)
        )
        draw.line([(x, body_top), (x, body_bottom)], fill=(*color, 255))
    manifest.add("bottle_body", glass_color=product.glass_color, schematic=True)

    # Gold hardware at BOTH ends — separate, assertable layers.
    draw.rounded_rectangle(
        [0, 0, width - 1, cap_h], radius=int(width * 0.12), fill=(*gold, 255)
    )
    manifest.add(
        "gold_end_top",
        finish=product.hardware_finish,
        mechanism=product.mechanisms[0] if product.mechanisms else "",
        present=True,
    )
    draw.rounded_rectangle(
        [0, height - cap_h, width - 1, height - 1],
        radius=int(width * 0.12),
        fill=(*gold, 255),
    )
    manifest.add(
        "gold_end_bottom",
        finish=product.hardware_finish,
        mechanism=product.mechanisms[1] if len(product.mechanisms) > 1 else "",
        present=True,
    )

    # Specular highlight.
    highlight = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(highlight).rectangle(
        [int(width * 0.18), body_top + 8, int(width * 0.3), body_bottom - 8],
        fill=(255, 255, 255, 46),
    )
    canvas.alpha_composite(highlight.filter(ImageFilter.GaussianBlur(8)))
    manifest.add("bottle_highlight", schematic=True)

    return canvas, (0, body_top, width, body_bottom)


# --- canvas and export ----------------------------------------------------------

def fit_to_canvas(
    image: Image.Image,
    canvas: str = "shopify_pdp_square",
    *,
    background: tuple[int, int, int] = (246, 241, 231),
    mode: str = "cover",
) -> Image.Image:
    """Reach the exact canvas size without ever stretching the source.

    ``cover`` scales up and centre-crops; ``contain`` pads onto the cream
    ground. Aspect ratio is preserved in both.
    """
    target_w, target_h = CANVAS_PRESETS.get(canvas, CANVAS_PRESETS["shopify_pdp_square"])
    rgb = image.convert("RGB")
    if mode == "contain":
        fitted = _fit_preserving_aspect(rgb.convert("RGBA"), target_w, target_h).convert("RGB")
        out = Image.new("RGB", (target_w, target_h), background)
        out.paste(fitted, ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2))
        return out

    scale = max(target_w / rgb.width, target_h / rgb.height)
    scaled = rgb.resize(
        (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - target_w) // 2
    top = (scaled.height - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def export(
    image: Image.Image,
    out_dir: Path,
    basename: str,
    *,
    canvas: str = "shopify_pdp_square",
    jpg_quality: int = 95,
    include_webp: bool = False,
    manifest: LayerManifest | None = None,
) -> dict[str, Path]:
    """Write real, decodable JPG and PNG at the exact canvas size."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target_w, target_h = CANVAS_PRESETS.get(canvas, CANVAS_PRESETS["shopify_pdp_square"])
    final = image.convert("RGB")
    if final.size != (target_w, target_h):
        final = fit_to_canvas(final, canvas)

    written: dict[str, Path] = {}
    jpg = out_dir / f"{basename}.jpg"
    final.save(jpg, "JPEG", quality=jpg_quality, subsampling=0, optimize=True)
    written["jpg"] = jpg

    png = out_dir / f"{basename}.png"
    final.save(png, "PNG", optimize=True)
    written["png"] = png

    if include_webp:
        webp = out_dir / f"{basename}.webp"
        final.save(webp, "WEBP", quality=92, method=6)
        written["webp"] = webp

    if manifest is not None:
        manifest.add(
            "export",
            canvas=canvas,
            size=[target_w, target_h],
            files={k: v.name for k, v in written.items()},
        )
    return written


def safe_area_report(
    canvas: str, safe_percent: float = 9.0
) -> dict[str, int | float]:
    """Pixel bounds of the mobile-crop safe area for the UI overlay."""
    width, height = CANVAS_PRESETS.get(canvas, CANVAS_PRESETS["shopify_pdp_square"])
    inset_x = int(width * safe_percent / 100)
    inset_y = int(height * safe_percent / 100)
    return {
        "canvas_width": width,
        "canvas_height": height,
        "safe_percent": safe_percent,
        "left": inset_x,
        "top": inset_y,
        "right": width - inset_x,
        "bottom": height - inset_y,
    }


def mobile_crop_preview(
    image: Image.Image, *, ratio: tuple[int, int] = (4, 5)
) -> Image.Image:
    """Centre crop at a tighter ratio, to check a mobile PDP crop."""
    rgb = image.convert("RGB")
    target = ratio[0] / ratio[1]
    current = rgb.width / rgb.height
    if current > target:
        new_w = int(rgb.height * target)
        left = (rgb.width - new_w) // 2
        return rgb.crop((left, 0, left + new_w, rgb.height))
    new_h = int(rgb.width / target)
    top = (rgb.height - new_h) // 2
    return rgb.crop((0, top, rgb.width, top + new_h))
