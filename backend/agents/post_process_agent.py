"""
Post-Processing Agent – validate và chuẩn hóa JSON output từ Qwen.
Improvements:
  - Validates and defaults new 'severity' field (minor/major/critical)
  - Validates and defaults new 'category' field
  - Returns severity_summary breakdown in final dict
"""
import re
from PIL import Image
import io
from .color_analyzer import analyze_box_contrast

VALID_SEVERITIES = {"minor", "major", "critical"}
VALID_CATEGORIES = {
    "color_theory", "typography", "layout_rules",
    "logo_design", "poster_design",
    "icon_design", "pattern_design",
    "general",
}


class PostProcessAgent:
    @staticmethod
    def _parse_and_orient_box(v1: int, v2: int, v3: int, v4: int, text: str, is_from_json: bool = False) -> list:
        """
        Smart coordinate parser. Resolves whether coordinates are [ymin, xmin, ymax, xmax] or [xmin, ymin, xmax, ymax]
        based on text cues (like 'vertical' or 'horizontal') and aspect ratios.
        """
        # Both native Qwen <box> and JSON "c" in this project are consistently output in [xmin, ymin, xmax, ymax] order.
        box = [v1, v2, v3, v4]
            
        text_lower = text.lower()
        is_vertical_text = "vertical" in text_lower or "dọc" in text_lower
        is_horizontal_text = "horizontal" in text_lower or "ngang" in text_lower
        
        x1, y1, x2, y2 = box
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        
        # If the text explicitly says "vertical" but our box is horizontal (width > height * 1.2),
        # it means the coordinates were likely swapped! Let's correct it by swapping X and Y.
        if is_vertical_text and width > height * 1.2:
            print(f"[DEBUG] Smart Swapping: Text describes vertical element but box is horizontal. Swapping axes.")
            box = [y1, x1, y2, x2]
        # If the text explicitly says "horizontal" but our box is vertical (height > width * 1.2),
        # we swap them too.
        elif is_horizontal_text and height > width * 1.2:
            print(f"[DEBUG] Smart Swapping: Text describes horizontal element but box is vertical. Swapping axes.")
            box = [y1, x1, y2, x2]
            
        # Standardize so xmin < xmax and ymin < ymax
        rx1, ry1, rx2, ry2 = box
        return [min(rx1, rx2), min(ry1, ry2), max(rx1, rx2), max(ry1, ry2)]

    def process(
        self,
        raw_result: dict,
        image_bytes: bytes,
    ) -> dict:
        """
        Validate và clean Qwen output:
        1. Kiểm tra JSON structure hợp lệ
        2. Clamp bounding boxes trong giới hạn ảnh
        3. Loại bỏ duplicate bounding boxes
        4. Lọc bỏ errors có boxes quá nhỏ
        5. Validate severity + category fields (new)
        6. Build severity_summary (new)
        7. Clean 'Rule X' mentions from reasons (User request)
        """
        # --- 1. Validate structure (hỗ trợ cả schema cũ và mới) ---
        errors = raw_result.get("e")
        if errors is None:
            errors = raw_result.get("errors")
        if errors is None or not isinstance(errors, list):
            raise ValueError("Response JSON thiếu trường 'e' hoặc 'errors'")

        # --- 2. Lấy kích thước ảnh ---
        img = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = img.size

        # --- 3. Process từng error ---
        cleaned   = []
        seen_boxes = set()

        for err in errors:
            print(f"[DEBUG] Processing err: {err}")
            if not isinstance(err, dict):
                print(f"[DEBUG] Skipped: not a dict")
                continue
            issue = str(err.get("issue") or "").strip()
            suggestion = str(err.get("suggestion") or "").strip()
            reason = str(err.get("r") or err.get("reason") or "").strip()
            
            # Prioritize extracting box from native inline <box> tags in the text,
            # using a flexible regex to support any variations of spaces.
            box = None
            combined_text = f"{reason} {issue} {suggestion}"
            match = re.search(r'<box>\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*</box>', combined_text)
            if match:
                v1, v2, v3, v4 = map(int, match.groups())
                box = self._parse_and_orient_box(v1, v2, v3, v4, combined_text, is_from_json=False)
                print(f"[DEBUG] Extracted and corrected native inline box: {box}")
            
            if box is None:
                raw_box = err.get("c") or err.get("box_2d")
                if raw_box and isinstance(raw_box, list) and len(raw_box) == 4:
                    try:
                        v1, v2, v3, v4 = map(int, raw_box)
                        box = self._parse_and_orient_box(v1, v2, v3, v4, combined_text, is_from_json=True)
                        print(f"[DEBUG] Parsed and oriented raw JSON box coordinates: {box}")
                    except (ValueError, TypeError):
                        pass

            if not reason and (issue or suggestion):
                reason = f"{issue} {suggestion}".strip()
                
            if box is None or not reason:
                print(f"[DEBUG] Skipped: no box or no reason (box={box}, reason={reason})")
                continue
            if not (isinstance(box, list) and len(box) == 4):
                print(f"[DEBUG] Skipped: invalid box {box}")
                continue

            # Convert to int
            try:
                xmin_norm, ymin_norm, xmax_norm, ymax_norm = [int(v) for v in box]
            except (ValueError, TypeError):
                print(f"[DEBUG] Skipped: coords are not ints")
                continue

            # Qwen-VL outputs [xmin, ymin, xmax, ymax] in normalized 0-1000 format
            needs_normalization = all(v <= 1000 for v in [xmin_norm, ymin_norm, xmax_norm, ymax_norm])
            
            if needs_normalization:
                x1 = int(xmin_norm / 1000 * img_w)
                y1 = int(ymin_norm / 1000 * img_h)
                x2 = int(xmax_norm / 1000 * img_w)
                y2 = int(ymax_norm / 1000 * img_h)
            else:
                # Fallback if it somehow output absolute pixels
                x1, y1, x2, y2 = xmin_norm, ymin_norm, xmax_norm, ymax_norm

            # Clamp vào image bounds
            x1 = max(0, min(x1, img_w))
            y1 = max(0, min(y1, img_h))
            x2 = max(0, min(x2, img_w))
            y2 = max(0, min(y2, img_h))

            # Đảm bảo x1<x2, y1<y2
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)

            # Bỏ qua boxes quá nhỏ (< 5×5 px)
            if (x2 - x1) < 5 or (y2 - y1) < 5:
                print(f"[DEBUG] Skipped: box too small: w={x2-x1}, h={y2-y1} from original {box} and normalized {xmin_norm, ymin_norm, xmax_norm, ymax_norm} on img size {img_w}x{img_h}")
                continue

            # Deduplication
            box_key = (x1 // 10, y1 // 10, x2 // 10, y2 // 10)
            if box_key in seen_boxes:
                print(f"[DEBUG] Skipped: deduplicated box {box_key}")
                continue
            seen_boxes.add(box_key)

            print(f"[DEBUG] Added to cleaned! new box: {x1, y1, x2, y2}")

            # --- Validate severity ---
            severity = str(err.get("s") or err.get("severity") or "minor").lower().strip()
            if severity not in VALID_SEVERITIES:
                severity = "minor"

            # --- Validate category ---
            category = str(err.get("g") or err.get("category") or "general").lower().strip()
            if category not in VALID_CATEGORIES:
                category = "general"

            # --- Validate rule_violated (Developer attribution, hidden) ---
            rule_violated = str(err.get("rule_violated") or err.get("violated_rule") or "").strip()
            if not rule_violated:
                rule_violated = f"[{category.replace('_', ' ').title()}] Standard Design Principle"
                
            # --- Vision-based Color Analysis (WCAG) ---
            new_reason = str(reason).strip()
            
            # --- USER REQUEST: Clean 'Rule X' mentions ---
            # Remove patterns like "Rule 7", "Rule 123", "Rules 1-2", "(Rule 7)" etc.
            
            # 1. Remove "Rule X" + optional separator following it (e.g., "Rule 7 — ", "Rule 7: ")
            new_reason = re.sub(r'(?i)\bRules?\s+\d+([-&,]\d+)?\s*[:\-—]+\s*', '', new_reason)
            
            # 2. Remove "Rule X" without separator (e.g., "violating Rule 7", "(Rule 7)")
            new_reason = re.sub(r'(?i)\bRules?\s+\d+([-&,]\d+)?\b', '', new_reason)
            
            # 3. Clean up empty parentheses "( )"
            new_reason = re.sub(r'\(\s*\)', '', new_reason)
            
            # 4. Clean up multiple spaces and strip
            new_reason = re.sub(r'\s+', ' ', new_reason).strip()

            new_severity = severity
            if category in ["typography", "color_theory"]:
                wcag_result = analyze_box_contrast(image_bytes, [x1, y1, x2, y2])
                ratio = wcag_result.get("ratio")
                if ratio is not None and not wcag_result.get("pass"):
                    new_reason = f"{new_reason} [WCAG ERROR: Contrast ratio is only {ratio}:1, below the 4.5:1 standard. Increase the light/dark contrast between text and background.]"
                    new_severity = "critical" if ratio < 3.0 else "major"

            cleaned.append({
                "c"  : [x1, y1, x2, y2],
                "r"  : new_reason,
                "issue": issue,
                "suggestion": suggestion,
                "s": new_severity,
                "g": category,
                "rule_violated": rule_violated,
            })

        # --- 4. Implementing Quick-Fix Priority Flow ---
        # Sort by severity (critical > major > minor) to prioritize critical errors
        severity_priority = {"critical": 0, "major": 1, "minor": 2}
        cleaned.sort(key=lambda x: severity_priority.get(x["s"], 3))
        
        # Limit the number of errors and form a sequential list of repair steps
        # This prevents overwhelming the user with too many minor errors
        MAX_STEPS = 5
        cleaned = cleaned[:MAX_STEPS]

        # --- 5. Build severity summary ---
        severity_summary = {"minor": 0, "major": 0, "critical": 0}
        for item in cleaned:
            severity_summary[item["s"]] += 1

        usage_data = raw_result.get("_usage", {}) if isinstance(raw_result, dict) else {}
        return {
            "compliments": raw_result.get("compliments", []),
            "e"  : cleaned,
            "isz": {"w": img_w, "h": img_h},
            "te" : len(cleaned),
            "ss" : severity_summary,
            "inputtoken": usage_data.get("input_tokens", 0),
            "outputtoken": usage_data.get("output_tokens", 0),
            "totaltoken": usage_data.get("total_tokens", 0)
        }
