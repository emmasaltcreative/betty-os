"""Canonical template / content-piece / render models for BettyOS."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RendererStatus = Literal["ready", "partial", "planned", "manual_only"]
TemplateCategory = Literal["video", "static", "multi_frame", "commercial", "copy"]
ApprovalStatus = Literal["awaiting_review", "approved", "needs_revision", "rejected"]
SaveState = Literal["saved", "unsaved_changes", "saving", "save_failed"]

APPROVAL_STATUSES: tuple[str, ...] = (
    "awaiting_review",
    "approved",
    "needs_revision",
    "rejected",
)


class TemplateRecord(BaseModel):
    template_id: str
    display_name: str
    description: str = ""
    category: str
    supported_platforms: list[str] = Field(default_factory=list)
    supported_aspect_ratios: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    renderer_status: str = "planned"
    renderer_module: str = ""
    renderer_family: str = ""
    version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""


class ContentPieceRecord(BaseModel):
    piece_id: str
    title: str
    platform: str = ""
    objective: str = ""
    format: str = ""
    template_id: str | None = None
    source_assets: list[str] = Field(default_factory=list)
    body_markdown: str = ""
    number: str = ""


class TemplateConfiguration(BaseModel):
    content_piece_id: str
    template_id: str
    source_assets: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None
    overlays: list[dict[str, Any]] = Field(default_factory=list)
    cta: dict[str, Any] = Field(default_factory=dict)
    export_settings: dict[str, Any] = Field(default_factory=dict)
    copy_fields: dict[str, str] = Field(default_factory=dict)


class PieceAssignment(BaseModel):
    piece_id: str
    template_id: str
    primary_template_id: str
    confidence: float = 0.0
    rationale: str = ""
    alternative_template_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    override: bool = False
    updated_at: str = ""


class ApprovalRecord(BaseModel):
    campaign_id: str
    asset_id: str
    template_id: str
    render_version_id: str
    status: str = "awaiting_review"
    note: str = ""
    reviewed_at: str | None = None
    updated_at: str = ""
    item_name: str = ""
    item_type: str = ""
    file_path: str = ""


class ClassificationResult(BaseModel):
    primary_template_id: str
    confidence: float
    rationale: str
    alternative_template_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
