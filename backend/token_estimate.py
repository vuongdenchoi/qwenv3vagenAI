"""
Ước lượng token Phase 3 — công thức đồng bộ với WillA_AI QwenTokenEstimateServiceImpl.

DashScope ACTUAL = 1 lần gọi DesignCheckAgent.analyze (không Phase 2A/2B).
Xem docs/TOKEN_ESTIMATE.md
"""
from __future__ import annotations

import math
import os
from io import BytesIO
from typing import Any

from PIL import Image

from box_coordinates import ANALYSIS_MAX_EDGE

# Đồng bộ application.yaml ai.qwen.token-estimate (override qua env Docker)
PATCH_FACTOR = int(os.getenv("QWEN_PATCH_FACTOR", "28"))
MIN_PIXELS = int(os.getenv("QWEN_MIN_PIXELS", "3136"))
MAX_PIXELS = int(os.getenv("QWEN_MAX_PIXELS", "12845056"))
CHARS_PER_TOKEN = float(os.getenv("QWEN_CHARS_PER_TOKEN", "3.2"))
SAFETY_MARGIN_PERCENT = int(os.getenv("QWEN_ESTIMATE_SAFETY_MARGIN_PERCENT", "2"))
TOTAL_SAFETY_MARGIN_PERCENT = float(os.getenv("QWEN_ESTIMATE_TOTAL_MARGIN_PERCENT", "1.5"))

BASE_PROMPT_TOKENS = int(os.getenv("QWEN_ESTIMATE_BASE_PROMPT", "2650"))
OUTPUT_TYPICAL = int(os.getenv("QWEN_ESTIMATE_OUTPUT_TYPICAL", "1100"))
OUTPUT_MIN = int(os.getenv("QWEN_ESTIMATE_OUTPUT_MIN", "860"))
OUTPUT_MAX = int(os.getenv("QWEN_ESTIMATE_OUTPUT_MAX", "1320"))
OUTPUT_PIVOT = int(os.getenv("QWEN_ESTIMATE_OUTPUT_PIVOT", "1100"))
OUTPUT_SMALL_DIV = float(os.getenv("QWEN_ESTIMATE_OUTPUT_SMALL_DIV", "1.5"))
OUTPUT_LARGE_FACTOR = float(os.getenv("QWEN_ESTIMATE_OUTPUT_LARGE_FACTOR", "0.4"))
OUTPUT_ADJUST_MAX = int(os.getenv("QWEN_ESTIMATE_OUTPUT_ADJUST_MAX", "220"))
SMALL_IMAGE_BOOST_THRESHOLD = int(os.getenv("QWEN_ESTIMATE_BOOST_THRESHOLD", "1500"))
SMALL_IMAGE_BOOST_FACTOR = float(os.getenv("QWEN_ESTIMATE_BOOST_FACTOR", "0.50"))
WALLET_BUFFER_TOKENS = int(os.getenv("QWEN_ESTIMATE_WALLET_BUFFER", "100"))


def text_tokens(text: str) -> int:
    if not text:
        return 0
    return int(math.ceil(len(text) / max(CHARS_PER_TOKEN, 0.1)))


def _round_to_factor(value: int, factor: int) -> int:
    return max(factor, (value // factor) * factor)


def smart_resize(width: int, height: int) -> tuple[int, int]:
    """Khớp QwenVisionTokenMath.smartResize (Java)."""
    if width <= 0 or height <= 0:
        return 0, 0
    aspect = width / height
    pixels = width * height
    pf = PATCH_FACTOR

    if pixels > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / pixels)
        width = max(pf, _round_to_factor(int(width * scale), pf))
        height = max(pf, _round_to_factor(int(height * scale), pf))
    elif pixels < MIN_PIXELS:
        scale = math.sqrt(MIN_PIXELS / pixels)
        width = _round_to_factor(int(width * scale), pf)
        height = _round_to_factor(int(height * scale), pf)
    else:
        width = _round_to_factor(width, pf)
        height = _round_to_factor(height, pf)

    width = max(width, pf)
    height = max(height, pf)
    if aspect > 0 and abs(width / height - aspect) > 0.01:
        height = max(pf, _round_to_factor(int(width / aspect), pf))
    return width, height


def analysis_frame_size(width: int, height: int) -> tuple[int, int]:
    """Thumbnail max edge — khớp main.py + AiImageFrameUtil."""
    if width <= 0 or height <= 0:
        return 0, 0
    if width <= ANALYSIS_MAX_EDGE and height <= ANALYSIS_MAX_EDGE:
        return width, height
    scale = min(ANALYSIS_MAX_EDGE / width, ANALYSIS_MAX_EDGE / height)
    return max(1, int(math.floor(width * scale))), max(1, int(math.floor(height * scale)))


def billable_image_tokens(width: int, height: int) -> int:
    w, h = smart_resize(width, height)
    if w <= 0 or h <= 0:
        return 0
    patch_area = PATCH_FACTOR * PATCH_FACTOR
    return max(1, (w * h) // patch_area)


def prepare_analysis_image(image_bytes: bytes) -> tuple[bytes, int, int]:
    """
    Giống main.py upload: RGB + thumbnail → bytes gửi Qwen.
    Returns (bytes, frame_w, frame_h).
    """
    img = Image.open(BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > ANALYSIS_MAX_EDGE or img.height > ANALYSIS_MAX_EDGE:
        img.thumbnail((ANALYSIS_MAX_EDGE, ANALYSIS_MAX_EDGE), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), img.width, img.height
    return image_bytes, img.width, img.height


def estimate_phase3_text_tokens(image_tokens: int, user_text_tokens: int) -> int:
    text = BASE_PROMPT_TOKENS + user_text_tokens
    headroom = SMALL_IMAGE_BOOST_THRESHOLD - image_tokens
    if headroom > 0 and SMALL_IMAGE_BOOST_FACTOR > 0:
        text += int(round(headroom * SMALL_IMAGE_BOOST_FACTOR))
    return text


def with_output_margin(output_tokens: int) -> int:
    if output_tokens <= 0 or SAFETY_MARGIN_PERCENT <= 0:
        return output_tokens
    return output_tokens + (output_tokens * SAFETY_MARGIN_PERCENT // 100)


def with_total_safety_margin(subtotal: int) -> int:
    if subtotal <= 0 or TOTAL_SAFETY_MARGIN_PERCENT <= 0:
        return subtotal
    return subtotal + int(round(subtotal * TOTAL_SAFETY_MARGIN_PERCENT / 100.0))


def estimate_output_tokens(image_tokens: int) -> int:
    """Output JSON Phase 3 — điều chỉnh theo vision token (đồng bộ Java)."""
    adjust = 0
    if image_tokens < OUTPUT_PIVOT and OUTPUT_SMALL_DIV > 0:
        adjust = -min(
            OUTPUT_ADJUST_MAX,
            int(round((OUTPUT_PIVOT - image_tokens) / OUTPUT_SMALL_DIV)),
        )
    elif image_tokens > OUTPUT_PIVOT and OUTPUT_LARGE_FACTOR > 0:
        adjust = min(
            OUTPUT_ADJUST_MAX,
            int(round((image_tokens - OUTPUT_PIVOT) * OUTPUT_LARGE_FACTOR)),
        )
    base = OUTPUT_TYPICAL + adjust
    clamped = max(OUTPUT_MIN, min(OUTPUT_MAX, base))
    return with_output_margin(clamped)


def estimate_phase3(
    image_bytes: bytes,
    user_message: str = "",
    extra_text: str = "",
) -> dict[str, Any]:
    """
    Ước lượng 1 ảnh Phase 3.
    extra_text: persona_context JSON (BE cộng vào mỗi ảnh).
    """
    _, frame_w, frame_h = prepare_analysis_image(image_bytes)
    img_tok = billable_image_tokens(frame_w, frame_h)
    user_tok = text_tokens(user_message) + text_tokens(extra_text)
    text_tok = estimate_phase3_text_tokens(img_tok, user_tok)
    input_tokens = img_tok + text_tok + WALLET_BUFFER_TOKENS
    output_tokens = estimate_output_tokens(img_tok)
    subtotal = input_tokens + output_tokens
    total = with_total_safety_margin(subtotal)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "breakdown": {
            "image_tokens": img_tok,
            "text_tokens": text_tok,
            "user_message_tokens": text_tokens(user_message),
            "extra_text_tokens": text_tokens(extra_text),
            "wallet_buffer": WALLET_BUFFER_TOKENS,
            "frame_width": frame_w,
            "frame_height": frame_h,
            "base_prompt_tokens": BASE_PROMPT_TOKENS,
            "output_typical": OUTPUT_TYPICAL,
            "output_pivot": OUTPUT_PIVOT,
        },
    }


def estimate_text_chat(
    user_message: str = "",
    extra_text: str = "",
    *,
    session_has_image: bool = False,
    history_text_tokens: int = 0,
    analysis_context_tokens: int = 0,
) -> dict[str, Any]:
    """
    Chat không upload ảnh — đồng bộ QwenTokenEstimateServiceImpl.estimateTextChat.
    session_has_image: session đã phân tích → intent routing; ngược lại chat thuần.
    """
    ROUTING_SYSTEM = int(os.getenv("QWEN_ESTIMATE_CHAT_ROUTING_SYSTEM", "1180"))
    ROUTING_STATE = int(os.getenv("QWEN_ESTIMATE_CHAT_ROUTING_STATE", "120"))
    ROUTING_OUTPUT = int(os.getenv("QWEN_ESTIMATE_CHAT_ROUTING_OUTPUT", "480"))
    PLAIN_SYSTEM = int(os.getenv("QWEN_ESTIMATE_CHAT_PLAIN_SYSTEM", "120"))
    PLAIN_OUTPUT = int(os.getenv("QWEN_ESTIMATE_CHAT_PLAIN_OUTPUT", "550"))
    CHAT_BUFFER = int(os.getenv("QWEN_ESTIMATE_CHAT_BUFFER", "60"))
    HISTORY_CAP = int(os.getenv("QWEN_ESTIMATE_CHAT_HISTORY_CAP", "450"))

    persona_tok = text_tokens(extra_text)
    user_tok = text_tokens(user_message)
    history_tok = min(max(0, history_text_tokens), HISTORY_CAP) if HISTORY_CAP > 0 else max(0, history_text_tokens)

    if session_has_image:
        input_tokens = (
            ROUTING_SYSTEM
            + ROUTING_STATE
            + persona_tok
            + user_tok
            + history_tok
            + max(0, analysis_context_tokens)
            + CHAT_BUFFER
        )
        output_tokens = with_output_margin(ROUTING_OUTPUT)
        mode = "text-session-routing"
    else:
        input_tokens = PLAIN_SYSTEM + persona_tok + user_tok + CHAT_BUFFER
        output_tokens = with_output_margin(PLAIN_OUTPUT)
        mode = "text-plain"

    subtotal = input_tokens + output_tokens
    total = with_total_safety_margin(subtotal)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total,
        "mode": mode,
        "breakdown": {
            "persona_tokens": persona_tok,
            "user_tokens": user_tok,
            "history_tokens": history_tok,
            "analysis_context_tokens": analysis_context_tokens,
        },
    }


def log_estimate_vs_actual(estimate: dict[str, Any], usage: dict[str, Any], label: str = "Phase3") -> None:
    """Log cùng format BE: ESTIMATE vs ACTUAL."""
    est_total = estimate.get("total_tokens", 0)
    act_in = int(usage.get("input_tokens", 0) or 0)
    act_out = int(usage.get("output_tokens", 0) or 0)
    act_total = int(usage.get("total_tokens", 0) or 0) or (act_in + act_out)
    b = estimate.get("breakdown") or {}
    print(
        f"[Token] ESTIMATE ({label}): input={estimate.get('input_tokens')}, "
        f"output={estimate.get('output_tokens')}, total={est_total} "
        f"(img={b.get('image_tokens')}, text={b.get('text_tokens')}, buffer={b.get('wallet_buffer')}, "
        f"frame={b.get('frame_width')}x{b.get('frame_height')})"
    )
    print(
        f"[Token] ACTUAL ({label}): input={act_in}, output={act_out}, total={act_total} "
        f"| vs estimate total={est_total}"
    )
