"""
Post-Processing Agent – validate và chuẩn hóa JSON output từ Qwen.
Bounding box: docs/BOUNDING_BOX_COORDINATES.md + backend/box_coordinates.py
"""
import copy
import re
from PIL import Image
import io
from .color_analyzer import analyze_box_contrast
from box_coordinates import (
    COORD_FRAME_PIXEL,
    BOX_TAG_RE,
    _score_pixel_box,
    box_tag_grid_candidates,
    copy_errors_raw,
    grid_to_pixel_xyxy,
    resolve_best_box_grid,
    resolve_best_box_pixel,
    strip_box_tags,
)

VALID_SEVERITIES = {"minor", "major", "critical"}
VALID_CATEGORIES = {
    "color_theory", "typography", "layout_rules",
    "logo_design", "poster_design",
    "icon_design", "pattern_design",
    "general",
}


class PostProcessAgent:
    def process(
        self,
        raw_result: dict,
        image_bytes: bytes,
    ) -> dict:
        errors = raw_result.get("e")
        if errors is None:
            errors = raw_result.get("errors")
        if errors is None or not isinstance(errors, list):
            raise ValueError("Response JSON thiếu trường 'e' hoặc 'errors'")

        img = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = img.size

        pending: list[tuple[dict, dict]] = []

        for err in errors:
            if not isinstance(err, dict):
                continue
            issue = str(err.get("issue") or "").strip()
            suggestion = str(err.get("suggestion") or "").strip()
            reason = str(err.get("r") or err.get("reason") or "").strip()
            combined_text = f"{reason} {issue} {suggestion}"

            if not reason and (issue or suggestion):
                reason = f"{issue} {suggestion}".strip()

            grid = resolve_best_box_grid(err, combined_text, img_w, img_h)
            pixel = resolve_best_box_pixel(err, combined_text, img_w, img_h)
            if pixel is None and grid is not None:
                pixel = grid_to_pixel_xyxy(grid, img_w, img_h)
            if pixel is None:
                for m in BOX_TAG_RE.finditer(combined_text or ""):
                    try:
                        v1, v2, v3, v4 = (int(m.group(i)) for i in range(1, 5))
                        best_tag_pixel = None
                        best_tag_score = -1.0
                        best_tag_grid = None
                        for coords, bonus in box_tag_grid_candidates(v1, v2, v3, v4):
                            px = grid_to_pixel_xyxy(coords, img_w, img_h, pad_px=0)
                            if px is None:
                                continue
                            score = _score_pixel_box(px, img_w, img_h) + bonus
                            if score > best_tag_score:
                                best_tag_score = score
                                best_tag_pixel = px
                                best_tag_grid = coords
                        if best_tag_pixel is not None:
                            pixel = best_tag_pixel
                            grid = best_tag_grid
                            break
                    except (TypeError, ValueError):
                        continue

            new_reason = strip_box_tags(reason)
            new_reason = re.sub(r'(?i)\bRules?\s+\d+([-&,]\d+)?\s*[:\-—]+\s*', '', new_reason)
            new_reason = re.sub(r'(?i)\bRules?\s+\d+([-&,]\d+)?\b', '', new_reason)
            new_reason = re.sub(r'\(\s*\)', '', new_reason)
            new_reason = re.sub(r'\s+', ' ', new_reason).strip()

            if not new_reason and not issue and not suggestion:
                continue

            severity = str(err.get("s") or err.get("severity") or "minor").lower().strip()
            if severity not in VALID_SEVERITIES:
                severity = "minor"

            category = str(err.get("g") or err.get("category") or "general").lower().strip()
            if category not in VALID_CATEGORIES:
                category = "general"

            rule_violated = str(err.get("rule_violated") or err.get("violated_rule") or "").strip()
            if not rule_violated:
                rule_violated = f"[{category.replace('_', ' ').title()}] Standard Design Principle"

            if pixel is None:
                print(f"[DEBUG] No box for error (keeping text-only): {issue[:60] if issue else reason[:60]}")
                pending.append(({
                    "r": new_reason or issue or suggestion,
                    "issue": strip_box_tags(issue),
                    "suggestion": strip_box_tags(suggestion),
                    "s": severity,
                    "g": category,
                    "rule_violated": rule_violated,
                }, copy.deepcopy(err)))
                continue

            x1, y1, x2, y2 = pixel

            new_severity = severity
            if category in ["typography", "color_theory"]:
                wcag_result = analyze_box_contrast(image_bytes, [x1, y1, x2, y2])
                ratio = wcag_result.get("ratio")
                if ratio is not None and not wcag_result.get("pass"):
                    new_reason = (
                        f"{new_reason} [WCAG ERROR: Contrast ratio is only {ratio}:1, "
                        f"below the 4.5:1 standard. Increase the light/dark contrast between text and background.]"
                    )
                    new_severity = "critical" if ratio < 3.0 else "major"

            entry = {
                "c": [x1, y1, x2, y2],
                "r": new_reason,
                "issue": strip_box_tags(issue),
                "suggestion": strip_box_tags(suggestion),
                "s": new_severity,
                "g": category,
                "rule_violated": rule_violated,
            }
            if grid is not None:
                entry["c_grid"] = grid
            pending.append((entry, copy.deepcopy(err)))

        severity_priority = {"critical": 0, "major": 1, "minor": 2}
        pending.sort(key=lambda pair: severity_priority.get(pair[0]["s"], 3))
        pending = pending[:5]
        cleaned = [pair[0] for pair in pending]
        e_raw = [pair[1] for pair in pending]

        severity_summary = {"minor": 0, "major": 0, "critical": 0}
        for item in cleaned:
            severity_summary[item["s"]] += 1

        usage_data = raw_result.get("_usage", {}) if isinstance(raw_result, dict) else {}
        return {
            "compliments": raw_result.get("compliments", []),
            "e": cleaned,
            "e_raw": e_raw,
            "isz": {"w": img_w, "h": img_h},
            "coord_space": COORD_FRAME_PIXEL,
            "te": len(cleaned),
            "ss": severity_summary,
            "inputtoken": usage_data.get("input_tokens", 0),
            "outputtoken": usage_data.get("output_tokens", 0),
            "totaltoken": usage_data.get("total_tokens", 0),
        }
