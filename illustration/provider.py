"""Swappable image generation / edit adapter.

The UI never talks to a vendor SDK directly, so the engine can be replaced
without refactoring screens. Two adapters ship:

``NullProvider``
    Active whenever no image API is configured. It reports itself as
    unavailable and *raises* rather than returning a fake success, so the UI can
    still curate assets, write a brief and preview deterministic overlays
    without ever showing a false "Generate" success (brief §11).

``OpenAIImageProvider``
    Thin adapter over the OpenAI Images API. Model id, endpoint behaviour and
    pricing are read from configuration rather than hardcoded, because the
    account's available models decide what is actually callable. Verify the
    current Images API docs and the connected account's model list before
    trusting the defaults here.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

DEFAULT_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (2, 4, 8)


class ProviderError(Exception):
    """Image provider call failed."""


class ProviderUnavailable(ProviderError):
    """No image API is configured, or the requested capability is missing."""


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 2048
    height: int = 2048
    n: int = 1
    reference_paths: list[Path] = field(default_factory=list)
    mask_path: Path | None = None
    source_path: Path | None = None       # set for an edit
    quality: str = "high"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_edit(self) -> bool:
        return self.source_path is not None


@dataclass
class ImageResult:
    images: list[bytes]
    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    source_width: int | None = None
    source_height: int | None = None


@dataclass
class CostEstimate:
    currency: str = "USD"
    per_image: float | None = None
    total: float | None = None
    basis: str = ""
    is_known: bool = False

    def describe(self) -> str:
        if not self.is_known or self.total is None:
            return (
                "Cost unknown — this adapter has no confirmed price for the "
                "selected model. Check your provider dashboard before generating."
            )
        return f"≈ {self.currency} {self.total:.3f} for this request ({self.basis})"


class ImageProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...
    def supports_edit(self) -> bool: ...
    def supports_mask(self) -> bool: ...
    def estimate_cost(self, request: ImageRequest) -> CostEstimate: ...
    def generate(self, request: ImageRequest) -> ImageResult: ...


class NullProvider:
    """Honest no-op. Curation and deterministic compositing still work."""

    name = "none"

    def is_configured(self) -> bool:
        return False

    def supports_edit(self) -> bool:
        return False

    def supports_mask(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return (
            "No image generation provider is configured. Set an image provider "
            "API key to enable Generate Draft. You can still curate vault "
            "assets, assemble a brief and preview deterministic label and mark "
            "overlays."
        )

    def estimate_cost(self, request: ImageRequest) -> CostEstimate:
        return CostEstimate(basis="no provider configured", is_known=False)

    def generate(self, request: ImageRequest) -> ImageResult:
        raise ProviderUnavailable(self.unavailable_reason())


class OpenAIImageProvider:
    """Adapter over the OpenAI Images API.

    ``model`` and the per-image price come from environment configuration:

    - ``OPENAI_API_KEY``            — required
    - ``BETTY_OS_IMAGE_MODEL``      — final-quality model id
    - ``BETTY_OS_IMAGE_MODEL_DRAFT``— faster draft model id
    - ``BETTY_OS_IMAGE_PRICE_USD``  — per-image price, for the cost estimate

    Nothing here asserts that a given model exists on the connected account;
    :meth:`generate` surfaces the provider's own error if it does not.
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str | None = None,
        draft_model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model or os.getenv("BETTY_OS_IMAGE_MODEL", "").strip()
        self._draft_model = (
            draft_model or os.getenv("BETTY_OS_IMAGE_MODEL_DRAFT", "").strip()
        )
        self._timeout = timeout

    # --- capability ---------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip()) and bool(self.model())

    def model(self, *, draft: bool = False) -> str:
        if draft and self._draft_model:
            return self._draft_model
        return self._model

    def supports_edit(self) -> bool:
        return True

    def supports_mask(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            return "OPENAI_API_KEY is not set."
        if not self.model():
            return (
                "No image model is configured. Set BETTY_OS_IMAGE_MODEL to a "
                "model id your account can call."
            )
        return ""

    # --- cost ---------------------------------------------------------------

    def estimate_cost(self, request: ImageRequest) -> CostEstimate:
        raw = os.getenv("BETTY_OS_IMAGE_PRICE_USD", "").strip()
        if not raw:
            return CostEstimate(
                basis="BETTY_OS_IMAGE_PRICE_USD is not set", is_known=False
            )
        try:
            per_image = float(raw)
        except ValueError:
            return CostEstimate(
                basis="BETTY_OS_IMAGE_PRICE_USD is not a number", is_known=False
            )
        return CostEstimate(
            per_image=per_image,
            total=per_image * max(1, request.n),
            basis=f"{request.n} × configured per-image price",
            is_known=True,
        )

    # --- call ---------------------------------------------------------------

    def _client(self):
        try:
            from openai import OpenAI  # noqa: PLC0415 — optional dependency
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable(
                "The `openai` package is not installed. Add it to "
                "requirements.txt to enable this provider."
            ) from exc
        return OpenAI(timeout=self._timeout)

    def generate(self, request: ImageRequest) -> ImageResult:
        if not self.is_configured():
            raise ProviderUnavailable(self.unavailable_reason())

        import base64

        client = self._client()
        model = self.model()
        size = f"{request.width}x{request.height}"
        params: dict[str, Any] = {
            "model": model,
            "prompt": _merge_negative(request),
            "size": size,
            "n": request.n,
        }
        params.update(request.extra)

        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                if request.is_edit:
                    response = self._call_edit(client, request, params)
                else:
                    response = client.images.generate(**params)
                images: list[bytes] = []
                for item in getattr(response, "data", []) or []:
                    payload = getattr(item, "b64_json", None)
                    if payload:
                        images.append(base64.b64decode(payload))
                if not images:
                    raise ProviderError(
                        "Provider returned no image data. Nothing was saved."
                    )
                return ImageResult(
                    images=images,
                    provider=self.name,
                    model=model,
                    params={k: v for k, v in params.items() if k != "prompt"},
                    usage=_usage_of(response),
                )
            except ProviderUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 — adapter boundary
                last_error = exc
                if not _is_transient(exc) or attempt == MAX_ATTEMPTS - 1:
                    break
                time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])

        raise ProviderError(
            f"Image generation failed after {MAX_ATTEMPTS} attempt(s): {last_error}"
        ) from last_error

    def _call_edit(self, client, request: ImageRequest, params: dict[str, Any]):
        """Reference/mask edit. Handles are closed before returning."""
        handles: list[Any] = []
        try:
            source = request.source_path
            if source is None:
                raise ProviderError("An edit requires a source image.")
            primary = Path(source).open("rb")
            handles.append(primary)
            call: dict[str, Any] = dict(params)
            call.pop("n", None)
            references = [Path(p) for p in request.reference_paths]
            if references:
                extra_handles = [p.open("rb") for p in references]
                handles.extend(extra_handles)
                call["image"] = [primary, *extra_handles]
            else:
                call["image"] = primary
            if request.mask_path is not None:
                mask = Path(request.mask_path).open("rb")
                handles.append(mask)
                call["mask"] = mask
            call["n"] = request.n
            return client.images.edit(**call)
        finally:
            for handle in handles:
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass


def _merge_negative(request: ImageRequest) -> str:
    """The Images API has no negative-prompt field; fold it into the prompt."""
    if not request.negative_prompt.strip():
        return request.prompt
    return f"{request.prompt}\n\n{request.negative_prompt.strip()}"


def _usage_of(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    for attr in ("model_dump", "to_dict"):
        fn = getattr(usage, attr, None)
        if callable(fn):
            try:
                return dict(fn())
            except Exception:  # noqa: BLE001
                continue
    return {}


def _is_transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    markers = (
        "rate limit", "ratelimit", "429", "timeout", "timed out",
        "temporarily", "503", "502", "504", "connection", "overloaded",
    )
    return any(marker in text for marker in markers)


# --- registry -------------------------------------------------------------------

_REGISTRY: dict[str, Any] = {
    "none": NullProvider,
    "openai": OpenAIImageProvider,
}


def register_provider(name: str, factory: Any) -> None:
    """Add an adapter without touching the UI."""
    _REGISTRY[name] = factory


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def get_provider(name: str | None = None) -> ImageProvider:
    """Resolve the configured provider, falling back to the honest no-op."""
    requested = (name or os.getenv("BETTY_OS_IMAGE_PROVIDER", "") or "").strip().lower()
    if requested:
        factory = _REGISTRY.get(requested)
        if factory is None:
            raise ProviderError(
                f"Unknown image provider '{requested}'. "
                f"Known: {', '.join(available_providers())}."
            )
        return factory()
    # No explicit choice: use OpenAI when it is fully configured, else no-op.
    candidate = OpenAIImageProvider()
    return candidate if candidate.is_configured() else NullProvider()
