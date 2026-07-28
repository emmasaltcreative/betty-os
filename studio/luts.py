"""Real .cube LUT parsing, validation, and brand library storage."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

from src.common import DEFAULT_BRAND_ID, ROOT, relative_to_root
from src.persistence import atomic_write_json, load_json
from studio.models import LutRecord, utc_now_iso
from studio.paths import luts_dir, luts_index, sanitize_filename


@dataclass
class CubeLut:
    title: str
    size: int
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]
    table: np.ndarray  # shape (size, size, size, 3), float32, RGB


def parse_cube(path: Path) -> CubeLut:
    """Parse a .cube LUT file. Raises ValueError on invalid content."""
    path = Path(path)
    if not path.is_file():
        raise ValueError("LUT file does not exist.")
    if path.stat().st_size <= 0:
        raise ValueError("LUT file is empty.")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    title = path.stem
    size: int | None = None
    domain_min = (0.0, 0.0, 0.0)
    domain_max = (1.0, 1.0, 1.0)
    values: list[tuple[float, float, float]] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upper = line.upper()
        if upper.startswith("TITLE"):
            title = line.split(None, 1)[1].strip().strip('"') if len(line.split(None, 1)) > 1 else title
            continue
        if upper.startswith("LUT_3D_SIZE"):
            parts = line.split()
            if len(parts) < 2:
                raise ValueError("LUT_3D_SIZE is incomplete.")
            size = int(parts[1])
            continue
        if upper.startswith("DOMAIN_MIN"):
            parts = line.split()
            domain_min = (float(parts[1]), float(parts[2]), float(parts[3]))
            continue
        if upper.startswith("DOMAIN_MAX"):
            parts = line.split()
            domain_max = (float(parts[1]), float(parts[2]), float(parts[3]))
            continue
        if upper.startswith("LUT_1D_SIZE"):
            raise ValueError("1D LUTs are not supported.")
        # Data row
        parts = line.split()
        if len(parts) >= 3:
            try:
                values.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError as exc:
                raise ValueError(f"Invalid LUT data row: {line}") from exc

    if size is None:
        raise ValueError("Missing LUT_3D_SIZE.")
    if size < 2 or size > 128:
        raise ValueError(f"Unsupported cube size {size}. Supported range is 2–128.")
    expected = size ** 3
    if len(values) != expected:
        raise ValueError(f"Expected {expected} RGB triples, found {len(values)}.")
    for channel, lo, hi in zip(("R", "G", "B"), domain_min, domain_max):
        if not (hi > lo):
            raise ValueError(f"Invalid domain for {channel}: min {lo} max {hi}.")

    # .cube data is typically ordered R fastest, then G, then B
    table = np.zeros((size, size, size, 3), dtype=np.float32)
    idx = 0
    for b in range(size):
        for g in range(size):
            for r in range(size):
                table[r, g, b] = values[idx]
                idx += 1
    return CubeLut(title=title, size=size, domain_min=domain_min, domain_max=domain_max, table=table)


def apply_cube_to_rgb(rgb: np.ndarray, lut: CubeLut, intensity: float = 1.0) -> np.ndarray:
    """
    Apply 3D LUT to float RGB array in [0,1], shape (H,W,3).
    Intensity blends original and transformed when 0 < intensity < 1.
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))
    if intensity <= 0:
        return rgb
    h, w, _ = rgb.shape
    dmin = np.array(lut.domain_min, dtype=np.float32)
    dmax = np.array(lut.domain_max, dtype=np.float32)
    span = np.maximum(dmax - dmin, 1e-8)
    coords = (rgb.astype(np.float32) - dmin) / span
    coords = np.clip(coords, 0.0, 1.0)
    scaled = coords * (lut.size - 1)
    r0 = np.floor(scaled[..., 0]).astype(np.int32)
    g0 = np.floor(scaled[..., 1]).astype(np.int32)
    b0 = np.floor(scaled[..., 2]).astype(np.int32)
    r1 = np.minimum(r0 + 1, lut.size - 1)
    g1 = np.minimum(g0 + 1, lut.size - 1)
    b1 = np.minimum(b0 + 1, lut.size - 1)
    fr = scaled[..., 0] - r0
    fg = scaled[..., 1] - g0
    fb = scaled[..., 2] - b0

    def sample(rr, gg, bb):
        return lut.table[rr, gg, bb]

    c000 = sample(r0, g0, b0)
    c100 = sample(r1, g0, b0)
    c010 = sample(r0, g1, b0)
    c110 = sample(r1, g1, b0)
    c001 = sample(r0, g0, b1)
    c101 = sample(r1, g0, b1)
    c011 = sample(r0, g1, b1)
    c111 = sample(r1, g1, b1)

    fr = fr[..., None]
    fg = fg[..., None]
    fb = fb[..., None]
    c00 = c000 * (1 - fr) + c100 * fr
    c10 = c010 * (1 - fr) + c110 * fr
    c01 = c001 * (1 - fr) + c101 * fr
    c11 = c011 * (1 - fr) + c111 * fr
    c0 = c00 * (1 - fg) + c10 * fg
    c1 = c01 * (1 - fg) + c11 * fg
    mapped = c0 * (1 - fb) + c1 * fb
    if intensity >= 1.0:
        return np.clip(mapped, 0.0, 1.0)
    blended = rgb.astype(np.float32) * (1 - intensity) + mapped * intensity
    return np.clip(blended, 0.0, 1.0)


def _load_raw(brand_id: str) -> dict:
    data = load_json(luts_index(brand_id), default={"luts": []})
    return data if isinstance(data, dict) else {"luts": []}


def _save_raw(brand_id: str, data: dict) -> None:
    data["brand_id"] = brand_id
    data["updated_at"] = utc_now_iso()
    atomic_write_json(luts_index(brand_id), data)


def list_luts(brand_id: str = DEFAULT_BRAND_ID, *, include_archived: bool = False) -> list[LutRecord]:
    raw = _load_raw(brand_id)
    records = [LutRecord.from_dict(x) for x in raw.get("luts") or [] if isinstance(x, dict)]
    if include_archived:
        return records
    return [r for r in records if r.status != "Archived"]


def get_lut(lut_id: str, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord | None:
    for record in list_luts(brand_id, include_archived=True):
        if record.lut_id == lut_id:
            return record
    return None


def resolve_lut_path(record: LutRecord) -> Path:
    path = Path(record.file_path)
    if not path.is_absolute():
        path = ROOT / path
    return path


def upload_lut(
    source: Path,
    *,
    brand_id: str = DEFAULT_BRAND_ID,
    display_name: str,
    default_intensity: float = 1.0,
) -> LutRecord:
    source = Path(source)
    lut_id = f"lut_{uuid4().hex[:10]}"
    safe = sanitize_filename(source.name)
    dest = luts_dir(brand_id) / f"{lut_id}_{safe}"
    if dest.suffix.lower() != ".cube":
        dest = dest.with_suffix(".cube")
    shutil.copy2(source, dest)

    now = utc_now_iso()
    status = "Ready"
    notes = ""
    cube_size = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    try:
        cube = parse_cube(dest)
        cube_size = cube.size
        domain_min = list(cube.domain_min)
        domain_max = list(cube.domain_max)
        display = display_name.strip() or cube.title
    except ValueError as exc:
        status = "Invalid File"
        notes = str(exc)
        display = display_name.strip() or source.stem

    record = LutRecord(
        lut_id=lut_id,
        brand_id=brand_id,
        display_name=display,
        file_path=relative_to_root(dest),
        original_filename=source.name,
        format="cube",
        cube_size=cube_size,
        domain_min=domain_min,
        domain_max=domain_max,
        default_intensity=float(np.clip(default_intensity, 0.0, 1.0)),
        suitable_use_cases=["editorial", "film_character"],
        status=status,
        created_at=now,
        updated_at=now,
        validation_notes=notes,
    )
    raw = _load_raw(brand_id)
    raw.setdefault("luts", []).append(record.to_dict())
    _save_raw(brand_id, raw)
    saved = get_lut(lut_id, brand_id)
    if saved is None:
        raise RuntimeError("LUT write could not be verified.")
    return saved


def validate_lut_record(lut_id: str, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord:
    record = get_lut(lut_id, brand_id)
    if record is None:
        raise KeyError(lut_id)
    path = resolve_lut_path(record)
    raw = _load_raw(brand_id)
    for item in raw.get("luts") or []:
        if not isinstance(item, dict) or item.get("lut_id") != lut_id:
            continue
        try:
            cube = parse_cube(path)
            item["status"] = "Ready"
            item["cube_size"] = cube.size
            item["domain_min"] = list(cube.domain_min)
            item["domain_max"] = list(cube.domain_max)
            item["validation_notes"] = ""
        except ValueError as exc:
            item["status"] = "Invalid File"
            item["validation_notes"] = str(exc)
        item["updated_at"] = utc_now_iso()
        break
    _save_raw(brand_id, raw)
    return get_lut(lut_id, brand_id) or record


def rename_lut(lut_id: str, display_name: str, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord:
    return _update(lut_id, brand_id, display_name=display_name.strip())


def set_default_intensity(lut_id: str, intensity: float, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord:
    return _update(lut_id, brand_id, default_intensity=float(np.clip(intensity, 0.0, 1.0)))


def archive_lut(lut_id: str, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord:
    return _update(lut_id, brand_id, status="Archived")


def restore_lut(lut_id: str, brand_id: str = DEFAULT_BRAND_ID) -> LutRecord:
    record = validate_lut_record(lut_id, brand_id)
    return record


def _update(lut_id: str, brand_id: str, **updates) -> LutRecord:
    raw = _load_raw(brand_id)
    found = False
    for item in raw.get("luts") or []:
        if isinstance(item, dict) and item.get("lut_id") == lut_id:
            item.update(updates)
            item["updated_at"] = utc_now_iso()
            found = True
            break
    if not found:
        raise KeyError(lut_id)
    _save_raw(brand_id, raw)
    record = get_lut(lut_id, brand_id)
    if record is None:
        raise RuntimeError("LUT update could not be verified.")
    return record


def load_cube_for_record(record: LutRecord) -> CubeLut:
    if record.status != "Ready":
        raise ValueError(f"LUT is not Ready ({record.status}).")
    return parse_cube(resolve_lut_path(record))
