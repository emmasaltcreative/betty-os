"""BettyOS entry point — plan, ingest, repurpose, create, review, and approve."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
import typer
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from src.brand import load_brand_brain
from src.common import (
    ASSETS_PATH,
    LIBRARY_DIR,
    OUTPUTS_DIR,
    PAGE_TURN_SOURCE,
    RITUAL_REEL_TEMPLATE_PATH,
    ROOT,
    THUMBNAILS_DIR,
    BettyOSError,
    ensure_outputs_dir,
    find_latest_content_package,
    find_latest_render_dirs,
    new_campaign_dir,
    relative_to_root,
    require_latest_campaign_dir,
    single_render_dir,
    timestamp_stamp,
)
from src.package_parse import (
    extract_campaign_goal,
    extract_piece2_instagram_caption,
    extract_piece4_captions,
    list_content_pieces,
)
from src.production import (
    ProductionConfigError,
    load_production_brain,
    load_production_context_for_review,
)

VERSION = "1.0.0-beta"
TAGLINE = "A Creative Operations System for content production."
MODEL = "claude-sonnet-4-6"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mov", ".mp4"}

PLAN_INSTRUCTIONS = """
Generate a concise, executable production plan as Markdown with these sections:

1. Session objective
2. Recommended creative concept
3. Priority asset list
4. Shot list in production order
5. Styling and prop notes
6. Lighting and composition direction
7. Platform-specific adaptations for the selected channels
8. Suggested hooks, captions, or overlay copy
9. A realistic time allocation
10. Final preparation checklist

Rules:
- Reflect the actual time available, products, locations, channels, and notes.
- Prioritize the highest-value assets; do not propose an unrealistic amount of content.
- Keep the plan practical and ready to shoot today.
- Output Markdown only — no preamble outside the plan.
""".strip()

ASSET_ANALYSIS_INSTRUCTIONS = """
Analyze the media and return ONLY valid JSON matching this schema (no markdown fences, no commentary):

{
  "filename": "string",
  "asset_type": "image or video",
  "summary": "string",
  "products": ["string"],
  "objects": ["string"],
  "actions": ["string"],
  "setting": ["string"],
  "mood": ["string"],
  "lighting": "string",
  "orientation": "vertical, horizontal, or square",
  "quality_score": 1,
  "recommended_uses": ["string"],
  "potential_hooks": ["string"]
}

Rules:
- filename must be the provided filename
- asset_type must be "image" or "video" as provided
- quality_score is an integer from 1 (poor) to 10 (excellent)
- orientation must be exactly "vertical", "horizontal", or "square"
- Be concrete and useful for content planning
""".strip()

REPURPOSE_INSTRUCTIONS = """
You are a senior creative strategist and editor for Oh Betty Jaletti.

Using ONLY the indexed assets provided (by their exact file path keys), create an actionable brand-aligned content package in Markdown.

Required structure:

## Campaign Direction
- goal
- audience
- central creative idea
- recommended publishing rhythm

## Content Pieces

For each content piece include:
- Working title
- Platform
- Objective
- Exact asset file paths
- Recommended shot order
- On-screen hook
- Supporting on-screen text
- Caption
- CTA
- Suggested duration or format
- Editing notes (clearly mark whether it needs editing or is ready to post)
- Why it fits Oh Betty Jaletti

## Missing Assets
Only include shots genuinely needed to complete the proposed content. If nothing is missing, say so.

## Priority Order
Rank the content pieces by likely business impact.

Rules:
- Choose specific indexed assets by their exact file paths from the library.
- Explain how each asset supports the content concept.
- Do not recommend footage that does not exist in the indexed library.
- Stay aligned with the Oh Betty Jaletti aesthetic and voice.
- Prioritize content that can grow the First Edition waitlist.
- Distinguish between content requiring editing and content ready to post.
- Output Markdown only — no preamble outside the package.
""".strip()

app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    help="BettyOS — local Creative Operations System for planning, rendering, reviewing, and approving content.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()


class ProductionSession(BaseModel):
    brand: str
    time_available: str
    creating_for: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: str


class AssetRecord(BaseModel):
    filename: str
    asset_type: Literal["image", "video"]
    summary: str
    products: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    setting: list[str] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)
    lighting: str
    orientation: Literal["vertical", "horizontal", "square"]
    quality_score: int = Field(ge=1, le=10)
    recommended_uses: list[str] = Field(default_factory=list)
    potential_hooks: list[str] = Field(default_factory=list)


# --- Shared helpers ---


def exit_error(message: str, hint: str | None = None) -> None:
    """Print a friendly error and stop the CLI."""
    console.print(f"[red]{message}[/red]")
    if hint:
        console.print(f"[dim]{hint}[/dim]")
    raise typer.Exit(1)


def handle_betty_error(exc: BettyOSError) -> None:
    exit_error(exc.message, exc.hint)


def require_content_package() -> Path:
    try:
        return find_latest_content_package()
    except BettyOSError as exc:
        handle_betty_error(exc)
        raise  # pragma: no cover


def require_brand_context() -> str:
    try:
        return load_brand_brain()
    except BettyOSError as exc:
        handle_betty_error(exc)
        raise  # pragma: no cover


def show_launch_screen() -> None:
    title = Text.assemble(("BettyOS", "bold cyan"), (f"  v{VERSION}", "dim"))
    body = Text.assemble(
        (TAGLINE, "italic"),
        "\n\n",
        ("Let's plan today's production session.", "dim"),
    )
    console.print()
    console.print(Panel(body, title=title, border_style="cyan", padding=(1, 2)))
    console.print()


def prompt_list(question: str, examples: str) -> list[str]:
    """Collect one or more answers; blank line ends the list."""
    console.print(f"[bold]{question}[/bold]")
    console.print(f"[dim]Examples: {examples}[/dim]")
    console.print("[dim]Enter one per line. Leave blank when done.[/dim]")

    items: list[str] = []
    while True:
        value = console.input("[cyan]>[/] ").strip()
        if not value:
            break
        items.append(value)
    return items


def require_api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        console.print(
            "[red]Missing ANTHROPIC_API_KEY.[/red]\n"
            "Add it to a local [bold].env[/bold] file in the project root:\n\n"
            "  ANTHROPIC_API_KEY=your_key_here\n"
        )
        raise typer.Exit(1)
    return key


def extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


# --- Plan workflow ---


def collect_session() -> ProductionSession:
    brand = Prompt.ask("Which brand?", default="Oh Betty Jaletti").strip()

    console.print()
    console.print("[bold]How much time do you have available?[/bold]")
    console.print("[dim]Examples: 30 minutes, 2 hours, Half day, Full day[/dim]")
    time_available = Prompt.ask("Time").strip()

    console.print()
    creating_for = prompt_list(
        "What are you creating content for?",
        "Pinterest, Instagram, Email, Shopify, Waitlist, Multiple",
    )

    console.print()
    products = prompt_list(
        "What products are available today?",
        "earrings, scarf, tote — whatever is on hand",
    )

    console.print()
    locations = prompt_list(
        "What location(s) are available?",
        "Home, Coffee shop, Library, NYC apartment, Outdoors",
    )

    console.print()
    console.print("[bold]Is there anything important about today's shoot?[/bold]")
    console.print("[dim]Optional — leave blank to skip.[/dim]")
    notes_raw = Prompt.ask("Notes", default="", show_default=False).strip()
    notes = notes_raw or None

    now = datetime.now().astimezone()
    return ProductionSession(
        brand=brand,
        time_available=time_available,
        creating_for=creating_for,
        products=products,
        locations=locations,
        notes=notes,
        created_at=now.isoformat(timespec="seconds"),
    )


def save_session(session: ProductionSession, stamp: str) -> Path:
    ensure_outputs_dir()
    path = OUTPUTS_DIR / f"{stamp}_session.json"
    path.write_text(session.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def build_prompt(session: ProductionSession) -> str:
    session_json = session.model_dump_json(indent=2)
    return (
        f"{require_brand_context()}\n\n"
        f"Today's production session (JSON):\n{session_json}\n\n"
        f"{PLAN_INSTRUCTIONS}"
    )


def generate_plan(session: ProductionSession, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": build_prompt(session)}],
        )
    except anthropic.APIError as exc:
        console.print(f"[red]Claude request failed:[/red] {exc.__class__.__name__}")
        console.print("[dim]Check your network connection and API key, then try again.[/dim]")
        raise typer.Exit(1) from None
    except Exception:
        console.print("[red]Claude request failed unexpectedly.[/red]")
        console.print("[dim]Check your network connection and API key, then try again.[/dim]")
        raise typer.Exit(1) from None

    plan = extract_text(response)
    if not plan:
        console.print("[red]Claude returned an empty plan.[/red]")
        console.print("[dim]Try running again. If it keeps happening, simplify the session inputs.[/dim]")
        raise typer.Exit(1)
    return plan


def save_plan(plan: str, stamp: str) -> Path:
    ensure_outputs_dir()
    path = OUTPUTS_DIR / f"{stamp}_plan.md"
    path.write_text(plan.rstrip() + "\n", encoding="utf-8")
    return path


def run_plan_workflow() -> None:
    show_launch_screen()
    try:
        session = collect_session()
        stamp = timestamp_stamp()
        session_path = save_session(session, stamp)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None

    console.print()
    console.print(f"[green]Session saved:[/green] {session_path}")

    api_key = require_api_key()
    console.print("[dim]Generating production plan with Claude…[/dim]")
    plan = generate_plan(session, api_key)
    plan_path = save_plan(plan, stamp)

    console.print(f"[green]Plan saved:[/green] {plan_path}")
    console.print("[dim]Goodbye.[/dim]")


# --- Ingest workflow ---


def asset_key_for(path: Path) -> str:
    """Full relative path from cwd when possible; otherwise absolute path."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def media_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


def find_media(folder: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
            files.append(path)
    return files


def load_assets() -> dict[str, Any]:
    if not ASSETS_PATH.exists():
        return {}
    try:
        data = json.loads(ASSETS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        console.print("[yellow]Warning: library/assets.json is invalid; starting fresh.[/yellow]")
        return {}
    if not isinstance(data, dict):
        console.print("[yellow]Warning: library/assets.json is not an object; starting fresh.[/yellow]")
        return {}
    return data


def save_assets(assets: dict[str, Any]) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_PATH.write_text(json.dumps(assets, indent=2) + "\n", encoding="utf-8")


def parse_asset_json(text: str) -> AssetRecord:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    return AssetRecord.model_validate(data)


def image_block(path: Path) -> dict[str, Any]:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type_for(path),
            "data": data,
        },
    }


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    console.print(
        "[red]ffmpeg is required for video ingestion.[/red]\n"
        "Install on macOS with:\n\n"
        "  brew install ffmpeg\n"
    )
    raise typer.Exit(1)


def video_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def extract_video_frames(path: Path, key: str) -> list[Path]:
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    duration = video_duration_seconds(path)
    if duration <= 0:
        raise RuntimeError("Could not read video duration.")

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key)
    frames: list[Path] = []
    for label, fraction in (("20", 0.2), ("50", 0.5), ("80", 0.8)):
        out = THUMBNAILS_DIR / f"{safe}_{label}.jpg"
        stamp = max(duration * fraction, 0.0)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{stamp:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(out),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"Failed to extract frame at {label}%.")
        frames.append(out)
    return frames


def analyze_asset(
    client: anthropic.Anthropic,
    path: Path,
    asset_type: Literal["image", "video"],
    image_paths: list[Path],
) -> AssetRecord:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Filename: {path.name}\n"
                f"Asset type: {asset_type}\n\n"
                f"{ASSET_ANALYSIS_INSTRUCTIONS}"
            ),
        }
    ]
    for image_path in image_paths:
        content.append(image_block(image_path))

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
    )
    text = extract_text(response)
    if not text:
        raise RuntimeError("Claude returned an empty asset analysis.")
    record = parse_asset_json(text)
    # Keep identity fields consistent with the local file.
    return record.model_copy(update={"filename": path.name, "asset_type": asset_type})


def ingest_folder(folder: Path, force: bool) -> None:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        console.print(f"[red]Folder not found:[/red] {folder}")
        raise typer.Exit(1)

    media = find_media(folder)
    if not media:
        console.print("[yellow]No images or videos found.[/yellow]")
        raise typer.Exit(0)

    has_video = any(path.suffix.lower() in VIDEO_EXTS for path in media)
    if has_video:
        require_ffmpeg()

    api_key = require_api_key()
    client = anthropic.Anthropic(api_key=api_key)
    assets = load_assets()

    indexed = skipped = failed = 0
    total = len(media)

    for index, path in enumerate(media, start=1):
        key = asset_key_for(path)
        console.print(f"Analyzing {index} of {total}: {path.name}")

        if key in assets and not force:
            skipped += 1
            continue

        asset_type: Literal["image", "video"] = (
            "video" if path.suffix.lower() in VIDEO_EXTS else "image"
        )
        try:
            if asset_type == "image":
                image_paths = [path]
            else:
                image_paths = extract_video_frames(path, key)

            record = analyze_asset(client, path, asset_type, image_paths)
            assets[key] = record.model_dump()
            save_assets(assets)
            indexed += 1
        except (anthropic.APIError, ValidationError, json.JSONDecodeError, OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
            failed += 1
            console.print(f"  [red]Failed:[/red] {path.name} — {exc.__class__.__name__}")
        except Exception as exc:
            failed += 1
            console.print(f"  [red]Failed:[/red] {path.name} — {exc.__class__.__name__}")

    console.print()
    console.print(f"Indexed: {indexed}")
    console.print(f"Skipped: {skipped}")
    console.print(f"Failed: {failed}")
    console.print(f"[dim]Library:[/dim] {ASSETS_PATH}")


# --- Repurpose workflow ---


class RepurposeBrief(BaseModel):
    campaign_goal: str
    platforms: list[str]
    content_count: int = Field(ge=1)
    notes: str | None = None


def load_latest_session() -> dict[str, Any] | None:
    sessions = sorted(OUTPUTS_DIR.glob("*_session.json"))
    if not sessions:
        return None
    latest = sessions[-1]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        console.print(f"[yellow]Warning: could not parse {latest.name}; continuing without it.[/yellow]")
        return None
    if not isinstance(data, dict):
        return None
    data["_source_file"] = latest.name
    return data


def collect_repurpose_brief() -> RepurposeBrief:
    console.print()
    console.print(Panel("Brand-aware content repurposing", border_style="cyan"))
    console.print()

    campaign_goal = Prompt.ask("Campaign goal").strip()
    while not campaign_goal:
        campaign_goal = Prompt.ask("Campaign goal").strip()

    console.print()
    console.print("[bold]Platforms[/bold]")
    console.print("[dim]Enter one per line. Leave blank when done.[/dim]")
    console.print("[dim]Default if none entered: Pinterest, Instagram[/dim]")
    platforms = prompt_list("Which platforms?", "Pinterest, Instagram, Email, Shopify, Waitlist")
    if not platforms:
        platforms = ["Pinterest", "Instagram"]

    console.print()
    while True:
        raw = Prompt.ask("Number of content pieces desired", default="5").strip()
        try:
            content_count = int(raw)
            if content_count >= 1:
                break
        except ValueError:
            pass
        console.print("[dim]Enter a whole number of 1 or more.[/dim]")

    console.print()
    console.print("[bold]Optional notes[/bold]")
    console.print("[dim]Leave blank to skip.[/dim]")
    notes_raw = Prompt.ask("Notes", default="", show_default=False).strip()
    notes = notes_raw or None

    return RepurposeBrief(
        campaign_goal=campaign_goal,
        platforms=platforms,
        content_count=content_count,
        notes=notes,
    )


def build_repurpose_prompt(
    assets: dict[str, Any],
    brief: RepurposeBrief,
    session: dict[str, Any] | None,
) -> str:
    parts = [
        require_brand_context(),
        "",
        "Indexed asset library (JSON object keyed by exact file path):",
        json.dumps(assets, indent=2),
        "",
        "Campaign brief (JSON):",
        brief.model_dump_json(indent=2),
    ]
    if session is not None:
        parts.extend(
            [
                "",
                f"Most recent production session ({session.get('_source_file', 'unknown')}):",
                json.dumps({k: v for k, v in session.items() if k != "_source_file"}, indent=2),
            ]
        )
    else:
        parts.extend(["", "Most recent production session: none available."])
    parts.extend(["", REPURPOSE_INSTRUCTIONS])
    return "\n".join(parts)


def generate_content_package(prompt: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        console.print(f"[red]Claude request failed:[/red] {exc.__class__.__name__}")
        console.print("[dim]Check your network connection and API key, then try again.[/dim]")
        raise typer.Exit(1) from None
    except Exception:
        console.print("[red]Claude request failed unexpectedly.[/red]")
        console.print("[dim]Check your network connection and API key, then try again.[/dim]")
        raise typer.Exit(1) from None

    package = extract_text(response)
    if not package:
        console.print("[red]Claude returned an empty content package.[/red]")
        raise typer.Exit(1)
    return package


def save_content_package(package: str) -> Path:
    ensure_outputs_dir()
    stamp = timestamp_stamp()
    path = OUTPUTS_DIR / f"{stamp}_content_package.md"
    path.write_text(package.rstrip() + "\n", encoding="utf-8")
    return path


def run_repurpose_workflow() -> None:
    assets = load_assets()
    if not assets:
        console.print(
            "[red]No indexed assets found.[/red]\n"
            "Run [bold]python3 main.py ingest /path/to/media-folder[/bold] first."
        )
        raise typer.Exit(1)

    session = load_latest_session()
    if session and session.get("_source_file"):
        console.print(f"[dim]Using session:[/dim] {session['_source_file']}")
    else:
        console.print("[dim]No recent production session found; continuing with assets + brand only.[/dim]")

    try:
        brief = collect_repurpose_brief()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None

    api_key = require_api_key()
    console.print("[dim]Generating content package with Claude…[/dim]")
    prompt = build_repurpose_prompt(assets, brief, session)
    package = generate_content_package(prompt, api_key)
    path = save_content_package(package)
    console.print(f"[green]Content package saved:[/green] {path}")


# --- Create: page-turn-loop (production-brain driven) ---

RITUAL_REEL_MIN_SECONDS = 20.0
RITUAL_REEL_MAX_SECONDS = 30.0




def probe_video(path: Path) -> dict[str, float | int]:
    require_ffmpeg()
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    duration = float(stream.get("duration") or payload["format"]["duration"])
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": duration,
    }


def parse_color(value: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    colors = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
    }
    rgb = colors.get(value.lower(), (255, 255, 255))
    return (*rgb, max(0, min(255, int(opacity * 255))))


def resolve_font(typography: dict[str, Any]) -> str:
    primary = Path(typography["primary_font"]["path"])
    if primary.exists():
        return str(primary)
    fallback = Path(typography["secondary_font"]["path"])
    if fallback.exists():
        console.print(
            f"[yellow]Font not found:[/yellow] {primary}. "
            f"Using secondary: {fallback.name}"
        )
        return str(fallback)
    raise ProductionConfigError(
        "No usable font found. Update typography.primary_font.path "
        "or typography.secondary_font.path."
    )


def text_block_size(draw: Any, lines: list[str], font: Any, line_spacing: int) -> tuple[int, int]:
    widths: list[int] = []
    heights: list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    total_h = sum(heights) + line_spacing * max(len(lines) - 1, 0)
    return (max(widths) if widths else 0, total_h)


def draw_text_block(
    draw: Any,
    lines: list[str],
    font: Any,
    *,
    canvas_w: int,
    top_y: int,
    alignment: str,
    fill: tuple[int, int, int, int],
    line_spacing: int,
    shadow: dict[str, Any] | None,
) -> None:
    block_w, _ = text_block_size(draw, lines, font, line_spacing)
    x0 = (canvas_w - block_w) // 2 if alignment == "center" else 0
    y = top_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        if alignment == "center":
            x = x0 + (block_w - line_w) // 2
        else:
            x = x0
        if shadow and shadow.get("enabled"):
            shadow_fill = parse_color(
                str(shadow.get("color", "black")),
                float(shadow.get("opacity", 0.45)),
            )
            draw.text(
                (x + int(shadow.get("offset_x", 1)), y + int(shadow.get("offset_y", 2))),
                line,
                font=font,
                fill=shadow_fill,
            )
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_spacing


def render_overlay_layer(
    *,
    width: int,
    height: int,
    lines: list[str],
    font_path: str,
    font_size: int,
    y_ratio: float,
    typography: dict[str, Any],
    colors: dict[str, Any],
    layout: dict[str, Any],
    safe_margins: dict[str, int],
    output_path: Path,
    bottom_floor: int | None = None,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, font_size)
    fill = parse_color(str(colors["primary_text_color"]), float(colors["text_opacity"]))
    line_spacing = int(typography["line_spacing"])
    alignment = str(layout.get("alignment") or typography["default_alignment"])
    block_w, block_h = text_block_size(draw, lines, font, line_spacing)

    max_width = min(int(typography["max_line_width"]), int(layout["maximum_text_width"]))
    if block_w > max_width:
        console.print(
            f"[yellow]Warning:[/yellow] text block width {block_w}px exceeds "
            f"max line width ({max_width}px)."
        )

    top_y = int(height * float(y_ratio))
    top_y = max(top_y, int(safe_margins["top"]))
    if bottom_floor is not None:
        top_y = min(top_y, bottom_floor - block_h)
    else:
        top_y = min(top_y, height - int(safe_margins["bottom"]) - block_h)
    top_y = max(top_y, int(safe_margins["top"]))

    wash = colors.get("background_wash", {})
    if wash.get("enabled"):
        wash_fill = parse_color(str(wash.get("color", "black")), float(wash.get("opacity", 0)))
        pad = 18
        left = max((width - block_w) // 2 - pad, int(safe_margins["left"]))
        draw.rectangle(
            (left, top_y - pad, left + block_w + pad * 2, top_y + block_h + pad),
            fill=wash_fill,
        )

    draw_text_block(
        draw,
        lines,
        font,
        canvas_w=width,
        top_y=top_y,
        alignment=alignment,
        fill=fill,
        line_spacing=line_spacing,
        shadow=colors.get("shadow"),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def choose_segment(
    source_duration: float,
    target_duration: float,
    looping: dict[str, Any],
) -> dict[str, Any]:
    """Prefer middle target_duration seconds; loop if source is shorter."""
    if source_duration >= target_duration and looping.get("prefer_middle_segment_when_longer", True):
        start = (source_duration - target_duration) / 2
        return {
            "mode": "middle_trim",
            "source_start_seconds": round(start, 3),
            "source_end_seconds": round(start + target_duration, 3),
            "output_duration_seconds": target_duration,
            "looped": False,
            "notes": "Used the middle segment of the source clip.",
        }
    if source_duration >= target_duration:
        return {
            "mode": "start_trim",
            "source_start_seconds": 0.0,
            "source_end_seconds": target_duration,
            "output_duration_seconds": target_duration,
            "looped": False,
            "notes": "Used the first segment of the source clip.",
        }
    if not looping.get("enabled_when_source_shorter", True):
        return {
            "mode": "full_source",
            "source_start_seconds": 0.0,
            "source_end_seconds": round(source_duration, 3),
            "output_duration_seconds": round(source_duration, 3),
            "looped": False,
            "notes": "Source shorter than target; exported full source without looping.",
        }
    return {
        "mode": "full_source_looped",
        "source_start_seconds": 0.0,
        "source_end_seconds": round(source_duration, 3),
        "output_duration_seconds": target_duration,
        "looped": True,
        "notes": (
            f"Source is only {source_duration:.3f}s; used the full clip and looped "
            f"to reach {target_duration:.0f}s."
        ),
    }


def render_page_turn_loop(
    source: Path,
    output_video: Path,
    primary_overlay: Path,
    cta_overlay: Path,
    brain: dict[str, Any],
    segment: dict[str, Any],
    cta_appear_at: float,
) -> None:
    require_ffmpeg()
    exports = brain["exports"]
    animation = brain["animation"]
    resolved = brain["resolved"]
    target = float(segment["output_duration_seconds"])
    width = int(exports["width"])
    height = int(exports["height"])
    fade_in = float(animation["opening_fade_seconds"])
    fade_out = float(animation["closing_fade_seconds"])
    text_fade = float(animation["text_fade_seconds"])

    if resolved["crop_strategy"] == "center_crop":
        geometry = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        geometry = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

    video_filters = [geometry]
    if fade_in > 0:
        video_filters.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        video_filters.append(f"fade=t=out:st={max(target - fade_out, 0):.3f}:d={fade_out}")

    filter_complex = (
        f"[0:v]{','.join(video_filters)}[base];"
        f"[1:v]format=rgba,"
        f"fade=t=in:st=0:d={text_fade}:alpha=1[primary];"
        f"[2:v]format=rgba,"
        f"fade=t=in:st={cta_appear_at:.3f}:d={text_fade}:alpha=1[cta];"
        f"[base][primary]overlay=0:0[with_primary];"
        f"[with_primary][cta]overlay=0:0:enable='gte(t\\,{cta_appear_at:.3f})'"
    )

    cmd = ["ffmpeg", "-y"]
    if segment["looped"]:
        cmd += ["-stream_loop", "-1", "-i", str(source), "-t", f"{target:.3f}"]
    else:
        cmd += [
            "-ss",
            f"{segment['source_start_seconds']:.3f}",
            "-to",
            f"{segment['source_end_seconds']:.3f}",
            "-i",
            str(source),
        ]
    cmd += [
        "-loop",
        "1",
        "-i",
        str(primary_overlay),
        "-loop",
        "1",
        "-i",
        str(cta_overlay),
        "-filter_complex",
        filter_complex,
        "-t",
        f"{target:.3f}",
        "-r",
        str(exports["fps"]),
    ]
    if exports["audio"].get("behavior") == "remove":
        cmd.append("-an")
    cmd += [
        "-c:v",
        str(exports["codec"]),
        "-b:v",
        str(exports["bitrate"]),
        "-preset",
        str(exports["compression"]["preset"]),
        "-crf",
        str(exports["compression"]["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_video),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("[red]ffmpeg failed while rendering the draft.[/red]")
        err = (result.stderr or "").strip().splitlines()
        if err:
            console.print(f"[dim]{err[-1]}[/dim]")
        raise typer.Exit(1)


def run_create_page_turn_loop(out_dir: Path | None = None) -> Path:
    try:
        brain = load_production_brain()
    except ProductionConfigError as exc:
        exit_error(f"Production config error: {exc}", hint="Check files under production/.")

    template = brain["template"]
    typography = brain["typography"]
    colors = brain["colors"]
    layout = brain["layout"]
    animation = brain["animation"]
    exports = brain["exports"]
    resolved = brain["resolved"]

    package_path = require_content_package()
    package_text = package_path.read_text(encoding="utf-8")

    try:
        ig_caption, pin_caption = extract_piece4_captions(package_text)
    except RuntimeError as exc:
        exit_error(
            str(exc),
            hint="Latest package needs a Page Turn Loop piece, or use: python3 main.py create all",
        )
    source = ROOT / template["source_relative_path"]
    if not source.exists():
        source = PAGE_TURN_SOURCE
    if not source.exists():
        console.print(f"[red]Source video not found:[/red] {PAGE_TURN_SOURCE}")
        raise typer.Exit(1)

    try:
        font_path = resolve_font(typography)
    except ProductionConfigError as exc:
        console.print(f"[red]Production config error:[/red] {exc}")
        raise typer.Exit(1) from None

    probe = probe_video(source)
    target_duration = float(template["target_duration_seconds"])
    segment = choose_segment(
        float(probe["duration"]),
        target_duration,
        resolved["looping"],
    )
    output_duration = float(segment["output_duration_seconds"])
    cta_appear_at = max(
        output_duration - float(animation["cta_appear_from_end_seconds"]),
        0.0,
    )

    if out_dir is None:
        out_dir = single_render_dir("page_turn_loop")
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "page_turn_loop_draft.mp4"
    caption_path = out_dir / "caption.md"
    settings_path = out_dir / "render_settings.json"
    primary_overlay = out_dir / "_overlay_primary.png"
    cta_overlay = out_dir / "_overlay_cta.png"

    console.print(f"[dim]Content package:[/dim] {package_path.name}")
    console.print(f"[dim]Source:[/dim] {source.relative_to(ROOT)}")
    console.print(f"[dim]Segment:[/dim] {segment['notes']}")
    console.print("[dim]Rendering draft with global Production Brain…[/dim]")

    width = int(exports["width"])
    height = int(exports["height"])
    safe_margins = resolved["safe_margins"]
    bottom_floor = height - int(safe_margins["bottom"])

    from PIL import Image

    primary = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    hook_tmp = out_dir / "_tmp_hook.png"
    footer_tmp = out_dir / "_tmp_footer.png"
    render_overlay_layer(
        width=width,
        height=height,
        lines=list(template["hook"]["lines"]),
        font_path=font_path,
        font_size=int(typography["hook"]["size"]),
        y_ratio=float(layout["hook_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=hook_tmp,
    )
    render_overlay_layer(
        width=width,
        height=height,
        lines=list(template["footer"]["lines"]),
        font_path=font_path,
        font_size=int(typography["footer"]["size"]),
        y_ratio=float(layout["footer_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=footer_tmp,
        bottom_floor=bottom_floor,
    )
    primary.alpha_composite(Image.open(hook_tmp).convert("RGBA"))
    primary.alpha_composite(Image.open(footer_tmp).convert("RGBA"))
    primary.save(primary_overlay)
    hook_tmp.unlink(missing_ok=True)
    footer_tmp.unlink(missing_ok=True)

    render_overlay_layer(
        width=width,
        height=height,
        lines=[str(template["cta"]["text"])],
        font_path=font_path,
        font_size=int(typography["cta"]["size"]),
        y_ratio=float(layout["cta_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=cta_overlay,
        bottom_floor=bottom_floor,
    )

    try:
        render_page_turn_loop(
            source,
            video_path,
            primary_overlay,
            cta_overlay,
            brain,
            segment,
            cta_appear_at,
        )
    finally:
        primary_overlay.unlink(missing_ok=True)
        cta_overlay.unlink(missing_ok=True)

    caption_path.write_text(
        "# Captions — The Page Turn Loop\n\n"
        "## Instagram\n\n"
        f"{ig_caption}\n\n"
        "## Pinterest\n\n"
        f"{pin_caption}\n",
        encoding="utf-8",
    )

    settings = {
        "piece": "Piece #4 — The Page Turn Loop",
        "content_package": package_path.name,
        "style_guide": brain["style_guide"],
        "production": {
            "global_defaults": brain["global_defaults"],
            "typography": typography,
            "colors": colors,
            "layout": layout,
            "animation": animation,
            "exports": exports,
            "safe_zones": brain["safe_zones"],
            "template": template,
        },
        "resolved": {
            **resolved,
            "font_path": font_path,
            "cta_appear_at_seconds": round(cta_appear_at, 3),
            "opening_fade_seconds": animation["opening_fade_seconds"],
            "closing_fade_seconds": animation["closing_fade_seconds"],
        },
        "source": {
            "path": source.relative_to(ROOT).as_posix(),
            "width": probe["width"],
            "height": probe["height"],
            "duration_seconds": round(float(probe["duration"]), 3),
        },
        "segment": segment,
        "output": {
            "width": exports["width"],
            "height": exports["height"],
            "fps": exports["fps"],
            "codec": exports["codec"],
            "bitrate": exports["bitrate"],
            "audio": exports["audio"],
            "video": video_path.name,
        },
    }
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    console.print(f"[green]Draft folder:[/green] {out_dir}")
    return out_dir


def plan_ritual_clip_segments(
    probes: list[dict[str, float | int]],
    source_targets: list[float],
    target_total: float,
    looping: dict[str, Any],
) -> list[dict[str, Any]]:
    """Allocate multi-clip segments; short clips use full available duration without failing."""
    if len(probes) != len(source_targets):
        raise RuntimeError("Ritual reel source targets must match source count.")
    if not probes:
        raise RuntimeError("Ritual reel requires at least one source clip.")

    segments: list[dict[str, Any]] = []
    used = 0.0
    for index in range(len(probes) - 1):
        segment = choose_segment(
            float(probes[index]["duration"]),
            float(source_targets[index]),
            looping,
        )
        segments.append(segment)
        used += float(segment["output_duration_seconds"])

    last_duration = float(probes[-1]["duration"])
    remaining_for_target = max(target_total - used, 0.0)
    min_last = max(remaining_for_target, max(0.0, RITUAL_REEL_MIN_SECONDS - used))
    max_last = min(last_duration, max(0.0, RITUAL_REEL_MAX_SECONDS - used))
    if max_last <= 0:
        last_target = min(float(source_targets[-1]), last_duration)
    else:
        last_target = min(max(float(source_targets[-1]), min_last), max_last)
    segments.append(choose_segment(last_duration, last_target, looping))
    return segments


def _crop_filter(width: int, height: int, crop_strategy: str) -> str:
    if crop_strategy == "center_crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


def render_ritual_reel(
    sources: list[Path],
    segments: list[dict[str, Any]],
    output_video: Path,
    overlays: dict[str, Path],
    brain: dict[str, Any],
    text_timing: dict[str, float],
) -> None:
    """Assemble multi-clip ritual reel with global transition + text timing."""
    require_ffmpeg()
    exports = brain["exports"]
    animation = brain["animation"]
    resolved = brain["resolved"]
    globals_cfg = brain["global_defaults"]

    width = int(exports["width"])
    height = int(exports["height"])
    fade_in = float(animation["opening_fade_seconds"])
    fade_out = float(animation["closing_fade_seconds"])
    text_fade = float(animation["text_fade_seconds"])
    total = sum(float(segment["output_duration_seconds"]) for segment in segments)
    geometry = _crop_filter(width, height, str(resolved["crop_strategy"]))

    transition = str(
        globals_cfg.get("transition_style") or animation.get("default_transition") or "cut"
    )
    if transition != "cut":
        console.print(
            f"[yellow]Unsupported transition '{transition}'; falling back to cut.[/yellow]"
        )

    cmd: list[str] = ["ffmpeg", "-y"]
    for source, segment in zip(sources, segments):
        cmd += [
            "-ss",
            f"{float(segment['source_start_seconds']):.3f}",
            "-t",
            f"{float(segment['output_duration_seconds']):.3f}",
            "-i",
            str(source),
        ]
    for key in ("hook", "supporting", "footer", "cta"):
        cmd += ["-loop", "1", "-i", str(overlays[key])]

    clip_labels: list[str] = []
    filter_parts: list[str] = []
    for index in range(len(sources)):
        label = f"v{index}"
        clip_labels.append(f"[{label}]")
        filter_parts.append(
            f"[{index}:v]{geometry},setpts=PTS-STARTPTS[{label}]"
        )

    concat_inputs = "".join(clip_labels)
    filter_parts.append(f"{concat_inputs}concat=n={len(sources)}:v=1:a=0[base]")

    faded = "[base]"
    fade_chain: list[str] = []
    if fade_in > 0:
        fade_chain.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        fade_chain.append(f"fade=t=out:st={max(total - fade_out, 0):.3f}:d={fade_out}")
    if fade_chain:
        filter_parts.append(f"[base]{','.join(fade_chain)}[faded]")
        faded = "[faded]"

    hook_at = float(text_timing["hook_appear_at_seconds"])
    support_at = float(text_timing["supporting_appear_at_seconds"])
    support_end = float(text_timing["supporting_end_at_seconds"])
    footer_at = float(text_timing["footer_appear_at_seconds"])
    cta_at = float(text_timing["cta_appear_at_seconds"])

    n = len(sources)
    filter_parts.extend(
        [
            f"[{n}:v]format=rgba,fade=t=in:st={hook_at:.3f}:d={text_fade}:alpha=1[hook]",
            (
                f"[{n + 1}:v]format=rgba,"
                f"fade=t=in:st={support_at:.3f}:d={text_fade}:alpha=1[supporting]"
            ),
            (
                f"[{n + 2}:v]format=rgba,"
                f"fade=t=in:st={footer_at:.3f}:d={text_fade}:alpha=1[footer]"
            ),
            (
                f"[{n + 3}:v]format=rgba,"
                f"fade=t=in:st={cta_at:.3f}:d={text_fade}:alpha=1[cta]"
            ),
            (
                f"{faded}[hook]overlay=0:0:"
                f"enable='between(t\\,{hook_at:.3f}\\,{support_at:.3f})'[with_hook]"
            ),
            (
                "[with_hook][supporting]overlay=0:0:"
                f"enable='between(t\\,{support_at:.3f}\\,{support_end:.3f})'[with_support]"
            ),
            (
                "[with_support][footer]overlay=0:0:"
                f"enable='gte(t\\,{footer_at:.3f})'[with_footer]"
            ),
            f"[with_footer][cta]overlay=0:0:enable='gte(t\\,{cta_at:.3f})'",
        ]
    )

    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-t",
        f"{total:.3f}",
        "-r",
        str(exports["fps"]),
    ]
    if exports["audio"].get("behavior") == "remove":
        cmd.append("-an")
    cmd += [
        "-c:v",
        str(exports["codec"]),
        "-b:v",
        str(exports["bitrate"]),
        "-preset",
        str(exports["compression"]["preset"]),
        "-crf",
        str(exports["compression"]["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_video),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("[red]ffmpeg failed while rendering the ritual reel draft.[/red]")
        err = (result.stderr or "").strip().splitlines()
        if err:
            console.print(f"[dim]{err[-1]}[/dim]")
        raise typer.Exit(1)


def run_create_ritual_reel(
    out_dir: Path | None = None,
    *,
    source_overrides: list[dict[str, Any]] | None = None,
    target_duration_seconds: float | None = None,
    cta_appear_at_seconds: float | None = None,
    caption_override: str | None = None,
    overlay_copy_overrides: dict[str, Any] | None = None,
    output_filename: str | None = None,
    caption_filename: str | None = None,
    preserve_existing: bool = False,
    versioning: dict[str, Any] | None = None,
) -> Path:
    try:
        brain = load_production_brain(RITUAL_REEL_TEMPLATE_PATH)
    except ProductionConfigError as exc:
        exit_error(f"Production config error: {exc}", hint="Check files under production/.")

    template = dict(brain["template"])
    typography = brain["typography"]
    colors = brain["colors"]
    layout = brain["layout"]
    animation = brain["animation"]
    exports = brain["exports"]
    resolved = brain["resolved"]

    if source_overrides is not None:
        template["sources"] = list(source_overrides)
    if target_duration_seconds is not None:
        template["target_duration_seconds"] = float(target_duration_seconds)
    if overlay_copy_overrides:
        # Approved on-screen copy for this render only. The shared template file
        # under production/ is never written to, so other campaigns keep theirs.
        for key in ("hook", "supporting"):
            lines = overlay_copy_overrides.get(key)
            if lines:
                template[key] = {
                    "lines": [str(line) for line in lines if str(line).strip()]
                }
        cta_text = overlay_copy_overrides.get("cta")
        if cta_text:
            template["cta"] = {**(template.get("cta") or {}), "text": str(cta_text)}

    package_path = require_content_package()
    package_text = package_path.read_text(encoding="utf-8")
    try:
        ig_caption = extract_piece2_instagram_caption(package_text)
    except RuntimeError as exc:
        if caption_override:
            ig_caption = caption_override
        else:
            # Revisions may run against campaigns whose latest package renamed pieces.
            existing_caption = None
            if out_dir is not None and (out_dir / "caption.md").is_file():
                existing_caption = (out_dir / "caption.md").read_text(encoding="utf-8")
            if existing_caption:
                ig_caption = existing_caption
            else:
                exit_error(
                    str(exc),
                    hint="Latest package needs a Ritual Reel piece, or use: python3 main.py create all",
                )
    if caption_override:
        ig_caption = caption_override

    source_entries = list(template["sources"])
    sources: list[Path] = []
    for entry in source_entries:
        path = ROOT / entry["relative_path"]
        if not path.exists():
            console.print(f"[red]Source video not found:[/red] {entry['relative_path']}")
            raise typer.Exit(1)
        sources.append(path)

    try:
        font_path = resolve_font(typography)
    except ProductionConfigError as exc:
        console.print(f"[red]Production config error:[/red] {exc}")
        raise typer.Exit(1) from None

    probes = [probe_video(path) for path in sources]
    source_targets = [
        float(entry.get("target_duration_seconds", template["target_duration_seconds"]))
        for entry in source_entries
    ]
    # Equalize missing per-clip targets when only the piece total is set.
    if all("target_duration_seconds" not in entry for entry in source_entries):
        equal = float(template["target_duration_seconds"]) / len(source_entries)
        source_targets = [equal] * len(source_entries)

    segments = plan_ritual_clip_segments(
        probes,
        source_targets,
        float(template["target_duration_seconds"]),
        resolved["looping"],
    )
    output_duration = sum(float(segment["output_duration_seconds"]) for segment in segments)
    timeline_starts: list[float] = []
    cursor = 0.0
    for segment in segments:
        timeline_starts.append(cursor)
        cursor += float(segment["output_duration_seconds"])

    open_end = timeline_starts[1] if len(timeline_starts) > 1 else output_duration
    middle_end = timeline_starts[2] if len(timeline_starts) > 2 else output_duration
    close_start = timeline_starts[-1]

    hook_at = min(float(animation["hook_appear_at_seconds"]), max(open_end - 0.05, 0.0))
    supporting_at = open_end
    supporting_end = middle_end
    footer_at = close_start + float(animation["footer_appear_at_seconds"])
    footer_at = min(footer_at, max(output_duration - 0.05, 0.0))
    if cta_appear_at_seconds is not None:
        cta_at = min(float(cta_appear_at_seconds), max(output_duration - 0.05, 0.0))
        cta_at = max(cta_at, 0.0)
    else:
        cta_at = max(
            output_duration - float(animation["cta_appear_from_end_seconds"]),
            footer_at,
        )
        cta_at = min(cta_at, max(output_duration - 0.05, 0.0))

    text_timing = {
        "hook_appear_at_seconds": round(hook_at, 3),
        "supporting_appear_at_seconds": round(supporting_at, 3),
        "supporting_end_at_seconds": round(supporting_end, 3),
        "footer_appear_at_seconds": round(footer_at, 3),
        "cta_appear_at_seconds": round(cta_at, 3),
    }

    if out_dir is None:
        out_dir = single_render_dir("ritual_reel")
    out_dir.mkdir(parents=True, exist_ok=True)
    if preserve_existing:
        from review.versioning import ensure_baseline_version

        ensure_baseline_version(out_dir)
    video_name = output_filename or "ritual_reel_draft.mp4"
    video_path = out_dir / video_name
    if preserve_existing and video_path.exists() and output_filename is None:
        raise RuntimeError("Refusing to overwrite existing Ritual Reel draft.")
    caption_path = out_dir / (caption_filename or "caption.md")
    settings_path = out_dir / "render_settings.json"

    overlays = {
        "hook": out_dir / "_overlay_hook.png",
        "supporting": out_dir / "_overlay_supporting.png",
        "footer": out_dir / "_overlay_footer.png",
        "cta": out_dir / "_overlay_cta.png",
    }

    console.print(f"[dim]Content package:[/dim] {package_path.name}")
    for path, segment in zip(sources, segments):
        console.print(
            f"[dim]Clip:[/dim] {path.relative_to(ROOT)} — {segment['notes']}"
        )
    console.print(
        f"[dim]Total duration:[/dim] {output_duration:.2f}s "
        f"(target {float(template['target_duration_seconds']):.0f}s)"
    )
    console.print("[dim]Rendering ritual reel with global Production Brain…[/dim]")

    width = int(exports["width"])
    height = int(exports["height"])
    safe_margins = resolved["safe_margins"]
    bottom_floor = height - int(safe_margins["bottom"])
    supporting = template.get("supporting") or {"lines": []}

    render_overlay_layer(
        width=width,
        height=height,
        lines=list(template["hook"]["lines"]),
        font_path=font_path,
        font_size=int(typography["hook"]["size"]),
        y_ratio=float(layout["hook_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=overlays["hook"],
    )
    render_overlay_layer(
        width=width,
        height=height,
        lines=list(supporting["lines"]),
        font_path=font_path,
        font_size=int(typography["hook"]["size"]),
        y_ratio=float(layout["hook_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=overlays["supporting"],
    )
    render_overlay_layer(
        width=width,
        height=height,
        lines=list(template["footer"]["lines"]),
        font_path=font_path,
        font_size=int(typography["footer"]["size"]),
        y_ratio=float(layout["footer_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=overlays["footer"],
        bottom_floor=bottom_floor,
    )
    render_overlay_layer(
        width=width,
        height=height,
        lines=[str(template["cta"]["text"])],
        font_path=font_path,
        font_size=int(typography["cta"]["size"]),
        y_ratio=float(layout["cta_region"]["y_ratio"]),
        typography=typography,
        colors=colors,
        layout=layout,
        safe_margins=safe_margins,
        output_path=overlays["cta"],
        bottom_floor=bottom_floor,
    )

    try:
        render_ritual_reel(
            sources,
            segments,
            video_path,
            overlays,
            brain,
            text_timing,
        )
    finally:
        for path in overlays.values():
            path.unlink(missing_ok=True)

    # Preserve an existing caption unless this render supplies a deliberate override.
    if caption_override or not caption_path.is_file():
        caption_body = ig_caption
        if not caption_body.lstrip().startswith("#"):
            caption_body = (
                "# Captions — The Ritual Reel\n\n"
                "## Instagram\n\n"
                f"{ig_caption}\n"
            )
        caption_path.write_text(caption_body if caption_body.endswith("\n") else caption_body + "\n", encoding="utf-8")

    clip_records = []
    for path, probe, segment, start in zip(sources, probes, segments, timeline_starts):
        clip_records.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "width": probe["width"],
                "height": probe["height"],
                "source_duration_seconds": round(float(probe["duration"]), 3),
                "timeline_start_seconds": round(start, 3),
                "timeline_end_seconds": round(
                    start + float(segment["output_duration_seconds"]), 3
                ),
                "segment": segment,
            }
        )

    settings = {
        "piece": "Piece #2 — The Ritual Reel",
        "content_package": package_path.name,
        "style_guide": brain["style_guide"],
        "production": {
            "global_defaults": brain["global_defaults"],
            "typography": typography,
            "colors": colors,
            "layout": layout,
            "animation": animation,
            "exports": exports,
            "safe_zones": brain["safe_zones"],
            "template": template,
        },
        "resolved": {
            **resolved,
            "font_path": font_path,
            "transition_style": brain["global_defaults"].get("transition_style", "cut"),
            "opening_fade_seconds": animation["opening_fade_seconds"],
            "closing_fade_seconds": animation["closing_fade_seconds"],
            **text_timing,
        },
        "clips": clip_records,
        "output": {
            "width": exports["width"],
            "height": exports["height"],
            "fps": exports["fps"],
            "codec": exports["codec"],
            "bitrate": exports["bitrate"],
            "audio": exports["audio"],
            "duration_seconds": round(output_duration, 3),
            "video": video_path.name,
        },
    }
    if versioning:
        settings["versioning"] = {
            "version": versioning.get("version"),
            "parent_version": versioning.get("parent_version"),
            "revision_request_ids": list(versioning.get("revision_request_ids") or []),
            "addressed_recommendation_ids": list(
                versioning.get("addressed_recommendation_ids") or []
            ),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "review_status": "awaiting_review",
        }
        # Each version keeps its own settings snapshot. The configuration that
        # produced the original render is left exactly as it was found — a new
        # version is added beside it, never over it.
        version_settings_path = out_dir / f"render_settings_v{versioning.get('version')}.json"
        version_settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    if not versioning or not settings_path.is_file():
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    console.print(f"[green]Draft folder:[/green] {out_dir}")
    if versioning:
        console.print(
            f"[green]Version:[/green] v{versioning.get('version')} → {video_path.name}"
        )
    return out_dir


# --- Create all: render queue ---

# Templates BettyOS already knows how to render. Do not invent new ones here.
SUPPORTED_RENDER_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "command": "ritual-reel",
        "piece_id": "ritual-reel",
        "folder_name": "ritual_reel",
        "title_regex": r"ritual\s+reel",
        "label": "Ritual Reel",
    },
    {
        "command": "page-turn-loop",
        "piece_id": "page-turn-loop",
        "folder_name": "page_turn_loop",
        "title_regex": r"page[\s\-]?turn\s+loop",
        "label": "Page Turn Loop",
    },
)


def match_supported_render_queue(
    package_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Match package pieces to known render templates; leave unsupported pieces skipped."""
    pieces = list_content_pieces(package_text)
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    claimed_templates: set[str] = set()

    for piece in pieces:
        matched: dict[str, Any] | None = None
        for template in SUPPORTED_RENDER_TEMPLATES:
            if template["piece_id"] in claimed_templates:
                continue
            if re.search(template["title_regex"], piece["title"], flags=re.IGNORECASE):
                matched = template
                break
        if matched is None:
            skipped.append(
                {
                    "heading": piece["heading"],
                    "title": piece["title"],
                    "reason": "No supported render template",
                }
            )
            continue
        claimed_templates.add(matched["piece_id"])
        queued.append(
            {
                **matched,
                "piece_heading": piece["heading"],
                "piece_title": piece["title"],
                "piece_number": piece["number"],
            }
        )

    return queued, skipped


def run_create_all() -> None:
    """Render every supported draft from the latest content package into one campaign folder."""
    package_path = require_content_package()
    package_text = package_path.read_text(encoding="utf-8")
    queued, skipped = match_supported_render_queue(package_text)

    if not queued and not skipped:
        exit_error(
            "Content package has no recognizable content pieces.",
            hint="Run python3 main.py repurpose to generate a package with Piece headings.",
        )

    if not queued:
        console.print()
        console.print("[yellow]No supported pieces to render in the latest package.[/yellow]")
        console.print("[dim]Supported templates: ritual-reel, page-turn-loop[/dim]")
        console.print(f"[yellow]Skipped unsupported:[/yellow] {len(skipped)}")
        for item in skipped:
            console.print(f"  • {item['heading']}")
        return

    campaign_dir = new_campaign_dir()

    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("Render Queue", "bold"),
                "\n",
                (f"Package: {package_path.name}", "dim"),
            ),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print(f"[dim]Campaign folder:[/dim] {campaign_dir}")
    console.print(f"[dim]Queued:[/dim] {len(queued)}  [dim]Skipped:[/dim] {len(skipped)}")
    console.print()

    successful: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    runners = {
        "page-turn-loop": run_create_page_turn_loop,
        "ritual-reel": run_create_ritual_reel,
    }

    for index, job in enumerate(queued, start=1):
        label = job["label"]
        out_dir = campaign_dir / str(job["folder_name"])
        console.print(
            f"[bold][{index}/{len(queued)}][/bold] Rendering {label} "
            f"from {job['piece_heading']}…"
        )
        runner = runners[str(job["command"])]
        try:
            result_dir = runner(out_dir=out_dir)
            successful.append(
                {
                    "label": label,
                    "piece": job["piece_heading"],
                    "path": str(result_dir),
                }
            )
        except (KeyboardInterrupt, EOFError):
            raise
        except typer.Exit as exc:
            code = getattr(exc, "exit_code", 1)
            if code in (0, None):
                raise
            failed.append(
                {
                    "label": label,
                    "piece": job["piece_heading"],
                    "error": "Render exited with an error",
                }
            )
            console.print(f"[yellow]Continuing queue after failure:[/yellow] {label}")
        except Exception as exc:  # noqa: BLE001 — queue must continue after one failure
            failed.append(
                {
                    "label": label,
                    "piece": job["piece_heading"],
                    "error": str(exc) or exc.__class__.__name__,
                }
            )
            console.print(f"[red]Failed:[/red] {label} — {exc}")
            console.print(f"[yellow]Continuing queue after failure:[/yellow] {label}")
        console.print()

    summary_lines = [
        "# Render Queue Summary",
        "",
        f"**Content package:** `{package_path.name}`",
        f"**Campaign folder:** `{campaign_dir.name}`",
        "",
        "## Successful renders",
        "",
    ]
    if successful:
        for item in successful:
            summary_lines.append(f"- **{item['label']}** — {item['piece']} → `{item['path']}`")
    else:
        summary_lines.append("- None")

    summary_lines.extend(["", "## Failed renders", ""])
    if failed:
        for item in failed:
            summary_lines.append(
                f"- **{item['label']}** — {item['piece']} ({item['error']})"
            )
    else:
        summary_lines.append("- None")

    summary_lines.extend(["", "## Skipped unsupported pieces", ""])
    if skipped:
        for item in skipped:
            summary_lines.append(f"- {item['heading']} — {item['reason']}")
    else:
        summary_lines.append("- None")
    summary_lines.append("")

    summary_path = campaign_dir / "render_queue_summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    console.print("[bold]Render queue complete[/bold]")
    console.print(f"[green]Successful:[/green] {len(successful)}")
    for item in successful:
        console.print(f"  • {item['label']} → {item['path']}")
    console.print(f"[red]Failed:[/red] {len(failed)}")
    for item in failed:
        console.print(f"  • {item['label']} — {item['error']}")
    console.print(f"[yellow]Skipped unsupported:[/yellow] {len(skipped)}")
    for item in skipped:
        console.print(f"  • {item['heading']}")
    console.print(f"[green]Summary:[/green] {summary_path}")


# --- Review Brain ---



def build_render_review_context(render_dirs: list[Path]) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Assemble render text context and optional frame image blocks for vision critique."""
    if not render_dirs:
        return "No render outputs present.", [], []

    require_ffmpeg()
    frame_root = OUTPUTS_DIR / ".review_frames"
    if frame_root.exists():
        shutil.rmtree(frame_root)
    frame_root.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []
    names: list[str] = []
    image_blocks: list[dict[str, Any]] = []

    for render_dir in render_dirs:
        label = relative_to_root(render_dir)
        names.append(label)
        settings_path = render_dir / "render_settings.json"
        caption_path = render_dir / "caption.md"
        videos = sorted(render_dir.glob("*.mp4"))

        chunk = [f"### Render: {label}"]
        if settings_path.is_file():
            chunk.append("render_settings.json:")
            chunk.append(settings_path.read_text(encoding="utf-8").strip())
        else:
            chunk.append("render_settings.json: missing")
        if caption_path.is_file():
            chunk.append("caption.md:")
            chunk.append(caption_path.read_text(encoding="utf-8").strip())
        if videos:
            chunk.append("video files: " + ", ".join(v.name for v in videos))
        sections.append("\n".join(chunk))

        for video in videos:
            try:
                probe = probe_video(video)
            except Exception:
                continue
            duration = max(float(probe["duration"]), 0.1)
            stamps = sorted(
                {
                    min(0.35, duration * 0.05),
                    duration * 0.45,
                    max(duration - 1.0, duration * 0.85),
                }
            )
            piece_dir = frame_root / render_dir.name
            piece_dir.mkdir(parents=True, exist_ok=True)
            for index, stamp in enumerate(stamps, start=1):
                frame_path = piece_dir / f"{video.stem}_frame_{index}.jpg"
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        f"{stamp:.3f}",
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        str(frame_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 or not frame_path.is_file():
                    continue
                image_blocks.append(image_block(frame_path))
                sections.append(
                    f"Attached frame for visual review: {render_dir.name}/{frame_path.name} "
                    f"(~{stamp:.2f}s into {video.name})"
                )

    return "\n\n".join(sections), names, image_blocks


def run_review_workflow() -> None:
    """Critique the latest content package (and renders if present). Critique only."""
    from review.review_engine import run_creative_review

    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("Review Brain", "bold"),
                "\n",
                ("Creative Director critique — no rewrites.", "dim"),
            ),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    package_path = require_content_package()
    package_text = package_path.read_text(encoding="utf-8")
    console.print(f"[dim]Content package:[/dim] {package_path.name}")

    render_dirs = find_latest_render_dirs()
    if render_dirs:
        for path in render_dirs:
            console.print(f"[dim]Render:[/dim] {relative_to_root(path)}")
    else:
        console.print("[dim]No render outputs found; reviewing package only.[/dim]")

    campaign_goal = extract_campaign_goal(package_text) or "Not specified"
    console.print(f"[dim]Campaign goal:[/dim] {campaign_goal}")

    try:
        brand_brain = require_brand_context()
        production_brain = load_production_context_for_review()
    except BettyOSError as exc:
        handle_betty_error(exc)
        raise  # pragma: no cover
    render_context, render_names, image_blocks = build_render_review_context(render_dirs)
    api_key = require_api_key()
    console.print("[dim]Running Creative Director review…[/dim]")

    try:
        review_path, scores_path, result = run_creative_review(
            brand_brain=brand_brain,
            production_brain=production_brain,
            content_package=package_text,
            campaign_goal=campaign_goal,
            render_context=render_context,
            api_key=api_key,
            outputs_dir=OUTPUTS_DIR,
            package_name=package_path.name,
            render_names=render_names,
            image_blocks=image_blocks or None,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    except anthropic.APIError as exc:
        console.print(f"[red]Claude request failed:[/red] {exc.__class__.__name__}")
        console.print("[dim]Check your network connection and API key, then try again.[/dim]")
        raise typer.Exit(1) from None

    console.print(
        f"[green]Overall readiness:[/green] {result.overall_readiness.score:.1f} / 10"
    )
    console.print(f"[green]Review saved:[/green] {review_path}")
    console.print(f"[green]Scores saved:[/green] {scores_path}")


# --- Approval Layer ---

APPROVAL_STATUSES = ("approved", "needs_revision", "rejected", "awaiting_review")
APPROVAL_STATUS_LABELS = {
    "approved": "Approved",
    "needs_revision": "Needs Revision",
    "rejected": "Rejected",
    "awaiting_review": "Awaiting Review",
}
APPROVAL_CHOICE_MAP = {
    "1": "approved",
    "2": "needs_revision",
    "3": "rejected",
    "4": "skip",
}



def discover_campaign_review_items(campaign_dir: Path) -> list[dict[str, str]]:
    """Find reviewable assets in a campaign folder (videos + captions)."""
    items: list[dict[str, str]] = []
    subdirs = sorted(
        p for p in campaign_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    for subdir in subdirs:
        files = sorted(p for p in subdir.iterdir() if p.is_file() and not p.name.startswith("."))
        for path in files:
            suffix = path.suffix.lower()
            if suffix in {".mp4", ".mov"}:
                item_type = "video"
            elif path.name.lower() == "caption.md":
                item_type = "caption"
            else:
                continue
            rel = path.relative_to(campaign_dir).as_posix()
            items.append(
                {
                    "item_name": path.name,
                    "item_type": item_type,
                    "file_path": rel,
                }
            )
    return items


def load_approvals(campaign_dir: Path) -> dict[str, Any]:
    from src.templates.approvals_store import load_campaign_approvals

    return load_campaign_approvals(campaign_dir)


def approvals_by_path(approvals: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for entry in approvals.get("items", []):
        if isinstance(entry, dict) and entry.get("file_path"):
            by_path[str(entry["file_path"])] = entry
    return by_path


def write_approvals(campaign_dir: Path, approvals: dict[str, Any]) -> Path:
    from src.templates.approvals_store import write_campaign_approvals

    return write_campaign_approvals(campaign_dir, approvals)


def write_approval_summary(campaign_dir: Path, items: list[dict[str, Any]]) -> Path:
    path = campaign_dir / "approval_summary.md"
    groups: dict[str, list[dict[str, Any]]] = {status: [] for status in APPROVAL_STATUSES}
    for item in items:
        status = str(item.get("status") or "awaiting_review")
        if status not in groups:
            status = "awaiting_review"
        groups[status].append(item)

    lines = [
        "# Approval Summary",
        "",
        f"**Campaign:** `{campaign_dir.name}`",
        f"**Updated:** {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for status in APPROVAL_STATUSES:
        lines.append(f"## {APPROVAL_STATUS_LABELS[status]}")
        lines.append("")
        bucket = groups[status]
        if not bucket:
            lines.append("- None")
            lines.append("")
            continue
        for item in bucket:
            note = str(item.get("note") or "").strip()
            note_bit = f" — _{note}_" if note else ""
            lines.append(
                f"- **{item.get('item_name')}** (`{item.get('file_path')}`){note_bit}"
            )
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def merge_approval_items(
    discovered: list[dict[str, str]],
    existing_by_path: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the current item list, preserving prior decisions."""
    merged: list[dict[str, Any]] = []
    for discovered_item in discovered:
        prior = existing_by_path.get(discovered_item["file_path"])
        if prior:
            merged.append(
                {
                    "item_name": discovered_item["item_name"],
                    "item_type": discovered_item["item_type"],
                    "file_path": discovered_item["file_path"],
                    "status": str(prior.get("status") or "awaiting_review"),
                    "note": str(prior.get("note") or ""),
                    "reviewed_at": prior.get("reviewed_at"),
                }
            )
        else:
            merged.append(
                {
                    "item_name": discovered_item["item_name"],
                    "item_type": discovered_item["item_type"],
                    "file_path": discovered_item["file_path"],
                    "status": "awaiting_review",
                    "note": "",
                    "reviewed_at": None,
                }
            )
    return merged


def prompt_approval_decision(item: dict[str, Any], index: int, total: int) -> dict[str, Any]:
    """Ask for one approval decision; skip preserves the existing record."""
    current = str(item.get("status") or "awaiting_review")
    current_label = APPROVAL_STATUS_LABELS.get(current, current)
    console.print()
    console.print(f"[bold][{index}/{total}][/bold] {item['item_name']}")
    console.print(f"[dim]Type:[/dim] {item['item_type']}")
    console.print(f"[dim]Path:[/dim] {item['file_path']}")
    console.print(f"[dim]Current:[/dim] {current_label}")
    if item.get("note"):
        console.print(f"[dim]Note:[/dim] {item['note']}")
    console.print(
        "1. approved  ·  2. needs_revision  ·  3. rejected  ·  4. skip for now"
    )
    choice = Prompt.ask("Decision", choices=["1", "2", "3", "4"], default="4").strip()
    action = APPROVAL_CHOICE_MAP[choice]

    if action == "skip":
        return item

    note = ""
    if action in {"needs_revision", "rejected"}:
        note = Prompt.ask("Note (optional)", default="", show_default=False).strip()

    updated = dict(item)
    updated["status"] = action
    updated["note"] = note
    updated["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    return updated


def run_approve_workflow() -> None:
    """Human approval pass over the latest campaign assets. Does not alter content."""
    try:
        campaign_dir = require_latest_campaign_dir()
    except BettyOSError as exc:
        handle_betty_error(exc)
        raise  # pragma: no cover

    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("Approval Layer", "bold"),
                "\n",
                (f"Campaign: {campaign_dir.name}", "dim"),
            ),
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()

    summary_path = campaign_dir / "render_queue_summary.md"
    if summary_path.is_file():
        console.print(f"[dim]Queue summary:[/dim] {summary_path.name}")
        # Show a short excerpt — successful/failed counts if present.
        summary_text = summary_path.read_text(encoding="utf-8")
        for line in summary_text.splitlines():
            if line.startswith("**Content package:**") or line.startswith(
                "**Campaign folder:**"
            ):
                console.print(f"[dim]{line}[/dim]")
    else:
        console.print("[dim]No render_queue_summary.md in this campaign.[/dim]")

    discovered = discover_campaign_review_items(campaign_dir)
    if not discovered:
        console.print(
            "[yellow]Campaign folder has no reviewable render assets yet.[/yellow]\n"
            "Expected video drafts and caption.md files inside render subfolders."
        )
        # Still write empty approval files so the campaign has a clear state.
        empty = {"campaign": campaign_dir.name, "items": []}
        approvals_path = write_approvals(campaign_dir, empty)
        summary_out = write_approval_summary(campaign_dir, [])
        console.print(f"[green]Approvals saved:[/green] {approvals_path}")
        console.print(f"[green]Summary saved:[/green] {summary_out}")
        raise typer.Exit(0)

    existing = load_approvals(campaign_dir)
    items = merge_approval_items(discovered, approvals_by_path(existing))
    console.print(f"[dim]Reviewable items:[/dim] {len(items)}")
    console.print(
        "[dim]Existing decisions are kept. Choose 1–3 to set/revise, or 4 to skip.[/dim]"
    )

    try:
        for index, item in enumerate(items, start=1):
            items[index - 1] = prompt_approval_decision(item, index, len(items))
            write_approvals(campaign_dir, {"items": items})
            write_approval_summary(campaign_dir, items)
    except (KeyboardInterrupt, EOFError):
        write_approvals(campaign_dir, {"items": items})
        write_approval_summary(campaign_dir, items)
        console.print("\n[dim]Stopped — progress saved.[/dim]")
        raise typer.Exit(0) from None

    approvals_path = write_approvals(campaign_dir, {"items": items})
    summary_out = write_approval_summary(campaign_dir, items)

    counts = {status: 0 for status in APPROVAL_STATUSES}
    for item in items:
        status = str(item.get("status") or "awaiting_review")
        counts[status if status in counts else "awaiting_review"] += 1

    console.print()
    console.print("[bold]Approval pass complete[/bold]")
    console.print(f"[green]Approved:[/green] {counts['approved']}")
    console.print(f"[yellow]Needs revision:[/yellow] {counts['needs_revision']}")
    console.print(f"[red]Rejected:[/red] {counts['rejected']}")
    console.print(f"[dim]Awaiting review:[/dim] {counts['awaiting_review']}")
    console.print(f"[green]Approvals:[/green] {approvals_path}")
    console.print(f"[green]Summary:[/green] {summary_out}")


# --- CLI ---


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Plan a production session (default when no subcommand is given)."""
    if ctx.invoked_subcommand is not None:
        return
    run_plan_workflow()


@app.command("ingest")
def ingest_command(
    folder: Path = typer.Argument(..., help="Folder of photos/videos to index."),
    force: bool = typer.Option(
        False, "--force", help="Re-analyze assets that are already indexed."
    ),
) -> None:
    """Index photos and videos into the local asset library."""
    try:
        ingest_folder(folder, force=force)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None


@app.command("repurpose")
def repurpose_command() -> None:
    """Turn indexed assets into a brand-aligned content package."""
    run_repurpose_workflow()


@app.command("review")
def review_command() -> None:
    """Score the latest package and renders (Creative Director critique only)."""
    try:
        run_review_workflow()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None
    except BettyOSError as exc:
        handle_betty_error(exc)


@app.command("approve")
def approve_command() -> None:
    """Approve, revise, or reject assets in the latest campaign folder."""
    try:
        run_approve_workflow()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None
    except BettyOSError as exc:
        handle_betty_error(exc)


create_app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    help="Render editable video drafts from content package pieces.",
)
app.add_typer(create_app, name="create")


@create_app.command("page-turn-loop")
def create_page_turn_loop_command() -> None:
    """Render the Page Turn Loop draft (single piece)."""
    try:
        run_create_page_turn_loop()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None
    except BettyOSError as exc:
        handle_betty_error(exc)


@create_app.command("ritual-reel")
def create_ritual_reel_command() -> None:
    """Render the Ritual Reel draft (single piece)."""
    try:
        run_create_ritual_reel()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None
    except BettyOSError as exc:
        handle_betty_error(exc)


@create_app.command("all")
def create_all_command() -> None:
    """Render every supported piece from the latest package into one campaign folder."""
    try:
        run_create_all()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(0) from None
    except BettyOSError as exc:
        handle_betty_error(exc)


if __name__ == "__main__":
    app()
