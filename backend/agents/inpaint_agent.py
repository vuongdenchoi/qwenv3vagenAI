"""
InpaintAgent - Gọi WillaAI Image Edits (x.ai) API để redesign/fix lỗi thiết kế.

API dùng:
  POST https://api.x.ai/v1/images/edits
  Input: JSON body với model, prompt, và image_url
  Output: synchronous - result trong data[0].url

Image hosting: Upload ảnh lên ImgBB trước, URL của ImgBB được WillaAI API chấp nhận.
"""

import os
import io
import time
import base64
import requests
from typing import List, Optional, Tuple
from pathlib import Path
from PIL import Image, ImageDraw

TEMP_DIR = Path(__file__).parent.parent / "static_temp"
TEMP_DIR.mkdir(exist_ok=True)

WILLAAI_API_URL  = "https://api.x.ai/v1/images/edits"
IMGBB_UPLOAD = "https://api.imgbb.com/1/upload"


class InpaintAgent:
    """
    - Gọi WillaAI (x.ai) với model grok-imagine-image
    """

    def __init__(self, api_key: str, public_base_url: str = "", imgbb_api_key: str = ""):
        self.api_key        = api_key
        self.public_base_url = public_base_url.rstrip("/")
        self.imgbb_api_key  = imgbb_api_key

    # ------------------------------------------------------------------
    # 1a. Luu anh goc xuong disk (luon hoat dong, khong can mang)
    # ------------------------------------------------------------------
    def save_local_image(
        self,
        image_bytes: bytes,
        session_id: str,
    ) -> str:
        """
        Chi luu anh xuong local disk, dam bao du kich thuoc cho Wan API.
        Tra ve local_path.
        """
        filename   = f"original_{session_id}.jpg"
        local_path = TEMP_DIR / filename

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Dam bao anh du lon (WillaAI API co the co yeu cau tuong tu Wan)
        w, h = img.size
        min_px = 768
        if w < min_px or h < min_px:
            scale = max(min_px / w, min_px / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        img.save(str(local_path), format="JPEG", quality=90)
        print(f"[InpaintAgent] Anh goc da luu: {local_path}")
        return str(local_path)

    # ------------------------------------------------------------------
    # 1b. Upload anh len ImgBB de lay public URL (can khi goi WillaAI API)
    # ------------------------------------------------------------------
    def upload_to_imgbb(self, local_path: str) -> str:
        """
        Upload file anh len ImgBB, tra ve public URL.
        Raise RuntimeError neu that bai.
        """
        if not self.imgbb_api_key:
            raise RuntimeError(
                "IMGBB_API_KEY chua duoc set. "
                "WillaAI API can mot public URL de tai anh, "
                "vui long set bien moi truong IMGBB_API_KEY."
            )

        # Doc anh tu disk
        with open(local_path, "rb") as f:
            original_bytes = f.read()

        img = Image.open(io.BytesIO(original_bytes)).convert("RGB")

        # Compress dan dan neu qua lon (ImgBB limit ~32MB)
        quality_steps = [90, 75, 60]
        max_size_bytes = 20 * 1024 * 1024  # 20MB an toan

        for quality in quality_steps:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            jpeg_bytes = buf.getvalue()
            size_mb = len(jpeg_bytes) / (1024 * 1024)
            print(f"[InpaintAgent] ImgBB upload attempt: quality={quality}, size={size_mb:.2f}MB")

            if len(jpeg_bytes) > max_size_bytes:
                print(f"[InpaintAgent] Anh qua lon ({size_mb:.1f}MB), giam quality...")
                continue

            try:
                b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
                resp = requests.post(
                    IMGBB_UPLOAD,
                    data={"key": self.imgbb_api_key, "image": b64, "expiration": 600},
                    timeout=30,
                )
                if resp.status_code == 200:
                    url = resp.json()["data"]["url"]
                    print(f"[InpaintAgent] ImgBB upload OK: {url}")
                    return url
                else:
                    print(f"[InpaintAgent] ImgBB FAIL status={resp.status_code}: {resp.text[:500]}")
                    raise RuntimeError(
                        f"ImgBB tra ve loi {resp.status_code}: {resp.text[:200]}"
                    )
            except RuntimeError:
                raise
            except Exception as e:
                print(f"[InpaintAgent] ImgBB exception: {type(e).__name__}: {e}")
                raise RuntimeError(f"ImgBB upload that bai: {e}")

        raise RuntimeError(
            f"Anh qua lon de upload len ImgBB, thu resize anh nho hon truoc khi phan tich."
        )

    # ------------------------------------------------------------------
    # 1c. Giu lai ham cu de tuong thich (goi save_local + upload_imgbb)
    # ------------------------------------------------------------------
    def prepare_original_image(
        self,
        image_bytes: bytes,
        session_id: str,
    ) -> Tuple[str, str]:
        local_path = self.save_local_image(image_bytes, session_id)
        public_url = self.upload_to_imgbb(local_path)
        return local_path, public_url

    # ------------------------------------------------------------------
    # 2. Build prompt tu danh sach loi (IMPROVED v2)
    # ------------------------------------------------------------------

    # Keyword map: extract key visual action from Vietnamese recommendation
    _CONTRAST_KEYWORDS = ["tương phản", "overlay", "bão hòa", "viền", "bóng", "làm tối", "làm sáng", "figure-ground"]
    _TYPOGRAPHY_KEYWORDS = ["chữ", "font", "tiêu đề", "văn bản", "legibility", "hinting", "stroke", "glow", "halo", "chữ viết tay", "sans-serif"]
    _LAYOUT_KEYWORDS = ["bố cục", "căn lề", "spacing", "white space", "alignment", "layout", "trật tự", "visual flow", "golden ratio"]

    def _classify_fix_type(self, reason: str, category: str) -> str:
        """Classify a fix into: contrast | typography | layout"""
        r = reason.lower()
        cat = (category or "").lower()
        if cat == "typography" or any(k in r for k in self._TYPOGRAPHY_KEYWORDS):
            return "typography"
        if cat in ("layout_rules",) or any(k in r for k in self._LAYOUT_KEYWORDS):
            return "layout"
        if any(k in r for k in self._CONTRAST_KEYWORDS):
            return "contrast"
        return "contrast"  # default to contrast fix

    def _extract_recommendation(self, reason: str) -> str:
        """
        Extract the 'Khuyến nghị' (recommendation) part from the Vietnamese reason string.
        Falls back to full reason if no split found.
        """
        import re
        # Try to split on "Khuyến nghị:" marker
        match = re.search(r"Khuyến nghị[:\s]+(.+)", reason, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        # Try to split on "Recommendation:" marker (English fallback)
        match = re.search(r"Recommendation[:\s]+(.+)", reason, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return reason

    def _build_english_fix_instruction(self, severity: str, fix_type: str, recommendation: str, coords: list) -> str:
        """
        Convert Vietnamese recommendation + metadata into a concise English fix instruction for WillaAI.
        """
        coord_str = f"[{coords[0]}, {coords[1]}, {coords[2]}, {coords[3]}]" if coords else "entire image"
        sev_label = severity.upper()

        # Build a short technical directive based on fix_type
        if fix_type == "contrast":
            base = (
                f"[{sev_label}] Region {coord_str}: "
                "Apply a subtle dark overlay (10–15% black) over the BACKGROUND in this region to increase figure-ground separation. "
                "The main subject/character must appear MORE visually prominent. "
                "Do NOT move, alter, or modify the main character or foreground elements."
            )
        elif fix_type == "typography":
            base = (
                f"[{sev_label}] Region {coord_str}: "
                "Improve text legibility in this region. Add a soft white glow or halo effect around character strokes. "
                "Alternatively, darken/blur the background directly behind the text to increase contrast. "
                "Do NOT reposition, resize, or change the font style of any text."
            )
        elif fix_type == "layout":
            base = (
                f"[{sev_label}] Region {coord_str}: "
                "Improve visual clarity and spacing in this region. Reduce visual noise by slightly desaturating secondary elements. "
                "Ensure the most important element in this area is the clearest focal point. "
                "Do NOT rearrange key design elements."
            )
        else:
            base = f"[{sev_label}] Region {coord_str}: Apply targeted visual enhancement to improve design quality."

        # Append a summarized version of the Vietnamese recommendation as a hint
        if len(recommendation) > 20:
            hint = recommendation[:200].rstrip(".") + "."
            base += f" (Design note: {hint})"

        return base

    def _build_vietnamese_fix_instruction(self, severity: str, fix_type: str, recommendation: str, coords: list) -> str:
        """
        Convert recommendation + metadata into a concise Vietnamese fix instruction for WillaAI.
        """
        coord_str = f"[{coords[0]}, {coords[1]}, {coords[2]}, {coords[3]}]" if coords else "toàn bộ ảnh"
        sev_label = severity.upper()

        if fix_type == "contrast":
            base = (
                f"[{sev_label}] Vùng {coord_str}: "
                "Thêm một lớp phủ tối nhẹ (10-15% đen) vào NỀN trong vùng này để tăng cường độ tương phản figure-ground. "
                "Chủ thể chính/nhân vật phải trở nên nổi bật hơn. "
                "KHÔNG ĐƯỢC di chuyển, thay đổi hoặc chỉnh sửa nhân vật chính hay các yếu tố tiền cảnh."
            )
        elif fix_type == "typography":
            base = (
                f"[{sev_label}] Vùng {coord_str}: "
                "Cải thiện khả năng đọc chữ trong vùng này. Thêm hiệu ứng phát sáng mờ màu trắng hoặc viền sáng xung quanh chữ. "
                "Hoặc có thể làm tối/mờ trực tiếp nền ngay phía sau chữ để tăng độ tương phản. "
                "KHÔNG ĐƯỢC thay đổi vị trí, kích thước, hay kiểu font của bất kỳ chữ nào."
            )
        elif fix_type == "layout":
            base = (
                f"[{sev_label}] Vùng {coord_str}: "
                "Cải thiện sự rõ ràng của thiết kế và khoảng cách trong vùng này. Giảm nhiễu thị giác bằng cách giảm nhẹ độ bão hòa của các yếu tố phụ. "
                "Đảm bảo yếu tố quan trọng nhất trong khu vực này là điểm nhấn rõ ràng nhất. "
                "KHÔNG ĐƯỢC sắp xếp lại các yếu tố thiết kế chính."
            )
        else:
            base = f"[{sev_label}] Vùng {coord_str}: Áp dụng tăng cường hình ảnh để cải thiện chất lượng thiết kế."

        if len(recommendation) > 20:
            hint = recommendation[:200].rstrip(".") + "."
            base += f" (Ghi chú thiết kế: {hint})"

        return base

    def build_prompt(self, errors: List[dict], error_indices: List[int], translator_cb=None, lang: str = "en") -> str:
        """
        Build a structured inpainting prompt for WillaAI (x.ai), localized based on `lang`.
        """
        selected = [errors[i] for i in error_indices if 0 <= i < len(errors)]
        if not selected:
            if lang == "vi":
                return (
                    "Nhiệm vụ: Cải thiện chất lượng hình ảnh tổng thể của thiết kế này. "
                    "Tăng độ tương phản figure-ground, cải thiện khả năng đọc chữ, và giảm nhiễu thị giác. "
                    "Giữ nguyên phong cách nghệ thuật gốc, bảng màu, và tất cả các chi tiết thiết kế."
                )
            return (
                "Task: Improve the overall visual quality of this image. "
                "Increase figure-ground contrast, improve text legibility, and reduce visual noise. "
                "Preserve the original artistic style, color palette, and all design elements."
            )

        # --- Header: Style preservation ---
        if lang == "vi":
            header = (
                "Bạn là một chuyên gia thiết kế đồ họa đang thực hiện các chỉnh sửa trực quan CỤ THỂ lên một hình ảnh thiết kế.\n\n"
                "QUY TẮC BẢO TOÀN PHONG CÁCH (BẮT BUỘC):\n"
                "- Giữ nguyên phong cách nghệ thuật gốc (minh họa, bảng màu, bố cục tổng thể).\n"
                "- KHÔNG THÊM yếu tố mới, KHÔNG DI CHUYỂN nhân vật/chữ, và KHÔNG THAY ĐỔI bố cục tổng thể.\n"
                "- CHỈ áp dụng các thay đổi trong vùng tọa độ được chỉ định.\n"
                "- Các thay đổi phải tinh tế và chuyên nghiệp — không được chỉnh sửa quá đà.\n\n"
            )
        else:
            header = (
                "You are an expert graphic designer applying TARGETED visual fixes to a design image.\n\n"
                "STYLE PRESERVATION RULES (MANDATORY):\n"
                "- Preserve the original artistic style (illustration, color palette, overall composition).\n"
                "- Do NOT add new elements, move characters/text, or change the overall layout.\n"
                "- Apply changes ONLY within the specified coordinate regions.\n"
                "- Changes must be subtle and professional — do not over-process.\n\n"
            )

        # --- Group fixes by type ---
        contrast_fixes = []
        typography_fixes = []
        layout_fixes = []

        severity_order = {"critical": 0, "major": 1, "minor": 2}

        for err in sorted(selected, key=lambda e: severity_order.get(e.get("s", "minor"), 3)):
            box      = err.get("c") or err.get("box_2d") or []
            severity = err.get("s", "minor")
            category = err.get("g", "general")

            issue = str(err.get("issue") or "").strip()
            suggestion = str(err.get("suggestion") or "").strip()
            reason = str(err.get("r") or "").strip()
            
            if suggestion:
                full_reason = f"{issue} {suggestion}"
                recommendation = suggestion
            else:
                full_reason = reason
                recommendation = self._extract_recommendation(reason)

            fix_type = self._classify_fix_type(full_reason, category)

            coords = []
            if box and len(box) == 4:
                try:
                    coords = [int(float(v)) for v in box]
                except (TypeError, ValueError):
                    coords = []

            if lang == "vi":
                coord_str = f"[{coords[0]}, {coords[1]}, {coords[2]}, {coords[3]}]" if coords else "toàn bộ ảnh"
                sev_label = severity.upper()
                if recommendation:
                    instruction = f"[{sev_label}] Vùng {coord_str}: {recommendation}"
                else:
                    instruction = self._build_vietnamese_fix_instruction(severity, fix_type, recommendation, coords)
            else:
                is_translated = False
                if translator_cb and recommendation:
                    try:
                        print(f"[InpaintAgent] Translating recommendation: {recommendation}")
                        translated_rec = translator_cb(recommendation)
                        print(f"[InpaintAgent] Translated result: {translated_rec}")
                        recommendation = translated_rec
                        is_translated = True
                    except Exception as e:
                        print(f"[InpaintAgent] Translation failed: {e}")

                if is_translated:
                    coord_str = f"[{coords[0]}, {coords[1]}, {coords[2]}, {coords[3]}]" if coords else "entire image"
                    sev_label = severity.upper()
                    instruction = f"[{sev_label}] Region {coord_str}: {recommendation}"
                else:
                    instruction = self._build_english_fix_instruction(severity, fix_type, recommendation, coords)

            if fix_type == "typography":
                typography_fixes.append(instruction)
            elif fix_type == "layout":
                layout_fixes.append(instruction)
            else:
                contrast_fixes.append(instruction)

        # --- Assemble final prompt ---
        fix_sections = []
        step = 1

        if contrast_fixes:
            fix_sections.append("=== SỬA LỖI TƯƠNG PHẢN & FIGURE-GROUND ===" if lang == "vi" else "=== CONTRAST & FIGURE-GROUND FIXES ===")
            for f in contrast_fixes:
                fix_sections.append(f"  {step}. {f}")
                step += 1

        if typography_fixes:
            fix_sections.append("\n=== SỬA LỖI KIỂU CHỮ & KHẢ NĂNG ĐỌC ===" if lang == "vi" else "\n=== TYPOGRAPHY & LEGIBILITY FIXES ===")
            for f in typography_fixes:
                fix_sections.append(f"  {step}. {f}")
                step += 1

        if layout_fixes:
            fix_sections.append("\n=== SỬA LỖI BỐ CỤC & LUỒNG THỊ GIÁC ===" if lang == "vi" else "\n=== LAYOUT & VISUAL FLOW FIXES ===")
            for f in layout_fixes:
                fix_sections.append(f"  {step}. {f}")
                step += 1

        body = "\n".join(fix_sections)

        if lang == "vi":
            footer = (
                "\n\nYÊU CẦU ĐẦU RA:\n"
                "- Trả về hình ảnh ĐÃ CHỈNH SỬA với TẤT CẢ các lỗi được liệt kê đã được xử lý.\n"
                "- Mỗi sửa lỗi phải rõ ràng nhưng tinh tế — đạt chất lượng chuyên nghiệp.\n"
                "- KHÔNG thay đổi bất cứ thứ gì bên ngoài các vùng tọa độ đã chỉ định.\n"
                "- Hình ảnh tổng thể phải duy trì tính nhất quán và thẩm mỹ."
            )
            return header + "CÁC CHỈNH SỬA CỤ THỂ (áp dụng theo thứ tự):\n" + body + footer
        else:
            footer = (
                "\n\nOUTPUT REQUIREMENTS:\n"
                "- Return the MODIFIED image with ALL listed fixes applied.\n"
                "- Every fix must be visible but subtle — professional quality.\n"
                "- NOTHING outside the specified regions should be changed.\n"
                "- The overall image must remain cohesive and aesthetically consistent."
            )
            return header + "TARGETED FIXES (apply in order):\n" + body + footer

    # ------------------------------------------------------------------
    # 3. Build preview mask (chi hien thi UI, khong gui API)
    # ------------------------------------------------------------------
    def build_mask_preview(
        self,
        image_bytes: bytes,
        errors: List[dict],
        error_indices: List[int],
        analysis_result: Optional[dict] = None,
    ) -> bytes:
        """
        Tao anh preview: overlay do ban trong len vung loi.
        Tra ve bytes PNG.
        """
        from box_coordinates import (
            COORD_FRAME_PIXEL,
            grid_to_pixel_xyxy,
            resolve_best_box_pixel,
            scale_pixel_box_to_image,
            scale_pixel_to_source,
        )

        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        W, H = img.size
        meta = analysis_result or {}
        isz = meta.get("isz") or {}
        ref_w = int(isz.get("w") or W)
        ref_h = int(isz.get("h") or H)
        coord_space = meta.get("coord_space") or COORD_FRAME_PIXEL
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        selected = [errors[i] for i in error_indices if 0 <= i < len(errors)]
        for err in selected:
            pixel = None
            raw = err.get("c") or err.get("box_2d")
            # Post-process: e[].c = pixel trên isz (frame_pixel) — không parse lại như grid 0–1000
            if isinstance(raw, list) and len(raw) == 4:
                pixel = scale_pixel_box_to_image(raw, ref_w, ref_h, W, H)
            if pixel is None and coord_space != COORD_FRAME_PIXEL:
                g = err.get("c_grid")
                if isinstance(g, list) and len(g) == 4:
                    pixel = grid_to_pixel_xyxy(g, ref_w, ref_h, pad_px=0)
                    if pixel and (ref_w != W or ref_h != H):
                        pixel = scale_pixel_to_source(pixel, ref_w, ref_h, W, H)
            if pixel is None:
                combined = (
                    f"{err.get('issue') or ''} {err.get('suggestion') or ''} {err.get('r') or ''}"
                )
                pixel = resolve_best_box_pixel(err, combined, ref_w, ref_h)
                if pixel and (ref_w != W or ref_h != H):
                    pixel = scale_pixel_to_source(pixel, ref_w, ref_h, W, H)
            if not pixel:
                continue
            x1, y1, x2, y2 = pixel
            draw.rectangle(
                [x1, y1, x2, y2],
                fill=(220, 30, 30, 100),
                outline=(255, 0, 0, 200),
                width=3,
            )

        composite = Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        composite.save(buf, format="PNG")
        return buf.getvalue()

    # ------------------------------------------------------------------
    # 4. Goi WillaAI Image Edits API (x.ai)
    # ------------------------------------------------------------------
    def run_inpainting(
        self,
        base_image_url: str,
        prompt: str,
        timeout: int = 120,
    ) -> dict:
        """
        Goi WillaAI Image Edits (x.ai) API va tra ve ket qua.

        Returns:
            {
                "success": bool,
                "result_url": str | None,
                "result_bytes": bytes | None,
                "error": str | None
            }
        """
        if not self.api_key:
            return {"success": False, "error": "XAI_API_KEY chua duoc set."}

        print(f"[InpaintAgent] Calling WillaAI Image Edits (x.ai)...")
        print(f"[InpaintAgent] image_url={base_image_url}")
        print(f"[InpaintAgent] prompt={prompt[:100]}...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "grok-imagine-image",
            "prompt": prompt,
            "image": {
                "url": base_image_url,
                "type": "image_url",
            }
        }

        try:
            resp = requests.post(WILLAAI_API_URL, headers=headers, json=payload, timeout=timeout)
        except requests.exceptions.Timeout:
            return {"success": False, "error": f"WillaAI API timeout sau {timeout}s."}
        except Exception as e:
            return {"success": False, "error": f"Request failed: {e}"}

        if resp.status_code != 200:
            try:
                body = resp.json()
                msg  = body.get("message", resp.text[:200])
            except Exception:
                msg = resp.text[:200]
            return {"success": False, "error": f"WillaAI API error {resp.status_code}: {msg}"}

        try:
            body = resp.json()
            data = body.get("data", [])
            if not data:
                return {"success": False, "error": "WillaAI API trả về 0 kết quả."}

            result_url = data[0].get("url")
            if not result_url:
                return {"success": False, "error": f"Khong tim thay URL anh trong response: {str(body)[:300]}"}

            print(f"[InpaintAgent] Result URL: {result_url[:80]}...")

            # Download anh ket qua
            dl = requests.get(result_url, timeout=60)
            if dl.status_code != 200:
                return {"success": False, "error": f"Download result failed: HTTP {dl.status_code}"}

            return {
                "success": True,
                "result_url": result_url,
                "result_bytes": dl.content,
            }

        except Exception as e:
            return {"success": False, "error": f"Parse error: {e}. Body: {str(resp.text)[:300]}"}

    def fix_errors(
        self,
        image_bytes: bytes,
        analysis_result: dict,
        error_indices: List[int],
        session_id: str,
        custom_prompt: Optional[str] = None,
        translator_cb=None,
        lang: str = "en",
    ) -> dict:
        """
        Full pipeline: upload ảnh -> build prompt -> gọi WillaAI (x.ai) -> trả về kết quả.

        Returns:
            {
                "success": bool,
                "result_bytes": bytes | None,
                "result_url": str | None,
                "prompt_used": str,
                "error": str | None
            }
        """
        errors = analysis_result.get("e", []) or analysis_result.get("errors", [])

        if custom_prompt and custom_prompt.strip():
            prompt = custom_prompt.strip()
        else:
            prompt = self.build_prompt(errors, error_indices, translator_cb=translator_cb, lang=lang)

        print(f"[InpaintAgent] fix_errors: {len(error_indices)} errors selected")
        print(f"[InpaintAgent] Prompt: {prompt[:100]}...")

        # 2. Luu local -> Upload len ImgBB lay public URL
        local_path = self.save_local_image(image_bytes, session_id)
        public_url = self.upload_to_imgbb(local_path)

        # 3. Goi WillaAI API de redesign
        result = self.run_inpainting(base_image_url=public_url, prompt=prompt)
        result["prompt_used"] = prompt

        return result
