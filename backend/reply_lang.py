"""Đồng bộ ngôn ngữ UI (vi/en) với phản hồi AI."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def env_default_reply_lang() -> str:
    lang = (os.getenv("AI_ROUTER_REPLY_LANG", "vi") or "vi").strip().lower()
    if lang in {"en", "vi", "auto"}:
        return lang
    return "auto"


def normalize_reply_lang(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    lang = str(raw).strip().lower()
    if lang in {"vi", "en"}:
        return lang
    return None


def resolve_reply_lang(session_key: str, request_lang: Optional[str], memory_store) -> str:
    """Ưu tiên: request FE → memory session → env (auto/vi/en)."""
    norm = normalize_reply_lang(request_lang)
    if norm:
        memory_store.set_reply_lang(session_key, norm)
        return norm
    stored = memory_store.get_reply_lang(session_key)
    if stored in {"vi", "en"}:
        return stored
    default = env_default_reply_lang()
    if default in {"vi", "en"}:
        return default
    return "vi"


def router_language_instruction(lang: str) -> str:
    if lang == "en":
        return (
            "You MUST speak English in all chat responses. "
            "All output strings and replies MUST be written entirely in English."
        )
    return (
        "Bạn PHẢI trả lời bằng tiếng Việt trong toàn bộ phản hồi chat. "
        "Mọi chuỗi output và reply phải được viết hoàn toàn bằng tiếng Việt tự nhiên."
    )


def analysis_output_language_clause(lang: str) -> str:
    if lang == "vi":
        return (
            "QUAN TRỌNG — NGÔN NGỮ ĐẦU RA: Mọi trường compliments, issue, suggestion, reasoning ('r') "
            "PHẢI viết 100% bằng tiếng Việt tự nhiên. CẤM dùng tiếng Anh trong nội dung hiển thị cho người dùng. "
            "Dù design rules bên dưới là tiếng Anh, bạn vẫn phải diễn đạt phản hồi bằng tiếng Việt."
        )
    return (
        "All output text, including compliments, reasoning ('r'), issues, and suggestions, "
        "MUST be written entirely in English. Do not return Vietnamese in user-facing fields."
    )


def _t(lang: str, vi: str, en: str) -> str:
    return vi if lang == "vi" else en


def format_compliments_block(result: Dict[str, Any], lang: str) -> str:
    compliments = result.get("compliments", [])
    if not compliments:
        return ""
    header = _t(lang, "✨ Điểm nổi bật thiết kế:\n", "✨ Design Highlights:\n")
    text = header
    for c in compliments:
        text += f"💚 {c}\n"
    return text + "\n"


def format_post_context_analysis_reply(
    result: Dict[str, Any],
    lang: str,
    *,
    deep: bool = False,
    stored_only: bool = False,
) -> str:
    """Phản hồi sau khi xác nhận bối cảnh và chạy lại critique."""
    compliments_text = format_compliments_block(result, lang)
    error_count = result.get("te", 0)
    if deep:
        header = _t(lang, "✅ Đã xác nhận bối cảnh thiết kế!\n\n", "✅ Design context confirmed successfully!\n\n")
        body = _t(
            lang,
            f"Tôi đã phân tích sâu và phát hiện **{error_count}** lỗi thiết kế theo bối cảnh mới.\n"
            "Bạn có thể xem khung lỗi trên ảnh, hoặc tiếp tục chat để zoom/sửa.",
            f"I have conducted a deep critique and detected **{error_count}** visual design issues based on your new context.\n"
            "You can view highlighted bounding boxes on the image, or chat further to zoom/edit.",
        )
    elif stored_only:
        header = _t(lang, "✅ Đã xác nhận bối cảnh!\n\n", "✅ Context confirmed!\n\n")
        body = _t(
            lang,
            f"Tôi đã phân tích và phát hiện **{error_count}** lỗi thiết kế.\n"
            "Bạn có thể xem lỗi trên ảnh, hoặc chat để sửa (vd: 'sửa lỗi #1', 'sửa tất cả').",
            f"I have analyzed and found **{error_count}** visual design error(s).\n"
            "You can see the highlighted errors on the image, or continue chatting to fix them (e.g., 'fix error #1', 'fix all errors').",
        )
    else:
        header = _t(lang, "✅ Đã xác nhận bối cảnh!\n\n", "✅ Context confirmed!\n\n")
        body = _t(
            lang,
            f"Tôi đã phân tích lại và phát hiện **{error_count}** lỗi thiết kế theo bối cảnh mới.\n"
            "Bạn có thể xem lỗi trên ảnh, hoặc chat để sửa (vd: 'sửa lỗi #1', 'sửa tất cả').",
            f"I have re-analyzed and found **{error_count}** visual design error(s) based on the new context.\n"
            "You can see the highlighted errors on the image, or continue chatting to fix them (e.g., 'fix error #1', 'fix all errors').",
        )
    return header + compliments_text + body


def format_initial_analysis_reply(result: Dict[str, Any], lang: str) -> str:
    compliments = result.get("compliments", [])
    compliments_text = ""
    if compliments:
        header = "✨ Điểm nổi bật thiết kế:\n" if lang == "vi" else "✨ Design Highlights:\n"
        compliments_text = header
        for c in compliments:
            compliments_text += f"💚 {c}\n"
        compliments_text += "\n"

    error_count = result.get("te", 0)
    error_list_text = ""
    if error_count > 0:
        header = "⚠️ Các lỗi chính cần xử lý:\n" if lang == "vi" else "⚠️ Key Issues to Address:\n"
        error_list_text = header
        for err in result.get("e", [])[:3]:
            issue = err.get("issue") or err.get("r", "")
            error_list_text += f"- {issue}\n"
        error_list_text += "\n"

    if lang == "vi":
        return (
            "Chào mừng bạn đến với Willa AI! 🚀\n\n"
            f"{compliments_text}"
            f"💡 Tôi phát hiện **{error_count}** lỗi thiết kế có thể cải thiện.\n"
            f"{error_list_text}"
            "Bạn có thể xem khung lỗi trực tiếp trên ảnh.\n\n"
            "👉 Muốn phân tích bối cảnh theo **8 chiều Rubic**, hãy nhắn **\"bối cảnh\"** hoặc **\"Rubic\"**!"
        )
    return (
        "Welcome to Willa AI! 🚀\n\n"
        f"{compliments_text}"
        f"💡 I detected **{error_count}** visual critique issues that can be improved.\n"
        f"{error_list_text}"
        "You can view highlighted error bounding boxes directly on the image.\n\n"
        "👉 To analyze contextual suitability across **8 Rubic dimensions**, ask using **\"context\"** or **\"Rubic\"**!"
    )
