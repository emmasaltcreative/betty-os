"""Template package exports."""

from src.templates.classifier import classify_content_piece
from src.templates.models import (
    APPROVAL_STATUSES,
    ApprovalRecord,
    ClassificationResult,
    ContentPieceRecord,
    PieceAssignment,
    TemplateConfiguration,
    TemplateRecord,
)
from src.templates.registry import (
    LEGACY_FOLDER_TO_TEMPLATE,
    get_template,
    list_templates,
    load_registry,
    template_id_for_legacy_folder,
)

__all__ = [
    "APPROVAL_STATUSES",
    "ApprovalRecord",
    "ClassificationResult",
    "ContentPieceRecord",
    "LEGACY_FOLDER_TO_TEMPLATE",
    "PieceAssignment",
    "TemplateConfiguration",
    "TemplateRecord",
    "classify_content_piece",
    "get_template",
    "list_templates",
    "load_registry",
    "template_id_for_legacy_folder",
]
