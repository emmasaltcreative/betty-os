"""Studio data models — finish configs, brand assets, recipes, LUTs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


LOGO_ROLES = (
    "primary",
    "secondary",
    "wordmark",
    "emblem",
    "monogram",
    "watermark",
    "light",
    "dark",
)

LOGO_PLACEMENTS = (
    "top_left",
    "top_center",
    "top_right",
    "center_left",
    "center",
    "center_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "custom",
)

FINISH_STATUSES = ("draft", "processing", "ready_for_review", "failed", "archived")
APPROVAL_STATUSES = (
    "not_submitted",
    "awaiting_review",
    "approved",
    "needs_revision",
    "rejected",
)
VALIDATION_OUTCOMES = ("pass", "warning", "fail")
LUT_STATUSES = ("Ready", "Invalid File", "Unsupported", "Archived")
CAPABILITY_STATUSES = ("Ready", "Partial", "Setup Required", "Planned", "Unavailable")

ASPECT_PRESETS = {
    "original": None,
    "9:16": (9, 16),
    "4:5": (4, 5),
    "1:1": (1, 1),
    "2:3": (2, 3),
    "3:2": (3, 2),
    "16:9": (16, 9),
}

PLATFORM_EXPORT_PRESETS = {
    "instagram_reel": {"label": "Instagram Reel", "width": 1080, "height": 1920},
    "instagram_feed": {"label": "Instagram Feed", "width": 1080, "height": 1350},
    "instagram_square": {"label": "Instagram Square", "width": 1080, "height": 1080},
    "pinterest_pin": {"label": "Pinterest Pin", "width": 1000, "height": 1500},
    "story": {"label": "Story", "width": 1080, "height": 1920},
    "email_hero": {"label": "Email Hero", "width": 1200, "height": 600},
    "original": {"label": "Original Resolution", "width": None, "height": None},
}


@dataclass
class LogoConfiguration:
    role: str = "none"  # none | primary | ...
    asset_id: str | None = None
    placement: str = "bottom_right"
    size_mode: str = "standard"  # subtle | standard | prominent | custom
    size_percent: float = 18.0
    opacity: float = 0.85
    safe_margin_mode: str = "asset_default"  # asset_default | recipe_default | pixels | percent
    safe_margin_value: float = 24.0
    color_behavior: str = "original"  # original | light | dark | mono_light | mono_dark
    custom_x_percent: float = 50.0
    custom_y_percent: float = 50.0
    # Video timing
    timing_mode: str = "full"  # full | opening | closing | custom
    start_seconds: float = 0.0
    end_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LogoConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class LightingConfiguration:
    exposure: float = 0.0  # approx stops, mapped honestly
    brightness: float = 0.0  # -100..100 relative
    contrast: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    gamma: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LightingConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ColorConfiguration:
    temperature: float = 0.0  # -100..100 cool..warm
    tint: float = 0.0  # -100..100 green..magenta
    saturation: float = 0.0
    vibrance: float = 0.0
    fade: float = 0.0
    black_point_lift: float = 0.0
    red_balance: float = 0.0
    green_balance: float = 0.0
    blue_balance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ColorConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class TextureConfiguration:
    grain_amount: float = 0.0
    grain_size: float = 1.0
    grain_roughness: float = 0.5
    grain_seed: int = 42
    sharpening: float = 0.0
    softening: float = 0.0
    clarity: float = 0.0
    bloom: float = 0.0
    vignette_amount: float = 0.0
    vignette_feather: float = 0.5
    vignette_midpoint: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TextureConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class GeometryConfiguration:
    aspect_preset: str = "original"
    crop_mode: str = "none"  # none | free | fill | fit
    crop_left: float = 0.0  # normalized 0..1
    crop_top: float = 0.0
    crop_right: float = 1.0
    crop_bottom: float = 1.0
    rotate_degrees: float = 0.0  # 0/90/180/270
    straighten_degrees: float = 0.0  # fine -15..15
    output_width: int | None = None
    output_height: int | None = None
    fit_mode: str = "fill"  # fill | fit | pad
    pad_color: tuple[int, int, int] = (250, 247, 241)
    platform_preset: str = "original"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pad_color"] = list(self.pad_color)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GeometryConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        if "pad_color" in payload and isinstance(payload["pad_color"], list):
            payload["pad_color"] = tuple(payload["pad_color"])  # type: ignore[assignment]
        return cls(**payload)


@dataclass
class LutConfiguration:
    lut_id: str | None = None
    intensity: float = 1.0  # 0..1 when blending supported

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LutConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ExportConfiguration:
    format: str = "png"  # png | jpg | webp | mp4
    quality: int = 92
    preserve_transparency: bool = True
    strip_metadata: bool = False
    # Video
    fps: float | None = None
    codec: str = "libx264"
    quality_preset: str = "medium"
    bitrate: str = "8M"
    audio_normalize: bool = True
    faststart: bool = True
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExportConfiguration:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class VideoAdjustments:
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    temperature: float = 0.0
    fade: float = 0.0
    grain: float = 0.0
    sharpen: float = 0.0
    vignette: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> VideoAdjustments:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class FinishConfiguration:
    """Full finish draft / finished-version configuration."""

    recipe_id: str | None = None
    recipe_version: int = 1
    recipe_snapshot: dict[str, Any] = field(default_factory=dict)
    logo: LogoConfiguration = field(default_factory=LogoConfiguration)
    lighting: LightingConfiguration = field(default_factory=LightingConfiguration)
    color: ColorConfiguration = field(default_factory=ColorConfiguration)
    texture: TextureConfiguration = field(default_factory=TextureConfiguration)
    geometry: GeometryConfiguration = field(default_factory=GeometryConfiguration)
    lut: LutConfiguration = field(default_factory=LutConfiguration)
    export: ExportConfiguration = field(default_factory=ExportConfiguration)
    video: VideoAdjustments = field(default_factory=VideoAdjustments)
    acknowledged_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_version": self.recipe_version,
            "recipe_snapshot": self.recipe_snapshot,
            "logo_configuration": self.logo.to_dict(),
            "lighting_configuration": self.lighting.to_dict(),
            "color_configuration": self.color.to_dict(),
            "texture_configuration": self.texture.to_dict(),
            "geometry_configuration": self.geometry.to_dict(),
            "lut_configuration": self.lut.to_dict(),
            "export_configuration": self.export.to_dict(),
            "video_configuration": self.video.to_dict(),
            "acknowledged_warnings": list(self.acknowledged_warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FinishConfiguration:
        if not data:
            return cls()
        return cls(
            recipe_id=data.get("recipe_id"),
            recipe_version=int(data.get("recipe_version") or 1),
            recipe_snapshot=dict(data.get("recipe_snapshot") or {}),
            logo=LogoConfiguration.from_dict(data.get("logo_configuration")),
            lighting=LightingConfiguration.from_dict(data.get("lighting_configuration")),
            color=ColorConfiguration.from_dict(data.get("color_configuration")),
            texture=TextureConfiguration.from_dict(data.get("texture_configuration")),
            geometry=GeometryConfiguration.from_dict(data.get("geometry_configuration")),
            lut=LutConfiguration.from_dict(data.get("lut_configuration")),
            export=ExportConfiguration.from_dict(data.get("export_configuration")),
            video=VideoAdjustments.from_dict(data.get("video_configuration")),
            acknowledged_warnings=list(data.get("acknowledged_warnings") or []),
        )


@dataclass
class FinishRecord:
    finish_version_id: str
    campaign_id: str
    content_piece_id: str | None
    template_id: str
    parent_render_version_id: str
    parent_finish_version_id: str | None
    source_asset_id: str | None
    source_output_id: str | None
    source_file: str
    media_type: str  # static | video
    recipe_id: str | None
    recipe_version: int
    logo_configuration: dict[str, Any]
    lighting_configuration: dict[str, Any]
    color_configuration: dict[str, Any]
    texture_configuration: dict[str, Any]
    geometry_configuration: dict[str, Any]
    lut_configuration: dict[str, Any]
    export_configuration: dict[str, Any]
    video_configuration: dict[str, Any]
    output_files: list[str]
    preview_files: list[str]
    validation_results: dict[str, Any]
    status: str
    approval_status: str
    created_at: str
    updated_at: str
    failure_reason: str | None = None
    ffmpeg_command: list[str] | None = None
    technical_notes: dict[str, Any] = field(default_factory=dict)
    edit_decision: dict[str, Any] = field(default_factory=dict)
    execution_report: dict[str, Any] = field(default_factory=dict)
    revision_note: str | None = None
    creative_review_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinishRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class BrandAssetRecord:
    asset_id: str
    brand_id: str
    display_name: str
    role: str
    file_path: str
    original_filename: str
    mime_type: str
    width: int | None
    height: int | None
    aspect_ratio: float | None
    has_transparency: bool
    preferred_background: str
    minimum_display_width: int
    default_opacity: float
    default_size_percentage: float
    allowed_placements: list[str]
    prohibited_placements: list[str]
    default_safe_margin: float
    active: bool
    is_default_for_role: bool
    created_at: str
    updated_at: str
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrandAssetRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ColorRecipe:
    recipe_id: str
    brand_id: str
    display_name: str
    description: str
    suitable_media_types: list[str]
    suitable_content_types: list[str]
    suitable_platforms: list[str]
    lighting_defaults: dict[str, Any]
    color_defaults: dict[str, Any]
    texture_defaults: dict[str, Any]
    geometry_defaults: dict[str, Any]
    logo_defaults: dict[str, Any]
    export_defaults: dict[str, Any]
    version: int
    active: bool
    created_at: str
    updated_at: str
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColorRecipe:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class LutRecord:
    lut_id: str
    brand_id: str
    display_name: str
    file_path: str
    original_filename: str
    format: str
    cube_size: int | None
    domain_min: list[float]
    domain_max: list[float]
    default_intensity: float
    suitable_use_cases: list[str]
    status: str
    created_at: str
    updated_at: str
    validation_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LutRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ValidationItem:
    code: str
    outcome: str  # pass | warning | fail
    message: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
