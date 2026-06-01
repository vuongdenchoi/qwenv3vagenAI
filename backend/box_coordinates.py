"""
Hợp đồng bounding box Qwen-VL — dùng chung post_process / BE / FE.

Qwen grounding (prompt_agent):
  - JSON "c": [xmin, ymin, xmax, ymax] trên lưới 0–1000 (không phải pixel).
  - Tag <box>(ymin,xmin),(ymax,xmax)</box> trong "r".

Ảnh gửi model đã thumbnail max_edge (main.py) → box pixel = grid / 1000 * (img_w, img_h).
"""
from __future__ import annotations

import copy
import re
from typing import Any

QWEN_GRID_MAX = 1000
ANALYSIS_MAX_EDGE = 1536
COORD_FRAME_PIXEL = "frame_pixel"
COORD_SOURCE_PIXEL = "source_pixel"

BOX_TAG_RE = re.compile(
    r"<box\s*>?\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*</box\s*>?",
    re.IGNORECASE,
)


def is_qwen_grid_1000(
    coords: list[int] | tuple[int, ...],
    *,
    coord_space: str | None = None,
    img_w: int = 0,
    img_h: int = 0,
    for_model: bool = False,
) -> bool:
    """Grid Qwen 0–1000. `for_model=True`: tag/JSON từ model (luôn grid nếu 0–1000)."""
    if coord_space in (COORD_FRAME_PIXEL, COORD_SOURCE_PIXEL):
        return False
    if not coords or len(coords) < 4:
        return False
    vals = [int(v) for v in coords[:4]]
    if any(v < 0 or v > QWEN_GRID_MAX for v in vals):
        return False
    if for_model:
        return True
    if img_w > 0 and img_h > 0:
        x1, x2 = min(vals[0], vals[2]), max(vals[0], vals[2])
        y1, y2 = min(vals[1], vals[3]), max(vals[1], vals[3])
        w, h = x2 - x1, y2 - y1
        if w >= 5 and h >= 5 and x2 <= img_w and y2 <= img_h:
            if img_w > QWEN_GRID_MAX or img_h > QWEN_GRID_MAX:
                return False
    return True


def tag_to_xyxy_grid(ymin: int, xmin: int, ymax: int, xmax: int) -> list[int]:
    """<box>(ymin,xmin),(ymax,xmax)</box> → [xmin, ymin, xmax, ymax] grid."""
    return [
        min(xmin, xmax),
        min(ymin, ymax),
        max(xmin, xmax),
        max(ymin, ymax),
    ]


def box_tag_grid_candidates(v1: int, v2: int, v3: int, v4: int) -> list[tuple[list[int], float]]:
    """
    Hai cách đọc tag — model thường ghi (xmin,ymin),(xmax,ymax) dù prompt ghi (ymin,xmin).
    Trả (coords, bonus) để resolve_best_box_grid chọn đúng.
    """
    direct = [
        min(v1, v3),
        min(v2, v4),
        max(v1, v3),
        max(v2, v4),
    ]
    ymin_xmin = tag_to_xyxy_grid(v1, v2, v3, v4)
    out: list[tuple[list[int], float]] = []
    seen: set[tuple[int, int, int, int]] = set()

    def add(c: list[int], bonus: float) -> None:
        key = tuple(c)
        if key in seen:
            return
        seen.add(key)
        out.append((c, bonus))

    # Qwen thực tế hay dùng (xmin,ymin),(xmax,ymax) — ưu tiên hơn schema prompt
    add(direct, 3.0)
    add(ymin_xmin, 1.0)
    add([v2, v1, v4, v3], 0.0)
    return out


def grid_to_pixel_xyxy(
    grid: list[int],
    img_w: int,
    img_h: int,
    *,
    pad_px: int = 1,
) -> list[int] | None:
    """Grid [xmin,ymin,xmax,ymax] → pixel [x1,y1,x2,y2] trên ảnh analysis frame."""
    if img_w <= 0 or img_h <= 0:
        return None
    if not is_qwen_grid_1000(grid, for_model=True) and not is_qwen_grid_1000(grid, img_w=img_w, img_h=img_h):
        return None
    x1 = int(min(grid[0], grid[2]) * img_w / QWEN_GRID_MAX)
    y1 = int(min(grid[1], grid[3]) * img_h / QWEN_GRID_MAX)
    x2 = int(max(grid[0], grid[2]) * img_w / QWEN_GRID_MAX)
    y2 = int(max(grid[1], grid[3]) * img_h / QWEN_GRID_MAX)
    return clamp_pixel_xyxy(x1, y1, x2, y2, img_w, img_h, pad_px=pad_px)


def clamp_pixel_xyxy(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    img_w: int,
    img_h: int,
    *,
    pad_px: int = 1,
) -> list[int] | None:
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    if pad_px > 0 and img_w > 2 and img_h > 2:
        x1 = max(0, x1 - pad_px)
        y1 = max(0, y1 - pad_px)
        x2 = min(img_w, x2 + pad_px)
        y2 = min(img_h, y2 + pad_px)
    x1 = max(0, min(x1, img_w))
    y1 = max(0, min(y1, img_h))
    x2 = max(0, min(x2, img_w))
    y2 = max(0, min(y2, img_h))
    if (x2 - x1) < 5 or (y2 - y1) < 5:
        return None
    return [x1, y1, x2, y2]


def _score_pixel_box(box: list[int] | None, img_w: int, img_h: int) -> float:
    if not box:
        return -1.0
    w, h = box[2] - box[0], box[3] - box[1]
    if w < 5 or h < 5:
        return -1.0
    img_area = img_w * img_h
    ratio = (w * h) / max(img_area, 1)
    if ratio > 0.92 or ratio < 0.00005:
        return -1.0
    aspect = w / max(h, 1)
    aspect_score = 2.0 if 0.15 <= aspect <= 8.0 else 0.0
    return min(ratio * 500, 8.0) + aspect_score


def resolve_best_box_grid(
    err: dict[str, Any],
    combined_text: str,
    img_w: int,
    img_h: int,
) -> list[int] | None:
    """
    Chọn [xmin,ymin,xmax,ymax] grid 0–1000.
    Ưu tiên JSON c (schema prompt); tag chỉ khi không có c hợp lệ.
    """
    candidates: list[list[int]] = []
    c_raw = None
    tag_bonuses: dict[tuple[int, int, int, int], float] = {}
    raw_box = err.get("c") or err.get("box_2d")
    if raw_box and isinstance(raw_box, list) and len(raw_box) == 4:
        try:
            c_raw = [int(v) for v in raw_box]
            if is_qwen_grid_1000(c_raw, img_w=img_w, img_h=img_h, for_model=True):
                candidates.append(c_raw)
                candidates.append([c_raw[1], c_raw[0], c_raw[3], c_raw[2]])
        except (TypeError, ValueError):
            c_raw = None

    for m in BOX_TAG_RE.finditer(combined_text or ""):
        v1, v2, v3, v4 = (int(m.group(i)) for i in range(1, 5))
        for coords, bonus in box_tag_grid_candidates(v1, v2, v3, v4):
            key = tuple(coords)
            if key not in tag_bonuses:
                candidates.append(coords)
            tag_bonuses[key] = max(tag_bonuses.get(key, 0.0), bonus)

    best: list[int] | None = None
    best_score = -1.0
    for cand in candidates:
        if not is_qwen_grid_1000(cand, img_w=img_w, img_h=img_h, for_model=True):
            continue
        pixel = grid_to_pixel_xyxy(cand, img_w, img_h, pad_px=0)
        score = _score_pixel_box(pixel, img_w, img_h)
        if c_raw is not None and cand == c_raw:
            score += 5.0
        score += tag_bonuses.get(tuple(cand), 0.0)
        if score > best_score:
            best_score = score
            best = cand
    return best


def resolve_best_box_pixel(
    err: dict[str, Any],
    combined_text: str,
    img_w: int,
    img_h: int,
) -> list[int] | None:
    """Chọn pixel box tốt nhất từ JSON c hoặc tag grid."""
    scored: list[tuple[list[int], float]] = []
    raw_box = err.get("c") or err.get("box_2d")
    if raw_box and isinstance(raw_box, list) and len(raw_box) == 4:
        try:
            c = [int(v) for v in raw_box]
            for cand in (c, [c[1], c[0], c[3], c[2]]):
                pixel = clamp_pixel_xyxy(cand[0], cand[1], cand[2], cand[3], img_w, img_h, pad_px=0)
                if pixel:
                    scored.append((pixel, 5.0 if cand == c else 0.0))
        except (TypeError, ValueError):
            pass

    grid = resolve_best_box_grid(err, combined_text, img_w, img_h)
    if grid:
        pixel = grid_to_pixel_xyxy(grid, img_w, img_h)
        if pixel:
            scored.append((pixel, 2.0))

    for m in BOX_TAG_RE.finditer(combined_text or ""):
        v1, v2, v3, v4 = (int(m.group(i)) for i in range(1, 5))
        for coords, bonus in box_tag_grid_candidates(v1, v2, v3, v4):
            pixel = grid_to_pixel_xyxy(coords, img_w, img_h, pad_px=0)
            if pixel:
                scored.append((pixel, bonus))

    best = None
    best_score = -1.0
    for pixel, bonus in scored:
        score = _score_pixel_box(pixel, img_w, img_h) + bonus
        if score > best_score:
            best_score = score
            best = pixel
    return best


def strip_box_tags(text: str) -> str:
    if not text:
        return ""
    return BOX_TAG_RE.sub("", text).replace("  ", " ").strip()


def scale_pixel_to_source(
    box: list[int],
    frame_w: int,
    frame_h: int,
    source_w: int,
    source_h: int,
) -> list[int]:
    if frame_w <= 0 or frame_h <= 0 or source_w <= 0 or source_h <= 0:
        return box
    if frame_w == source_w and frame_h == source_h:
        return box
    sx = source_w / frame_w
    sy = source_h / frame_h
    return [
        int(round(box[0] * sx)),
        int(round(box[1] * sy)),
        int(round(box[2] * sx)),
        int(round(box[3] * sy)),
    ]


def scale_pixel_box_to_image(
    box: list[int] | tuple[int, ...],
    ref_w: int,
    ref_h: int,
    img_w: int,
    img_h: int,
) -> list[int] | None:
    """Scale pixel box từ hệ isz (ref) sang kích thước bytes ảnh thực (img)."""
    if not box or len(box) < 4 or img_w <= 0 or img_h <= 0:
        return None
    try:
        b = [int(float(v)) for v in box[:4]]
    except (TypeError, ValueError):
        return None
    rw = ref_w if ref_w > 0 else img_w
    rh = ref_h if ref_h > 0 else img_h
    if rw != img_w or rh != img_h:
        b = scale_pixel_to_source(b, rw, rh, img_w, img_h)
    return clamp_pixel_xyxy(b[0], b[1], b[2], b[3], img_w, img_h)


def copy_errors_raw(errors: list) -> list:
    return copy.deepcopy(errors) if isinstance(errors, list) else []
