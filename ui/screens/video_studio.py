"""Video Studio — platform-specific vertical video creator for BettyOS.

Uses local FFmpeg for repeatable, downloadable MP4 exports. Source clips are
stored in a dedicated workspace; rendering never overwrites source footage.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

PRESETS = {
    "Instagram Reels · 9:16": (1080, 1920),
    "Snapchat · 9:16": (1080, 1920),
    "Pinterest Video Pin · 9:16": (1080, 1920),
    "Pinterest Video Pin · 2:3": (1000, 1500),
}
ROOT = Path("outputs") / "video_studio"
ROOT.mkdir(parents=True, exist_ok=True)


def _font(size: int, serif: bool = True):
    names = (
        ["/System/Library/Fonts/Supplemental/Georgia.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
        if serif else
        ["/System/Library/Fonts/Supplemental/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def _title_overlay(width: int, height: int, headline: str, eyebrow: str,
                   position: str, opacity: int) -> bytes:
    """Create transparent title overlay locally; no shell text interpolation."""
    canvas = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(canvas)
    scale = width / 1080
    padding = int(width * .085)
    center = width // 2
    y = int(height * (.25 if position == "Upper" else .52 if position == "Middle" else .72))
    title_font = _font(int(76 * scale))
    small_font = _font(int(23 * scale), serif=False)
    # Constrain lines to a comfortable mobile-safe column.
    limit = width - 2 * padding
    def wrap(value, font):
        lines = []
        current = ""
        for word in value.split():
            candidate = (current + " " + word).strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] > limit and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines[:4]

    lines = wrap(headline, title_font) if headline else []
    section_h = int((len(lines) * 105 + (55 if eyebrow else 0) + 50) * scale)
    y = max(int(.16 * height), min(y, height - section_h - int(.19 * height)))
    if eyebrow or lines:
        background = Image.new("RGBA", (width, height))
        bg = ImageDraw.Draw(background)
        bg.rounded_rectangle((padding - 18, y - 25, width - padding + 18, y + section_h),
                             radius=12, fill=(245, 242, 233, max(0, min(opacity, 245))))
        canvas = Image.alpha_composite(canvas, background)
        draw = ImageDraw.Draw(canvas)
    current_y = y
    if eyebrow:
        draw.text((center, current_y), eyebrow.upper(), anchor="mt",
                  fill="#4D614E", font=small_font, stroke_width=0)
        current_y += int(60 * scale)
    for line in lines:
        draw.text((center, current_y), line, anchor="mt",
                  fill="#263A30", font=title_font)
        current_y += int(105 * scale)
    output = io.BytesIO()
    canvas.save(output, "PNG")
    return output.getvalue()


def _metadata(path: Path) -> tuple[float, int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    video = next((x for x in data.get("streams", []) if x.get("width")), {})
    return float(data.get("format", {}).get("duration", 0)), int(video.get("width", 0)), int(video.get("height", 0))


def _render(src: Path, output: Path, overlay: Path, width: int, height: int,
            start: float, duration: float, mode: str, mute: bool):
    if mode == "Fill (crop)":
        sizing = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        sizing = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0xF5F2E9"
    filters = f"[0:v]{sizing},setsar=1,fps=30[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    args = ["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(duration),
            "-i", str(src), "-loop", "1", "-i", str(overlay),
            "-filter_complex", filters, "-map", "[v]"]
    if not mute:
        args += ["-map", "0:a?"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-movflags", "+faststart", "-shortest"]
    if mute:
        args += ["-an"]
    else:
        args += ["-c:a", "aac", "-b:a", "160k"]
    args.append(str(output))
    subprocess.run(args, check=True, capture_output=True, text=True)


def render() -> None:
    st.title("Video Studio")
    st.caption("Oh Betty Jaletti · One original clip, composed for Pinterest, Snapchat & Reels")
    st.write("Upload a clip, choose a platform, set its crop and title card, then export a publish-ready MP4.")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        st.error("FFmpeg and ffprobe are required. Install with `brew install ffmpeg` and restart BettyOS.")
        return
    uploaded = st.file_uploader("01 / Source video", type=["mp4", "mov", "m4v", "webm"],
                               key="video_studio_upload")
    if uploaded is None:
        st.info("Start by adding your original product video. No footage is changed until you export.")
        return
    data = uploaded.getvalue()
    if not data:
        st.warning("This file is empty.")
        return
    # Stable session path prevents rerun-from-slider changing the uploaded footage.
    import hashlib
    digest = hashlib.sha256(data).hexdigest()[:16]
    source = ROOT / f"source_{digest}{Path(uploaded.name).suffix.lower()}"
    if not source.exists():
        source.write_bytes(data)
    try:
        length, source_w, source_h = _metadata(source)
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        st.error(f"Couldn't read the source video: {exc}")
        return
    if length <= 0:
        st.error("This clip has no usable duration.")
        return

    left, right = st.columns([1, 1])
    with left:
        preset = st.selectbox("02 / Destination", list(PRESETS))
        width, height = PRESETS[preset]
        mode = st.radio("03 / Framing", ["Fill (crop)", "Fit (letterbox)"], horizontal=True)
        first = st.slider("Trim start (seconds)", 0.0, max(0.0, length - .1), 0.0, step=.1)
        clip_limit = min(300., length - first)
        duration = st.slider("Clip duration (seconds)", min_value=.1,
                             max_value=max(.1, clip_limit), value=min(15., max(.1, clip_limit)), step=.1)
        collection = st.text_input("04 / Collection or eyebrow", "OH BETTY JALETTI")
        headline = st.text_input("On-screen headline", "Little things, kept close.")
        position = st.selectbox("Headline position", ["Upper", "Middle", "Lower"], index=2)
        opacity = st.slider("Title panel opacity", 0, 245, 190)
        mute = st.checkbox("Mute source audio", value=False)
    with right:
        st.caption(f"Source: {source_w} × {source_h} · {length:.1f} sec")
        st.video(data)
        st.caption(f"Export: {width} × {height} · H.264 MP4 · 30 fps")
        st.info("Keep important text clear of app buttons and captions. Check the final video in each platform before publishing.")

    if st.button("Export video · MP4", type="primary"):
        output = ROOT / f"betty_{digest}_{width}x{height}_{int(first*10)}_{int(duration*10)}.mp4"
        overlay = ROOT / f"overlay_{digest}.png"
        overlay.write_bytes(_title_overlay(width, height, headline, collection, position, opacity))
        with st.spinner("Rendering your video…"):
            try:
                _render(source, output, overlay, width, height, first, duration, mode, mute)
            except subprocess.CalledProcessError as exc:
                st.error("Video export failed. Check that your original video is supported by FFmpeg.")
                st.code(exc.stderr[-1600:] if exc.stderr else str(exc))
                return
        st.success("Video exported successfully.")
        st.video(str(output))
        st.download_button("Download MP4", output.read_bytes(),
                           file_name=f"oh-betty-jaletti-{preset.split(' · ')[0].lower().replace(' ', '-')}.mp4",
                           mime="video/mp4")
        st.caption(f"Local master: {output}")
