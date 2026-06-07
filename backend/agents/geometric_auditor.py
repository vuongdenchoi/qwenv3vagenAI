from __future__ import annotations
import numpy as np
from PIL import Image
import io

def to_linear_rgb(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    else:
        return ((c + 0.055) / 1.055) ** 2.4

def calculate_luminance(rgb: tuple[int, int, int]) -> float:
    r = to_linear_rgb(rgb[0] / 255.0)
    g = to_linear_rgb(rgb[1] / 255.0)
    b = to_linear_rgb(rgb[2] / 255.0)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    l1 = calculate_luminance(rgb1)
    l2 = calculate_luminance(rgb2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def is_structural_element(label: str) -> bool:
    lbl = label.lower().strip()
    if lbl in ["button", "input field", "card", "text", "logo", "icon"]:
        return True
    if lbl.startswith("text:") or lbl.startswith("button:") or lbl.startswith("input:") or lbl.startswith("card:") or lbl.startswith("logo:") or lbl.startswith("icon:"):
        return True
    return False

class GeometricAuditor:
    def __init__(self):
        pass

    def run_contrast_check(self, image: Image.Image, box_px: list[int]) -> dict:
        """
        Runs the Edge-Guided Seeding & Weighted Median contrast audit.
        box_px format: [x1, y1, x2, y2] in pixels.
        """
        try:
            x1, y1, x2, y2 = box_px
            crop = image.crop((x1, y1, x2, y2)).convert("RGB")
            img_np = np.array(crop)
            h, w, c = img_np.shape
            if h < 4 or w < 4:
                return {"success": False, "ratio": 1.0, "reason": "Crop too small"}

            # Grayscale for gradients
            gray = 0.299 * img_np[:, :, 0] + 0.587 * img_np[:, :, 1] + 0.114 * img_np[:, :, 2]
            
            # Simple gradients (anti-aliasing boundary detector)
            grad_x = np.zeros_like(gray)
            grad_y = np.zeros_like(gray)
            grad_x[1:-1, 1:-1] = (gray[1:-1, 2:] - gray[1:-1, :-2]) / 2.0
            grad_y[1:-1, 1:-1] = (gray[2:, 1:-1] - gray[:-2, 1:-1]) / 2.0
            grad_mag = np.sqrt(grad_x**2 + grad_y**2)
            
            # Mask out the edge pixels (top 35% gradients are likely boundary text edges)
            edge_threshold = np.percentile(grad_mag, 65)
            edge_mask = grad_mag > max(edge_threshold, 5.0)
            
            # BG seeds: 4 corners (10% of width/height at corners)
            bg_seeds = np.zeros_like(gray, dtype=bool)
            cw, ch = max(1, int(w * 0.15)), max(1, int(h * 0.15))
            bg_seeds[:ch, :cw] = True
            bg_seeds[:ch, -cw:] = True
            bg_seeds[-ch:, :cw] = True
            bg_seeds[-ch:, -cw:] = True
            
            # FG seeds: center (center 50%)
            fg_seeds = np.zeros_like(gray, dtype=bool)
            fx1, fx2 = int(w * 0.25), int(w * 0.75)
            fy1, fy2 = int(h * 0.25), int(h * 0.75)
            fg_seeds[fy1:fy2, fx1:fx2] = True
            
            # Exclude edges
            bg_seeds = bg_seeds & ~edge_mask
            fg_seeds = fg_seeds & ~edge_mask
            
            # Calculate BG color
            bg_pixels = img_np[bg_seeds]
            if len(bg_pixels) > 0:
                bg_color = tuple(np.median(bg_pixels, axis=0).astype(int))
            else:
                corner_pixs = [img_np[0, 0], img_np[0, -1], img_np[-1, 0], img_np[-1, -1]]
                bg_color = tuple(np.mean(corner_pixs, axis=0).astype(int))
                
            # Calculate FG color (text)
            fg_candidate_pixels = img_np[fg_seeds]
            if len(fg_candidate_pixels) > 0:
                bg_lum = calculate_luminance(bg_color)
                lums = np.array([calculate_luminance(p) for p in fg_candidate_pixels])
                diffs = np.abs(lums - bg_lum)
                
                # Pick top 50% contrasting pixels
                cutoff = np.percentile(diffs, 50)
                fg_selected = fg_candidate_pixels[diffs >= cutoff]
                
                if len(fg_selected) > 0:
                    fg_color = tuple(np.median(fg_selected, axis=0).astype(int))
                else:
                    fg_color = tuple(np.median(fg_candidate_pixels, axis=0).astype(int))
            else:
                fg_color = tuple(img_np[h//2, w//2].astype(int))
                
            ratio = contrast_ratio(fg_color, bg_color)
            return {
                "success": True,
                "ratio": ratio,
                "fg_color": fg_color,
                "bg_color": bg_color,
                "passed": ratio >= 4.5
            }
        except Exception as e:
            return {"success": False, "ratio": 1.0, "reason": str(e)}

    def audit(self, image_bytes: bytes, elements: list[dict]) -> list[dict]:
        """
        Performs full geometric audit: contrast, alignment, and spacing.
        Returns a list of error dicts.
        """
        errors = []
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_w, img_h = image.size
        except Exception as e:
            print(f"[GeometricAuditor] Failed to load image: {e}")
            return []

        # Convert 0-1000 grid boxes to pixel coordinates for image processing
        elements_px = []
        for idx, el in enumerate(elements):
            box = el["box_2d"]
            x1 = int(box[0] / 1000.0 * img_w)
            y1 = int(box[1] / 1000.0 * img_h)
            x2 = int(box[2] / 1000.0 * img_w)
            y2 = int(box[3] / 1000.0 * img_h)
            
            # Ensure dimensions are valid
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            
            elements_px.append({
                "index": idx,
                "label": el["label"],
                "box_px": [x1, y1, x2, y2],
                "box_grid": box,
                "cx": (x1 + x2) // 2,
                "cy": (y1 + y2) // 2,
                "w": x2 - x1,
                "h": y2 - y1
            })

        # --- 1. Contrast Check for Typography ---
        for el in elements_px:
            label = el["label"].lower()
            if "text" in label or label.startswith("text:"):
                res = self.run_contrast_check(image, el["box_px"])
                if res.get("success") and not res.get("passed"):
                    ratio = res["ratio"]
                    fg = res["fg_color"]
                    bg = res["bg_color"]
                    severity = "critical" if ratio < 3.0 else "major"
                    errors.append({
                        "box_2d": el["box_grid"],
                        "issue": f"Độ tương phản chữ kém (WCAG Contrast). Tỷ lệ tương phản hiện tại là {ratio:.2f}:1, không đạt mức tối thiểu 4.5:1.",
                        "suggestion": f"Hãy thay đổi màu chữ hoặc màu nền xung quanh. Màu chữ trích xuất: rgb{fg}, màu nền trích xuất: rgb{bg}.",
                        "severity": severity,
                        "category": "color_theory"
                    })

        # --- 2. Spacing Check (8pt grid) ---
        for el in elements_px:
            if is_structural_element(el["label"]):
                w_rem = el["w"] % 8
                h_rem = el["h"] % 8
                # If width or height is not divisible by 4 (more relaxed) or 8
                if w_rem != 0 and el["w"] % 4 != 0:
                    errors.append({
                        "box_2d": el["box_grid"],
                        "issue": f"Chiều rộng phần tử ({el['w']}px) không tuân thủ hệ lưới 8pt grid.",
                        "suggestion": f"Hãy căn chỉnh chiều rộng thành {el['w'] - w_rem}px hoặc {el['w'] + (8 - w_rem)}px.",
                        "severity": "minor",
                        "category": "layout_rules"
                    })
                if h_rem != 0 and el["h"] % 4 != 0:
                    errors.append({
                        "box_2d": el["box_grid"],
                        "issue": f"Chiều cao phần tử ({el['h']}px) không tuân thủ hệ lưới 8pt grid.",
                        "suggestion": f"Hãy căn chỉnh chiều cao thành {el['h'] - h_rem}px hoặc {el['h'] + (8 - h_rem)}px.",
                        "severity": "minor",
                        "category": "layout_rules"
                    })

        # --- 3. Alignment Check ---
        # Compare every pair of elements to find slight misalignments
        for i in range(len(elements_px)):
            for j in range(i + 1, len(elements_px)):
                el_a = elements_px[i]
                el_b = elements_px[j]
                
                # Exclude organic elements, only check alignments between UI structural components
                if not is_structural_element(el_a["label"]) or not is_structural_element(el_b["label"]):
                    continue
                
                # We check alignment only if they are relatively close (distance < 150px)
                dist_x = min(abs(el_a["box_px"][2] - el_b["box_px"][0]), abs(el_b["box_px"][2] - el_a["box_px"][0]))
                dist_y = min(abs(el_a["box_px"][3] - el_b["box_px"][1]), abs(el_b["box_px"][3] - el_a["box_px"][1]))
                
                if dist_x < 150 or dist_y < 150:
                    # Check left alignment
                    diff_left = abs(el_a["box_px"][0] - el_b["box_px"][0])
                    # Relaxed tolerance: ignore shifts <= 3px, only flag shifts between 3px and 12px
                    if 3 < diff_left <= 12:
                        errors.append({
                            "box_2d": el_a["box_grid"],
                            "issue": f"Lệch gióng hàng lề trái giữa hai phần tử kề nhau ({el_a['label']} và {el_b['label']}). Lệch {diff_left}px.",
                            "suggestion": f"Căn lề trái của cả hai phần tử về cùng tọa độ x={min(el_a['box_px'][0], el_b['box_px'][0])}px.",
                            "severity": "major",
                            "category": "layout_rules"
                        })
                    
                    # Check center vertical alignment
                    diff_cx = abs(el_a["cx"] - el_b["cx"])
                    if 3 < diff_cx <= 12:
                        # Only check if left boundary is not aligned (to avoid double reports)
                        if diff_left > 12:
                            errors.append({
                                "box_2d": el_a["box_grid"],
                                "issue": f"Lệch gióng hàng căn giữa dọc (Vertical Center) giữa {el_a['label']} và {el_b['label']}. Lệch {diff_cx}px.",
                                "suggestion": f"Hãy gióng thẳng tâm dọc của cả hai phần tử.",
                                "severity": "major",
                                "category": "layout_rules"
                            })

                    # Check top alignment
                    diff_top = abs(el_a["box_px"][1] - el_b["box_px"][1])
                    if 3 < diff_top <= 12:
                        errors.append({
                            "box_2d": el_a["box_grid"],
                            "issue": f"Lệch gióng hàng lề trên (Top Alignment) giữa {el_a['label']} và {el_b['label']}. Lệch {diff_top}px.",
                            "suggestion": f"Căn lề trên của cả hai về cùng tọa độ y={min(el_a['box_px'][1], el_b['box_px'][1])}px.",
                            "severity": "major",
                            "category": "layout_rules"
                        })

        return errors
