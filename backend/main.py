import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path, override=True)

os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"

import io
import sys
from typing import Optional, Tuple, Dict, Any, List
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from PIL import Image, ImageDraw
import base64
import re
import json
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from box_coordinates import (
    clamp_pixel_xyxy,
    COORD_FRAME_PIXEL,
    COORD_SOURCE_PIXEL,
    grid_to_pixel_xyxy,
    is_qwen_grid_1000,
    resolve_best_box_pixel,
)

# Patch requests and ssl to bypass SSL verification globally (disabled as it breaks on this system)
# import ssl
# _original_create_default_context = ssl.create_default_context
# def _patched_create_default_context(*args, **kwargs):
#     context = _original_create_default_context(*args, **kwargs)
#     context.check_hostname = False
#     context.verify_mode = ssl.CERT_NONE
#     return context
# ssl.create_default_context = _patched_create_default_context
# ssl._create_default_https_context = ssl._create_unverified_context
# 
# _original_request = requests.Session.request
# def _patched_request(self, method, url, *args, **kwargs):
#     kwargs['verify'] = False
#     return _original_request(self, method, url, *args, **kwargs)
# requests.Session.request = _patched_request
# 
# # Patch urllib3 to bypass SSL verification globally
# try:
#     import urllib3.util.ssl_
#     urllib3.util.ssl_.create_urllib3_context = lambda *args, **kwargs: ssl._create_unverified_context()
# except Exception as e:
#     print(f"[WARNING] Failed to patch urllib3: {e}")



from agents.design_check_agent import DesignCheckAgent
from agents.inpaint_agent import InpaintAgent
from agents.style_suggest_agent import StyleSuggestAgent
from memory_store import build_memory_store_from_env
from reply_lang import (
    _t,
    conversation_continuity_instruction,
    format_initial_analysis_reply,
    format_post_context_analysis_reply,
    resolve_reply_lang,
    router_language_instruction as localized_router_instruction,
)

# Windows console encoding fix
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

app = FastAPI(title="Design Check AI", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Thư mục tạm chứa ảnh gốc để host cho Wan API truy cập
TEMP_ASSETS_DIR = Path(__file__).parent / "static_temp"
TEMP_ASSETS_DIR.mkdir(exist_ok=True)
app.mount("/temp-assets", StaticFiles(directory=str(TEMP_ASSETS_DIR)), name="temp-assets")

_agent = None
_inpaint_agent = None
memory_store = build_memory_store_from_env()

def get_agent():
    global _agent
    if _agent is None:
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        _agent = DesignCheckAgent(api_key=api_key)
    return _agent

def get_inpaint_agent():
    global _inpaint_agent
    if _inpaint_agent is None:
        api_key         = os.getenv("XAI_API_KEY", "")
        public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
        imgbb_api_key   = os.getenv("IMGBB_API_KEY", "")
        _inpaint_agent  = InpaintAgent(
            api_key=api_key,
            public_base_url=public_base_url,
            imgbb_api_key=imgbb_api_key,
        )
    return _inpaint_agent

_style_agent = None
def get_style_agent():
    global _style_agent
    if _style_agent is None:
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        _style_agent = StyleSuggestAgent(api_key=api_key)
    return _style_agent

def check_is_confirm(msg: str) -> bool:
    """
    Hàm trợ giúp kiểm tra xem tin nhắn người dùng có phải là xác nhận sinh ảnh hay không.
    Hỗ trợ cả các cụm từ Tiếng Việt và Tiếng Anh phổ biến kèm theo các hậu tố.
    """
    msg_lower = msg.lower().strip()
    confirm_words = [
        "ok", "oke", "okay", "okey", "dong y", "đồng ý", "dung", "đúng", "chinh xac", "chính xác", 
        "yes", "y", "dong vay", "đúng vậy", "chay di", "chạy đi", "lam di", "làm đi", "tien hanh", 
        "tiến hành", "tao anh", "tạo ảnh", "tao anh moi", "tạo ảnh mới", "ve di", "vẽ đi", 
        "ve luon", "vẽ luôn", "lam luon", "làm luôn", "nhat tri", "nhất trí", "chuan", "chuẩn",
        "approved", "confirm", "xac nhan", "xác nhận", "start", "bat dau", "bắt đầu", "ok nha", "ok nhé"
    ]
    
    if msg_lower in confirm_words:
        return True
        
    for word in confirm_words:
        # Khớp các trường hợp như "ok!", "ok.", "làm đi!", "chạy đi..."
        if msg_lower.startswith(word + " ") or msg_lower.startswith(word + "!") or msg_lower.startswith(word + ".") or msg_lower.startswith(word + ","):
            return True
            
    return False


def looks_like_direct_image_edit_request(msg: str) -> bool:
    """
    Heuristic shortcut for concrete visual edit commands.
    Used to avoid router ambiguity where edit requests are answered as plain chat.
    """
    t = (msg or "").strip().lower()
    if not t:
        return False
    patterns = [
        "đổi màu", "thay màu", "đổi chữ", "thay chữ", "sửa ảnh", "chỉnh ảnh",
        "chuyển", "đổi ", "thay ", "replace ", "change ", "edit ",
        "remove ", "xóa ", "thêm ", "add ", "make ", "turn ",
        "thành ", "to #", "color #"
    ]
    # Need at least one action keyword + one target hint to reduce false positive.
    target_hints = ["nhân vật", "character", "text", "chữ", "màu", "color", "logo", "superman", "luffy", "#"]
    return any(p in t for p in patterns) and any(h in t for h in target_hints)


def get_router_reply_lang() -> str:
    """
    Router reply language mode:
    - en: always English
    - vi: always Vietnamese
    - auto: follow user's message language
    """
    lang = (os.getenv("AI_ROUTER_REPLY_LANG", "auto") or "auto").strip().lower()
    if lang in {"en", "vi", "auto"}:
        return lang
    return "vi"


def is_vietnamese(text: str) -> bool:
    vietnamese_chars = set("àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệđìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆĐÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴ")
    return any(char in vietnamese_chars for char in text)


def detect_feedback_language(msg: str) -> str:
    lang_mode = get_router_reply_lang()
    if lang_mode == "vi":
        return "vi"
    elif lang_mode == "en":
        return "en"
    else:  # auto
        if msg and is_vietnamese(msg):
            return "vi"
        return "en"


def router_language_instruction() -> str:
    lang = get_router_reply_lang()
    if lang == "en":
        return (
            "You MUST speak English in all chat responses. "
            "All output strings and replies MUST be written entirely in English."
        )
    if lang == "vi":
        return (
            "Bạn PHẢI trả lời bằng tiếng Việt trong toàn bộ phản hồi chat. "
            "Mọi chuỗi output và reply phải được viết hoàn toàn bằng tiếng Việt tự nhiên."
        )
    return (
        "Use the same language as the user's latest message for all replies "
        "(Vietnamese user message -> Vietnamese reply, English user message -> English reply)."
    )

def classify_image_type(image_bytes: bytes) -> dict:
    import base64
    import json
    import os
    import requests
    
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        return {"type": "design", "confidence": 1.0, "signals": []}
        
    encoded = base64.b64encode(image_bytes).decode('utf-8')
    prompt = 'You are an image classifier.\n\nAnalyze the image and classify it as ONE of:\n- "photo": a real photograph taken with a camera (people, nature, food, objects, etc.)\n- "design": a graphic design file (poster, banner, logo, UI mockup, infographic, illustration)\n\nRespond ONLY with this JSON, no markdown, no explanation:\n{\n  "type": "photo" | "design",\n  "confidence": 0.0-1.0,\n  "signals": ["signal1", "signal2", "signal3"]\n}'
    
    payload = {
        "model": "qwen-vl-plus",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                {"type": "text", "text": prompt}
            ]
        }],
        "max_tokens": 200
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", headers=headers, json=payload, timeout=60)
        if resp.ok:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
    except Exception as e:
        print(f"[ClassifyImage] Error: {e}")
    
    return {"type": "design", "confidence": 1.0, "signals": []}

def sanitize_secret(text: str, secret: str) -> str:
    if secret and isinstance(text, str) and secret in text:
        return text.replace(secret, "***REDACTED***")
    return text


def generate_or_edit_image(key: str, prompt: str, image_bytes: Optional[bytes] = None) -> dict:
    """
    Tạo hoặc sửa đổi ảnh bằng xAI Grok.
    Nếu có image_bytes, sử dụng InpaintAgent để sửa đổi (image-to-image) nhằm giữ lại bối cảnh cũ.
    """
    actual_grok_key = os.getenv("XAI_API_KEY", "")
    if not actual_grok_key:
        return {"success": False, "error": "Thiếu XAI_API_KEY để sinh ảnh."}

    if image_bytes:
        try:
            print(f"Phát hiện ảnh gốc, sử dụng InpaintAgent để sửa ảnh (Image-to-Image)")
            inpaint_agent = get_inpaint_agent()
            result = inpaint_agent.fix_errors(
                image_bytes=image_bytes,
                analysis_result={},
                error_indices=[],
                session_id=key,
                custom_prompt=prompt
            )
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("result_url"),
                    "image_bytes": result.get("result_bytes")
                }
            else:
                print(f"InpaintAgent thất bại: {result.get('error')}. Fallback sang text-to-image...")
        except Exception as e:
            print(f"Lỗi dùng InpaintAgent cho chat: {e}. Fallback sang text-to-image...")

    # Fallback hoặc khi không có ảnh
    xai_headers = {
        "Authorization": f"Bearer {actual_grok_key}",
        "Content-Type": "application/json"
    }
    xai_payload = {
        "prompt": prompt,
        "model": "grok-imagine-image-quality"
    }
    try:
        resp = requests.post("https://api.x.ai/v1/images/generations", headers=xai_headers, json=xai_payload, timeout=60)
        if resp.ok:
            xai_data = resp.json()
            images = xai_data.get("data", [])
            if images:
                image_url = images[0].get("url")
                # Download ảnh fallback
                dl = requests.get(image_url, timeout=60)
                dl_bytes = dl.content if dl.ok else None
                return {
                    "success": True,
                    "image_url": image_url,
                    "image_bytes": dl_bytes
                }
        safe_error = sanitize_secret(resp.text, actual_grok_key)
        return {"success": False, "error": f"Lỗi xAI API: {safe_error}"}
    except Exception as e:
        return {"success": False, "error": f"Lỗi gọi API: {e}"}

@app.get("/")
async def serve_frontend():
    index_html = FRONTEND_DIR / "index.html"
    if index_html.exists():
        return FileResponse(
            str(index_html),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "Design Check AI backend is running"}

@app.get("/element-layer")
async def serve_element_layer():
    element_layer_html = FRONTEND_DIR / "element-layer.html"
    if element_layer_html.exists():
        return FileResponse(
            str(element_layer_html),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "Element layer page not found"}

@app.get("/ux-audit-ui")
async def serve_ux_audit_ui():
    ux_audit_html = FRONTEND_DIR / "ux-audit.html"
    if ux_audit_html.exists():
        return FileResponse(
            str(ux_audit_html),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "UX Audit page not found"}


@app.get("/live-demo")
async def serve_live_demo():
    live_demo_html = FRONTEND_DIR / "live-demo.html"
    if live_demo_html.exists():
        return FileResponse(
            str(live_demo_html),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "Live demo page not found"}

@app.get("/grok-chat")
async def serve_grok_chat():
    grok_chat_html = FRONTEND_DIR / "grok-chat.html"
    if grok_chat_html.exists():
        return FileResponse(
            str(grok_chat_html),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "Grok chat page not found"}

@app.get("/mini-brand-kit")
async def serve_mini_brand_kit():
    html_file = FRONTEND_DIR / "mini-brand-kit.html"
    if html_file.exists():
        return FileResponse(
            str(html_file),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
        )
    return {"message": "Mini Brand Kit page not found"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "Design Check AI"}


@app.post("/estimate")
async def estimate_tokens(
    file: UploadFile = File(None),
    message: str = Form(""),
    persona_context: Optional[str] = Form(None),
):
    """
    Ước lượng token Phase 3 — cùng công thức WillA_AI (QwenTokenEstimateServiceImpl).
    Không gọi DashScope. Dùng để debug / đối chiếu với log ACTUAL.
    """
    from token_estimate import estimate_phase3

    if file is None or not file.filename:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "image_count": 0,
            "breakdown": {},
        }
    img_data = await file.read()
    if len(img_data) == 0:
        raise HTTPException(status_code=400, detail="Empty image file")
    result = estimate_phase3(img_data, user_message=message or "", extra_text=persona_context or "")
    result["image_count"] = 1
    return result


@app.post("/ux-audit")
async def ux_audit(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(""),
    lang: Optional[str] = Form(None),
    reply_lang: Optional[str] = Form(None),
    persona_context: Optional[str] = Form(None)
):
    """
    Endpoint thực hiện Hybrid Multi-Agent UX Audit.
    Tầng 1: Florence-2/OWL-ViT local.
    Tầng 2: Spacing/Alignment/Contrast.
    Tầng 3: LLM Critic.
    """
    key = session_id.strip() if session_id else "anonymous"
    resolved_lang = resolve_reply_lang(key, lang or reply_lang, memory_store)
    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp file ảnh thiết kế.")
    
    img_data = await file.read()
    if len(img_data) == 0:
        raise HTTPException(status_code=400, detail="File ảnh rỗng.")
        
    try:
        img = Image.open(io.BytesIO(img_data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        MAX_SIZE = 1536
        if img.width > MAX_SIZE or img.height > MAX_SIZE:
            img.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=85)
            img_data = out_buf.getvalue()
            print(f"[UX Audit API] Đã scale ảnh xuống {img.width}x{img.height}.")
            img = Image.open(io.BytesIO(img_data))
    except Exception as e:
        print(f"[UX Audit API] Lỗi xử lý/scale ảnh: {e}")
        
    cls_res = classify_image_type(img_data)
    if cls_res.get("type") != "design" or cls_res.get("confidence", 0.0) <= 0.70:
        if resolved_lang == "vi":
            msg = "Đây là ảnh không phải thiết kế."
        else:
            msg = "This is a photo, not a design."
        return {
            "success": False,
            "error": msg,
            "errors": [],
            "detected_elements": [],
            "summary": msg,
            "details": [],
            "markdown_report": msg,
            "image_size": {"w": 0, "h": 0}
        }

    try:
        persona_dict = parse_persona(persona_context)
        if persona_dict:
            patterns = persona_dict.get("designPatterns", {})
            recent_count = patterns.get("recentAnalysisCount", 0)
            cats = len(patterns.get("topIssueCategories", []))
            print(f"[UX Audit API] Loaded persona context: recentAnalysisCount={recent_count}, categoriesCount={cats}")
            
        agent = get_agent()
        result = agent.run_ux_audit(img_data, lang=resolved_lang, persona_context=persona_dict)
        
        # Tương thích ngược với hệ thống session/zoom
        legacy_errors = []
        for idx, err in enumerate(result["errors"]):
            grid_box = err["c"]
            pixel_box = grid_to_pixel_xyxy(grid_box, img.width, img.height)
            if not pixel_box:
                x1 = int(grid_box[0] / 1000.0 * img.width)
                y1 = int(grid_box[1] / 1000.0 * img.height)
                x2 = int(grid_box[2] / 1000.0 * img.width)
                y2 = int(grid_box[3] / 1000.0 * img.height)
                pixel_box = [x1, y1, x2, y2]
            legacy_errors.append({
                "c": pixel_box,
                "c_grid": grid_box,
                "r": err.get("r", ""),
                "s": err.get("s", "minor"),
                "g": err.get("g", "general"),
                "id": idx,
                "issue": err.get("issue", ""),
                "suggestion": err.get("suggestion", ""),
                "reference": err.get("reference")
            })
            
        legacy_result = {
            "e": legacy_errors,
            "te": len(legacy_errors),
            "isz": {"w": img.width, "h": img.height},
            "coord_space": COORD_FRAME_PIXEL,
            "ss": {
                "minor": sum(1 for e in legacy_errors if e["s"] == "minor"),
                "major": sum(1 for e in legacy_errors if e["s"] == "major"),
                "critical": sum(1 for e in legacy_errors if e["s"] == "critical")
            }
        }
        memory_store.set_last_analysis(key, img_data, legacy_result)
        
        return {
            "success": True,
            "errors": result["errors"],
            "detected_elements": result["detected_elements"],
            "summary": result["summary"],
            "details": result["details"],
            "markdown_report": result["markdown_report"],
            "image_size": {"w": img.width, "h": img.height}
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống trong quá trình UX Audit: {str(e)}")



def extract_user_context(user_text: str) -> Tuple[bool, Dict[str, Optional[str]]]:
    """
    Sử dụng LLM để trích xuất bối cảnh thiết kế từ câu trả lời của người dùng.
    Trả về: (user_knows, extracted_context)
    """
    user_text_lower = user_text.lower().strip()
    if user_text_lower in [
        "tôi không biết", "không biết", "tôi không rõ", "không rõ", 
        "chịu", "không biết nha", "don't know", "i don't know", "no", "không"
    ]:
        return False, {
            "thoi_gian": None, "dia_diem": None, "lich_su_xa_hoi": None,
            "kinh_te": None, "van_hoa": None, "art_style": None,
            "ty_le": None, "chat_lieu": None
        }
        
    system_prompt = (
        "You are an AI extracting design context information from the user's message.\n"
        "Analyze the message and extract information for the following 8 context dimensions:\n"
        "1. thoi_gian (Time / historical period)\n"
        "2. dia_diem (Location / geographical context)\n"
        "3. lich_su_xa_hoi (Historical / social / political context)\n"
        "4. kinh_te (Economic segment / commercial or non-profit purpose)\n"
        "5. van_hoa (Culture / community / beliefs)\n"
        "6. art_style (Art style / dominant style)\n"
        "7. ty_le (Aspect ratio / composition estimation)\n"
        "8. chat_lieu (Print or digital material/medium)\n\n"
        "Return ONLY JSON in the following format (fields with no information should be set to null):\n"
        "{\n"
        '  "user_knows": true/false,\n'
        '  "context": {\n'
        '    "thoi_gian": "...",\n'
        '    "dia_diem": "...",\n'
        '    "lich_su_xa_hoi": "...",\n'
        '    "kinh_te": "...",\n'
        '    "van_hoa": "...",\n'
        '    "art_style": "...",\n'
        '    "ty_le": "...",\n'
        '    "chat_lieu": "..."\n'
        "  }\n"
        "}"
    )
    
    try:
        agent = get_agent()
        payload = agent.qwen_agent.chat_json(
            system_prompt=system_prompt,
            user_text=user_text,
            history_messages=[]
        )
        user_knows = payload.get("user_knows", False)
        context = payload.get("context", {})
        keys = ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]
        refined_context = {k: context.get(k) for k in keys}
        if all(v is None for v in refined_context.values()):
            user_knows = False
        return user_knows, refined_context
    except Exception as e:
        print(f"Lỗi trích xuất bối cảnh: {e}")
        return False, {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}

def run_antigraviti_phase_2a(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> dict:
    """
    Chạy Phase 2A: Quét hình ảnh bằng Vision API để phân tích 8 chiều bối cảnh + đặc tính trực quan
    """
    lang_req = "You MUST output all text values in Vietnamese (Tiếng Việt)." if lang == "vi" else "CRITICAL: You MUST write all output strings entirely in English. Do NOT use Vietnamese under any circumstances, even if the JSON keys are in Vietnamese."
    system_prompt = (
        "You are a visual context analyzer for design critique. "
        "Analyze the uploaded image strictly along these 8 dimensions and extract visual style traits. "
        "Be specific, factual, and concise. Return structured JSON only. "
        f"{lang_req}"
    )
    instruction = (
        f"Analyze this design image and return a JSON object with these exact keys. {lang_req}\n"
        "{\n"
        '  "thoi_gian": "Time period / historical era evoked by the design",\n'
        '  "dia_diem": "Geographical setting, region, or cultural space",\n'
        '  "lich_su_xa_hoi": "Historical events, social movements, or political background",\n'
        '  "kinh_te": "Economic segment, commercial or non-profit purpose",\n'
        '  "van_hoa": "Cultural background, symbols, or cultural community",\n'
        '  "art_style": "Art style (specific name + identifying characteristics)",\n'
        '  "ty_le": "Aspect ratio and layout structure estimate",\n'
        '  "chat_lieu": "Evoked printing material or digital medium",\n'
        '  "visual_style_description": "Detailed description of the visual layout, typography, main colors, contrast, composition style",\n'
        '  "suggested_query": "Optimized English search query combining artistic and visual context for accurate RAG retrieval of design rules",\n'
        '  "confidence": "high / medium / low",\n'
        '  "notes": "Any special observations"\n'
        "}"
    )
    
    agent = get_agent()
    result = agent.qwen_agent.analyze(
        image_bytes=image_bytes,
        system_prompt=system_prompt,
        instruction=instruction,
        mime_type=mime_type
    )
    return result

def run_antigraviti_phase_2b(
    image_bytes: bytes,
    context: dict,
    mime_type: str = "image/jpeg",
    lang: str = "vi"
) -> dict:
    """
    Chạy Phase 2B: Truy vấn RAG và chạy phân tích pass 2 để đánh giá độ phù hợp và điểm xung đột
    """
    agent = get_agent()
    suggested_q = context.get("suggested_query")
    if suggested_q:
        query_str = suggested_q
    else:
        keywords = [
            context.get("thoi_gian"),
            context.get("dia_diem"),
            context.get("van_hoa"),
            context.get("art_style")
        ]
        query_str = ", ".join([str(k) for k in keywords if k])
    
    rag_rules = []
    if query_str.strip():
        print(f"[Antigraviti RAG] Tìm kiếm với từ khóa: {query_str}")
        try:
            rag_rules = agent.retriever.retrieve(query_str)
        except Exception as e:
            print(f"[Antigraviti RAG] Lỗi truy vấn RAG: {e}")
    
    rag_results_text = ""
    if rag_rules:
        for idx, rule in enumerate(rag_rules[:5]):
            title = rule.get("rule_title", "Quy tắc thiết kế")
            text = rule.get("text", "")
            rag_results_text += f"[{idx+1}] {title}:\n{text}\n\n"
    else:
        rag_results_text = "No reference documents found in the knowledge base."

    lang_req_sp = "Answer in Vietnamese." if lang == "vi" else "CRITICAL: You MUST answer entirely in English. ABSOLUTELY NO VIETNAMESE."
    system_prompt = (
        "You are a senior design critic. Re-analyze this design image and produce a refined, enriched analysis across 8 dimensions. "
        "Flag any CONFLICTS between the design's visual language and its stated/detected context. "
        "Rate contextual coherence on a scale of 1-10 for each dimension.\n\n"
        f"{lang_req_sp}\n\n"
        "Analyze strictly across these 8 dimensions:\n"
        "1. Time (thoi_gian)\n"
        "2. Location (dia_diem)\n"
        "3. History & Society (lich_su_xa_hoi)\n"
        "4. Economy (kinh_te)\n"
        "5. Culture (van_hoa)\n"
        "6. Art Style (art_style)\n"
        "7. Ratio (ty_le)\n"
        "8. Material (chat_lieu)\n"
    )
    
    instruction = (
        f"Given the following context retrieved from our design knowledge base:\n"
        f"=== RAG REFERENCES ===\n"
        f"{rag_results_text}\n"
        f"======================\n\n"
        f"And the current design context:\n"
        f"- Time: {context.get('thoi_gian')}\n"
        f"- Location: {context.get('dia_diem')}\n"
        f"- History & Society: {context.get('lich_su_xa_hoi')}\n"
        f"- Economy: {context.get('kinh_te')}\n"
        f"- Culture: {context.get('van_hoa')}\n"
        f"- Art Style: {context.get('art_style')}\n"
        f"- Ratio: {context.get('ty_le')}\n"
        f"- Material: {context.get('chat_lieu')}\n\n"
        f"Re-analyze the design image. Return ONLY valid JSON with these exact keys:\n"
        "{\n"
        '  "thoi_gian": {"analysis": "Analysis string...", "score": 8},\n'
        '  "dia_diem": {"analysis": "Analysis string...", "score": 7},\n'
        '  "lich_su_xa_hoi": {"analysis": "Analysis string...", "score": 9},\n'
        '  "kinh_te": {"analysis": "Analysis string...", "score": 8},\n'
        '  "van_hoa": {"analysis": "Analysis string...", "score": 8},\n'
        '  "art_style": {"analysis": "Analysis string...", "score": 9},\n'
        '  "ty_le": {"analysis": "Analysis string...", "score": 8},\n'
        '  "chat_lieu": {"analysis": "Analysis string...", "score": 7},\n'
        '  "conflicts": [\n'
        '     "Conflict 1 description if any",\n'
        '     "Conflict 2 description if any"\n'
        '  ],\n'
        '  "coherence_total": 8.2\n'
        "}\n\n"
        "Note:\n"
        f"- CRITICAL INSTRUCTION: You MUST write the 'analysis' fields and 'conflicts' strings entirely in {'Vietnamese (Tiếng Việt)' if lang == 'vi' else 'English. Do NOT use Vietnamese under any circumstances, even if the RAG references or JSON keys are in Vietnamese'}.\n"
        "- Each score must be an integer between 1 and 10.\n"
        "- coherence_total is the overall coherence score (float between 1.0 and 10.0).\n"
        "- If there are no conflicts, conflicts must be an empty list []."
    )
    
    result = agent.qwen_agent.analyze(
        image_bytes=image_bytes,
        system_prompt=system_prompt,
        instruction=instruction,
        mime_type=mime_type
    )
    
    result["rag_references"] = [r.get("text", "") for r in rag_rules[:5]]
    return result

def format_coherence_stars(score: int) -> str:
    stars_count = round(score / 2)
    return "★" * stars_count + "☆" * (5 - stars_count)

def format_antigraviti_report(analysis_result: dict, lang: str = "vi") -> str:
    """
    Format context analysis results in Phase 2 layout with localized strings
    """
    if lang == "vi":
        keys_map = {
            "thoi_gian": ("⏱️ THỜI GIAN / LỊCH SỬ", "Thời gian"),
            "dia_diem": ("📍 ĐỊA ĐIỂM / ĐỊA LÝ", "Địa điểm"),
            "lich_su_xa_hoi": ("🏛️ BỐI CẢNH LỊCH SỬ & XÃ HỘI", "Lịch sử & Xã hội"),
            "kinh_te": ("💰 PHÂN KHÚC KINH TẾ", "Kinh tế"),
            "van_hoa": ("🎨 BỐI CẢNH VĂN HÓA", "Văn hóa"),
            "art_style": ("🖌️ PHONG CÁCH NGHỆ THUẬT", "Phong cách nghệ thuật"),
            "ty_le": ("📐 TỶ LỆ & BỐ CỤC", "Tỷ lệ"),
            "chat_lieu": ("🧱 CHẤT LIỆU & PHƯƠNG TIỆN", "Chất liệu")
        }
        report = (
            "═══════════════════════════════════════════════\n"
            "🔍 PHÂN TÍCH BỐI CẢNH THIẾT KẾ\n"
            "═══════════════════════════════════════════════\n\n"
        )
    else:
        keys_map = {
            "thoi_gian": ("⏱️ TIME / HISTORICAL PERIOD", "Time"),
            "dia_diem": ("📍 LOCATION / GEOGRAPHIC CONTEXT", "Location"),
            "lich_su_xa_hoi": ("🏛️ HISTORICAL & SOCIAL CONTEXT", "History & Society"),
            "kinh_te": ("💰 ECONOMIC SEGMENT", "Economy"),
            "van_hoa": ("🎨 CULTURAL CONTEXT", "Culture"),
            "art_style": ("🖌️ ART STYLE", "Art Style"),
            "ty_le": ("📐 ASPECT RATIO & COMPOSITION", "Ratio"),
            "chat_lieu": ("🧱 MATERIAL & MEDIUM", "Material")
        }
        report = (
            "═══════════════════════════════════════════════\n"
            "🔍 DESIGN CONTEXT ANALYSIS\n"
            "═══════════════════════════════════════════════\n\n"
        )
    
    for key, (label, friendly_name) in keys_map.items():
        data = analysis_result.get(key, {})
        if isinstance(data, dict):
            analysis = data.get("analysis", "No analysis data available.")
            score = data.get("score", 0)
        else:
            analysis = str(data)
            score = 0
            
        report += f"{label}\n"
        report += f"➤ {analysis}\n\n"
        
    report += "───────────────────────────────────────────────\n"
    conflicts = analysis_result.get("conflicts", [])
    if conflicts and isinstance(conflicts, list):
        report += "⚠️ CÁC ĐIỂM XUNG ĐỘT:\n" if lang == "vi" else "⚠️ CONFLICTS (if any):\n"
        for conflict in conflicts:
            report += f"- {conflict}\n"
    else:
        report += "⚠️ CÁC ĐIỂM XUNG ĐỘT: Không phát hiện xung đột đáng kể.\n" if lang == "vi" else "⚠️ CONFLICTS (if any): No significant conflicts detected.\n"
        
    report += "───────────────────────────────────────────────\n\n"
    if lang == "vi":
        report += "✅ Mô tả bối cảnh này đã chính xác chưa?\n"
        report += "→ Trả lời **\"OK\"** để nhận đánh giá chi tiết thiết kế dựa trên bối cảnh này.\n"
        report += "→ Trả lời **\"Sửa: [chi tiết]\"** để điều chỉnh lại bối cảnh."
    else:
        report += "✅ Is this context description accurate?\n"
        report += "→ Reply **\"OK\"** to receive feedback on the artwork based on the context above.\n"
        report += "→ Reply **\"Edit: [details]\"** to modify the context."
    
    return report

def parse_persona(raw: Optional[str]) -> Optional[dict]:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if data.get("schemaVersion") != 1:
            return None
        return data
    except json.JSONDecodeError:
        return None


def _parse_box_2d_form(box_2d: Optional[str]) -> Optional[List[int]]:
    if not box_2d or not str(box_2d).strip():
        return None
    try:
        parsed = json.loads(box_2d)
        if isinstance(parsed, list) and len(parsed) == 4:
            return [int(float(v)) for v in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def _box_to_pixel_xyxy(
    box: Optional[List[int]],
    img_w: int,
    img_h: int,
    *,
    err: Optional[dict] = None,
    ref_w: Optional[int] = None,
    ref_h: Optional[int] = None,
    coord_space: Optional[str] = None,
    force_pixel: bool = False,
) -> Optional[List[int]]:
    if box is None and err is not None:
        combined = f"{err.get('issue') or ''} {err.get('suggestion') or ''} {err.get('r') or ''}"
        return resolve_best_box_pixel(err, combined, img_w, img_h)
    if box is None or len(box) != 4:
        return None
    cs = coord_space or ""
    treat_as_pixel = force_pixel or cs in (COORD_FRAME_PIXEL, COORD_SOURCE_PIXEL)
    if not treat_as_pixel and not is_qwen_grid_1000(box, coord_space=cs, img_w=img_w, img_h=img_h):
        treat_as_pixel = True
    if not treat_as_pixel:
        pixel = grid_to_pixel_xyxy(box, img_w, img_h)
        if pixel is not None:
            return pixel
    rw = ref_w if ref_w and ref_w > 0 else img_w
    rh = ref_h if ref_h and ref_h > 0 else img_h
    if rw != img_w or rh != img_h:
        sx = img_w / rw
        sy = img_h / rh
        box = [
            int(box[0] * sx),
            int(box[1] * sy),
            int(box[2] * sx),
            int(box[3] * sy),
        ]
    return clamp_pixel_xyxy(box[0], box[1], box[2], box[3], img_w, img_h)


def _sync_chat_history(key: str, chat_history: Optional[str]) -> None:
    """Đồng bộ lịch sử chat từ BE (DB) vào memory_store khi thiếu."""
    if not chat_history:
        return
    try:
        payload = json.loads(chat_history)
        if not isinstance(payload, list):
            return
        turns: List[Tuple[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            text = str(item.get("text") or item.get("content") or "").strip()
            if role in {"user", "assistant"} and text:
                turns.append((role, text))
        if turns:
            memory_store.sync_turns_from_history(key, turns)
    except Exception as e:
        print(f"[chat-history] sync skip: {e}")


def _errors_context_from_result(last_result: Optional[dict], lang: str) -> str:
    if not last_result or not isinstance(last_result, dict):
        return _t(lang, "Chưa có phân tích lỗi thiết kế nào.", "No design critique yet.")
    errs = last_result.get("e", [])
    if not errs:
        return _t(lang, "Chưa có phân tích lỗi thiết kế nào.", "No design critique yet.")
    if lang == "vi":
        return json.dumps(
            [{"Lỗi số": i + 1, "Vấn đề": e.get("issue") or e.get("r"), "Gợi ý sửa": e.get("suggestion")}
             for i, e in enumerate(errs)],
            ensure_ascii=False,
        )
    return json.dumps(
        [{"Error #": i + 1, "Issue": e.get("issue") or e.get("r"), "Suggestion": e.get("suggestion")}
         for i, e in enumerate(errs)],
        ensure_ascii=False,
    )


def _build_feedback_chat_system_prompt(
    actual_lang: str,
    *,
    rules_context: str = "",
    errors_context_str: str = "",
) -> str:
    prompt = (
        "You are WillaAI, a senior graphic design assistant developed by the Ewill team.\n"
        "You help users review and optimize their designs based on official design rules.\n"
        f"{localized_router_instruction(actual_lang)}\n"
        f"{conversation_continuity_instruction(actual_lang)}\n\n"
    )
    if errors_context_str:
        prompt += f"=== DETECTED DESIGN ERRORS ===\n{errors_context_str}\n\n"
    if rules_context:
        prompt += f"=== RELEVANT DESIGN RULES ===\n{rules_context}\n\n"
    return prompt



@app.post("/chat")
async def unified_chat(
    file: Optional[UploadFile] = File(None),
    message: Optional[str] = Form(""),
    session_id: Optional[str] = Form(""),
    action_type: Optional[str] = Form(""), # e.g. "zoom"
    error_index: Optional[int] = Form(None),
    box_2d: Optional[str] = Form("[]"),
    persona_context: Optional[str] = Form(None),
    lang: Optional[str] = Form(None),
    reply_lang: Optional[str] = Form(None),
    chat_history: Optional[str] = Form(None),
):
    """
    Cổng API hợp nhất (Unified endpoint) thay thế cho /analyze, /chat và /zoom.
    Tự động route dựa trên payload gửi lên.
    """
    key = session_id.strip() if session_id else "anonymous"
    msg = message.strip() if message else ""
    action = action_type.strip().lower() if action_type else ""
    _sync_chat_history(key, chat_history)
    actual_lang = resolve_reply_lang(key, lang or reply_lang, memory_store, user_message=msg)

    persona_dict = parse_persona(persona_context)
    if persona_dict:
        patterns = persona_dict.get("designPatterns", {})
        recent_count = patterns.get("recentAnalysisCount", 0)
        cats = len(patterns.get("topIssueCategories", []))
        print(f"[Persona] Loaded persona context: recentAnalysisCount={recent_count}, categoriesCount={cats}")

    try:
        # -------------------------------------------------------------------
        # LUỒNG 1: ZOOM CỨNG TỪ NÚT BẤM GIAO DIỆN (UI BUTTON CLICK)
        # -------------------------------------------------------------------
        if action == "zoom" or error_index is not None:
            last = memory_store.get_last_analysis(key)
            if not last:
                raise HTTPException(status_code=404, detail="Need to analyze the image before zooming.")
            image_bytes, last_result = last

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_w, img_h = img.size
            isz = (last_result or {}).get("isz") or {}
            ref_w = int(isz.get("w") or img_w)
            ref_h = int(isz.get("h") or img_h)

            coord_space = (last_result or {}).get("coord_space") or COORD_FRAME_PIXEL

            err = None
            if error_index is not None:
                errors = (last_result or {}).get("e", [])
                if 0 <= error_index < len(errors):
                    err = errors[error_index]

            box = _parse_box_2d_form(box_2d)
            if box is None and err is not None:
                for key in ("c", "box_2d"):
                    raw = err.get(key)
                    if isinstance(raw, list) and len(raw) == 4:
                        try:
                            box = [int(float(v)) for v in raw]
                            break
                        except (TypeError, ValueError):
                            box = None

            pixel_box = None
            if box is not None:
                pixel_box = _box_to_pixel_xyxy(
                    box,
                    img_w,
                    img_h,
                    ref_w=ref_w,
                    ref_h=ref_h,
                    coord_space=coord_space,
                    force_pixel=True,
                )
            if not pixel_box and err is not None:
                raw_grid = err.get("c_grid")
                if isinstance(raw_grid, list) and len(raw_grid) == 4:
                    try:
                        g = [int(float(v)) for v in raw_grid]
                        pixel_box = grid_to_pixel_xyxy(g, img_w, img_h)
                    except (TypeError, ValueError):
                        pixel_box = None
            if not pixel_box and err is not None:
                combined = f"{err.get('issue') or ''} {err.get('suggestion') or ''} {err.get('r') or ''}"
                pixel_box = resolve_best_box_pixel(err, combined, img_w, img_h)
            if not pixel_box:
                raise HTTPException(status_code=400, detail="Zoom coordinate error.")

            left, top, right, bottom = (
                min(pixel_box[0], pixel_box[2]),
                min(pixel_box[1], pixel_box[3]),
                max(pixel_box[0], pixel_box[2]),
                max(pixel_box[1], pixel_box[3]),
            )
            pad = 40
            cx1 = max(0, left - pad)
            cy1 = max(0, top - pad)
            cx2 = min(img.width, right + pad)
            cy2 = min(img.height, bottom + pad)
            if cx2 <= cx1 or cy2 <= cy1:
                raise HTTPException(status_code=400, detail="Zoom coordinate error.")
            crop = img.crop((cx1, cy1, cx2, cy2))

            draw = ImageDraw.Draw(crop)
            rx1 = max(0, left - cx1)
            ry1 = max(0, top - cy1)
            rx2 = min(crop.width, right - cx1)
            ry2 = min(crop.height, bottom - cy1)
            if rx2 > rx1 and ry2 > ry1:
                draw.rectangle([rx1, ry1, rx2, ry2], outline=(255, 77, 109), width=4)
            
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
            
            return {
                "type": "zoom",
                "reply": _t(actual_lang, "Đây là vùng lỗi chi tiết:", "Here is the detailed error region:"),
                "image_data_url": b64
            }

        # -------------------------------------------------------------------
        # LUỒNG: ANTIGRAVITI STATE MACHINE & PHÂN TÍCH THIẾT KẾ 3 PHA
        # -------------------------------------------------------------------
        phase, image_bytes, context, rag_results, coherence_scores, conflicts, coherence_total = memory_store.get_antigraviti_state(key)

        # Nếu có file upload mới -> reset state, đặt phase = 0, lưu ảnh
        if file is not None and file.filename:
            img_data = await file.read()
            if len(img_data) > 0:
                try:
                    img = Image.open(io.BytesIO(img_data))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    MAX_SIZE = 1536
                    if img.width > MAX_SIZE or img.height > MAX_SIZE:
                        img.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
                        out_buf = io.BytesIO()
                        img.save(out_buf, format="JPEG", quality=85)
                        img_data = out_buf.getvalue()
                        print(f"[Backend] Đã scale ảnh xuống ({img.width}x{img.height}).")
                except Exception as e:
                    print(f"[Backend] Lỗi xử lý/scale ảnh: {e}")
                
                cls_res = classify_image_type(img_data)
                if cls_res.get("type") != "design" or cls_res.get("confidence", 0.0) <= 0.70:
                    if actual_lang == "vi":
                        msg = "Đây là ảnh không phải thiết kế."
                    else:
                        msg = "This is a photo, not a design."
                    return {
                        "type": "chat",
                        "reply": msg,
                        "e": [],
                        "markdown_report": msg
                    }

                # -----------------------------------------------------------
                # LUỒNG PHÂN TÍCH VÀ FEEDBACK NGAY LẬP TỨC
                # Chạy thẳng Phase 3 critique (không chạy Phase 2A/2B ngầm).
                # -----------------------------------------------------------
                query_str = "graphic design poster advertisement"
                print(f"[Upload] Đang chạy phân tích trực quan ban đầu bằng luồng Willa Multi-Agent với query: '{query_str}'...")
                agent = get_agent()
                
                # Chạy Multi-Agent UX Audit thay cho Single Agent cũ
                audit_result = agent.run_ux_audit(img_data, lang=actual_lang, persona_context=persona_dict)
                
                # Chuyển đổi kết quả sang format (legacy_result) để tương thích UI Chat
                legacy_errors = []
                for idx, err in enumerate(audit_result.get("errors", [])):
                    grid_box = err.get("c", [0, 0, 0, 0])
                    pixel_box = grid_to_pixel_xyxy(grid_box, img.width, img.height)
                    if not pixel_box:
                        x1 = int(grid_box[0] / 1000.0 * img.width)
                        y1 = int(grid_box[1] / 1000.0 * img.height)
                        x2 = int(grid_box[2] / 1000.0 * img.width)
                        y2 = int(grid_box[3] / 1000.0 * img.height)
                        pixel_box = [x1, y1, x2, y2]
                    legacy_errors.append({
                        "c": pixel_box,
                        "c_grid": grid_box,
                        "r": err.get("r", ""),
                        "s": err.get("s", "minor"),
                        "g": err.get("g", "general"),
                        "id": idx,
                        "issue": err.get("issue", ""),
                        "suggestion": err.get("suggestion", ""),
                        "reference": err.get("reference")
                    })
                    
                result = {
                    "e": legacy_errors,
                    "te": len(legacy_errors),
                    "isz": {"w": img.width, "h": img.height},
                    "coord_space": COORD_FRAME_PIXEL,
                    "ss": {
                        "minor": sum(1 for e in legacy_errors if e["s"] == "minor"),
                        "major": sum(1 for e in legacy_errors if e["s"] == "major"),
                        "critical": sum(1 for e in legacy_errors if e["s"] == "critical")
                    },
                    "compliments": audit_result.get("compliments", []),
                    "errors": audit_result.get("errors", []),
                    "detected_elements": audit_result.get("detected_elements", []),
                    "markdown_report": audit_result.get("markdown_report", ""),
                    "details": audit_result.get("details", [])
                }
                
                if "e" in result and isinstance(result["e"], list):
                    severity_weight = {"critical": 3, "major": 2, "minor": 1}
                    result["e"].sort(key=lambda x: severity_weight.get(x.get("s", "minor"), 0), reverse=True)
                try:
                    img_for_size = Image.open(io.BytesIO(img_data))
                    result["analyzed_size"] = [img_for_size.width, img_for_size.height]
                except Exception:
                    pass

                # Lưu tất cả vào memory (Phase 3 result)
                memory_store.add_query(key, query_str)
                memory_store.set_last_analysis(key, img_data, result)
                # Đặt phase = 0 (luồng chat tự do ban đầu, đã có feedback)
                memory_store.set_antigraviti_state(
                    key,
                    phase=0,
                    image=img_data,
                    context={k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]},
                    rag_results=[],
                    coherence_scores={},
                    conflicts=[],
                    coherence_total=0.0
                )

                try:
                    out_path = Path(__file__).parent / "latest_result.json"
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=4)
                except Exception:
                    pass

                # Hiển thị feedback đầy đủ (một ngôn ngữ theo UI)
                final_reply = format_initial_analysis_reply(result, actual_lang)
                memory_store.add_turn(key, "assistant", final_reply)
                return {
                    "type": "analysis",
                    "reply": final_reply,
                    "has_analysis": True,
                    "analysis_data": result,
                    "usage": {
                        "input_tokens": result.get("inputtoken", 0),
                        "output_tokens": result.get("outputtoken", 0),
                        "total_tokens": result.get("totaltoken", 0)
                    }
                }
                
        # Retrieve image bytes and latest analysis from memory
        last = memory_store.get_last_analysis(key)
        if last:
            last_image_bytes, last_result = last
            image_bytes = image_bytes or last_image_bytes
        else:
            last_result = None

        if image_bytes:
            if not msg:
                # Có ảnh nhưng chưa có tin nhắn
                reply = _t(
                    actual_lang,
                    "Vui lòng mô tả bối cảnh thiết kế, hoặc gõ \"Tôi không biết\" để tiếp tục.",
                    "Please share details about your design context, or type 'I don't know' to proceed.",
                )
                memory_store.add_turn(key, "assistant", reply)
                return {"type": "chat", "reply": reply}
            
            # -------------------------------------------------------------------
            # 1. PHÁT HIỆN TỪ KHÓA KÍCH HOẠT BỐI CẢNH (RUBIC)
            # -------------------------------------------------------------------
            _context_keywords = [
                # Vietnamese
                "bối cảnh", "rubic", "khung bối cảnh", "bối cảnh thiết kế", 
                "ngữ cảnh", "chiều bối cảnh", "phân tích bối cảnh", 
                "đánh giá bối cảnh", "yếu tố bối cảnh", "môi trường thiết kế", 
                "hoàn cảnh", "bối cảnh văn hóa", "bối cảnh nghệ thuật", 
                "phong cách nghệ thuật", "đặc tính bối cảnh", "rubic bối cảnh",
                # English
                "context", "design context", "context framework", "contextual", 
                "context analysis", "cultural context", "historical context", 
                "art style context", "design constraints", "target context", 
                "context critique", "rubic context"
            ]
            _msg_lower = msg.lower().strip()

            # Shortcut: concrete edit command should execute image-to-image directly.
            if looks_like_direct_image_edit_request(_msg_lower):
                print("[Direct Edit Shortcut] Detected concrete image edit request.")
                res = generate_or_edit_image(key, msg, image_bytes)
                if res.get("success"):
                    image_url = res.get("image_url")
                    new_image_bytes = res.get("image_bytes")
                    if new_image_bytes:
                        memory_store.set_last_analysis(key, new_image_bytes, {"e": []})
                    memory_store.set_antigraviti_state(key, phase=0, image=new_image_bytes or image_bytes)
                    reply_with_img = "Done. I updated the image according to your instruction."
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply_with_img)
                    return {
                        "type": "chat",
                        "reply": reply_with_img,
                        "image_data_url": image_url
                    }
                reply_err = f"Image generation error: {res.get('error')}"
                memory_store.add_turn(key, "user", msg)
                memory_store.add_turn(key, "assistant", reply_err)
                return {"type": "chat", "reply": reply_err}
            
            if any(kw in _msg_lower for kw in _context_keywords):
                print("[Antigraviti] Kích hoạt phân tích bối cảnh Rubic theo yêu cầu.")
                memory_store.add_turn(key, "user", msg)
                # Thiết lập phase = 10 để lượt tiếp theo xử lý thu thập bối cảnh
                memory_store.set_antigraviti_state(key, phase=10, image=image_bytes)
                
                if actual_lang == "vi":
                    reply = (
                        "Tuyệt vời! Hãy cùng phân tích độ phù hợp của thiết kế này qua **8 chiều bối cảnh Rubic** nhé! 🎯\n\n"
                        "Bạn có thể chia sẻ thêm một số thông tin về bối cảnh thiết kế không?\n"
                        "*(Ví dụ: thời gian, địa điểm, văn hóa, phong cách nghệ thuật, tệp khách hàng, ấn phẩm in ấn hay kỹ thuật số...)*\n\n"
                        "→ Hoặc trả lời **\"AI tự phát hiện\"** để mình tự động phân tích bối cảnh từ ảnh của bạn!"
                    )
                else:
                    reply = (
                        "Awesome! Let's analyze the suitability of this design using **8 dimensions of Rubic** context! 🎯\n\n"
                        "Could you share some details about your design context?\n"
                        "*(For example: time period, location, cultural context, art style, economic segment, print or digital medium...)*\n\n"
                        "→ Or reply **\"AI detect\"** to let me automatically analyze the context from your image!"
                    )
                memory_store.add_turn(key, "assistant", reply)
                return {
                    "type": "chat",
                    "reply": reply
                }

            # -------------------------------------------------------------------
            # 2. CHẠY BỘ ĐỊNH TUYẾN Ý ĐỊNH ĐỂ KIỂM TRA NHANH CÁC LỆNH (GENERATE / ZOOM)
            # -------------------------------------------------------------------
            turns = memory_store.get_recent_turns(key, limit=12)
            history_messages = [{"role": r, "content": [{"text": t}]} for r, t in turns]
            
            # Kiểm tra nhanh từ khóa RE_ANALYZE
            _reanalyze_kw = [
                "phân tích bối cảnh thiết kế", "phân tích lại bối cảnh", "phân tích bối cảnh",
                "phân tích lại bức ảnh", "phân tích bức ảnh", "phân tích ảnh",
                "ai tự phân tích", "tự phân tích lại", "tự động phân tích lại",
                "quét lại ảnh", "scan lại ảnh", "xem lại bối cảnh", "kiểm tra lại bối cảnh"
            ]
            is_reanalyze_request = any(kw in _msg_lower for kw in _reanalyze_kw)
            
            # Lấy RAG context cho câu chat của người dùng
            rules_context = retrieve_design_rules_context(msg, top_k=3)

            # Chuẩn bị system prompt intent
            pending_gen_prompt = memory_store.get_pending_generation_prompt(key)
            errors_context_str = _errors_context_from_result(last_result, actual_lang)

            reply_field_hint = (
                "Phản hồi chat bằng tiếng Việt, hoặc xác nhận/làm rõ hành động."
                if actual_lang == "vi"
                else "English response for normal chat, or a confirmation request/clarification for actions."
            )

            system_prompt_intent = (
                "You are the routing and cognitive control system of a senior design critique AI assistant named WillaAI.\n"
                "Analyze the user's message, current state, design context, and visual errors to determine the user's intent with extreme accuracy.\n\n"
                "=== SYSTEM ROLES & INFORMATION ===\n"
                "WillaAI is a project developed by the Ewill team, focusing on design feedback solutions to help users analyze errors, identify areas for improvement, and optimize designs more clearly and quickly.\n"
                "If asked about yourself or your developer, you MUST use the exact phrase above.\n"
                f"{localized_router_instruction(actual_lang)}\n"
                f"{conversation_continuity_instruction(actual_lang)}\n\n"
                "=== RELEVANT DESIGN RULES ===\n"
                f"{rules_context if rules_context else 'No design rules fetched yet.'}\n\n"
                "=== CURRENT SESSION STATE ===\n"
                f"- Current Phase: {phase} (Phase 2 means waiting for context confirmation/feedback/modification. Phase 0 means freeform chat/post-confirmation)\n"
                f"- Design Context (Current design context): {json.dumps(context, ensure_ascii=False) if context else 'None'}\n"
                f"- Pending Image Generation Prompt: '{pending_gen_prompt if pending_gen_prompt else 'None'}'\n"
                f"- Existing Visual Errors detected: {errors_context_str}\n\n"
                "=== INTENTS EXPLANATION ===\n"
                "Classify the user's message into one of the following exact INTENT keys:\n"
                "1. AGREE: Use when the user agrees, confirms, says 'OK', 'Agree', 'Yes', 'Continue', or confirms to proceed with the context. "
                "   (Note: If 'Pending Image Generation Prompt' is not None, saying 'OK' or agreeing means they want to proceed with image generation, so set 'is_confirming_generation' to true).\n"
                "2. MODIFY_CONTEXT: Use ONLY when the user wants to change, edit, correct, or modify the abstract metadata parameters/context of the critique (specifically: time period/era, location/geographical setting, history/society background, economic purpose, culture, art style, aspect ratio, print/digital material medium) — for example 'modify context to...', 'edit: time is...', 'đổi bối cảnh sang...'. Under NO circumstances should this intent be selected if the user asks to change, edit, replace, or redraw actual text, words, colors, shapes, layers, or visual details within the image itself (which belongs to GENERATE_IMAGE).\n"
                "3. RE_ANALYZE: Use when the user asks to re-analyze or re-examine the design CONTEXT from the image — regardless of whether they say 'AI' or not. This includes: 'analyze design context', 're-analyze context', 'analyze context', 're-analyze the image', 'analyze image', 'AI auto analyze', 'scan image', 'check context'. The AI will re-run its own vision analysis (Phase 2A+2B) and show a context report — then wait for user to confirm OK before continuing.\n"
                "4. REQUEST_FEEDBACK: Use ONLY when the user asks for a general design critique/review/feedback about the visual quality, style, or errors — NOT about context re-analysis (e.g., 're-critique design', 'feedback again', 'overall review', 'review my design'). This will prompt the user to supply context before re-analysis.\n"
                "5. GENERATE_IMAGE: Use when the user wants to generate/create a new image, draw an image, or edit/modify the existing image using image-to-image/inpaint (e.g., 'create new image', 'draw new', 'edit this image', 'generate new image', 'redraw as...', 'sửa ảnh', 'vẽ lại', 'thay đổi chi tiết', 'đổi chữ X thành Y', 'thay chữ X thành Y', 'inpaint', 'sửa chữ', 'thay chữ', 'chèn thêm chữ', 'xóa chữ', 'xóa bớt', 'thêm hình'). This includes ANY requests to edit the text or words written inside the design itself (e.g., 'đổi chữ việt đồng tâm thành Việt Nam' means they want to edit the text on the image, which is a GENERATE_IMAGE intent).\n"
                "6. ZOOM: Use when the user wants to zoom in, crop, or focus on a specific region or error (e.g., 'zoom error #1', 'zoom in on crown', 'crop text').\n"
                "7. CHAT: Use for general chat, questions, chit-chat, or comments that do not match the specific actions above.\n\n"
                "=== EXTRACTION RULES ===\n"
                "- If intent is MODIFY_CONTEXT:\n"
                "  - Extract any context parameters they explicitly provided in their message into the 'extracted_context' object. Leave other fields null.\n"
                "- If intent is GENERATE_IMAGE:\n"
                "  - Create a highly detailed, professional English image generation/modification prompt in 'generate_image_prompt'.\n"
                "  - If there is an original image, write delta changes (e.g., 'Modify the top right section to add a banner, keeping other elements unchanged'). If drawing a brand new image from scratch, describe the full scene.\n"
                "- If intent is ZOOM:\n"
                "  - If they mention a specific error number (e.g., 'error #2'), extract the 0-indexed index (e.g., 1) in 'zoom_target.error_index'.\n"
                "  - If they mention a text description (e.g., 'text at the bottom'), extract it in 'zoom_target.description'.\n\n"
                "=== OUTPUT FORMAT ===\n"
                "You MUST return ONLY valid JSON matching this schema (do not include any markdown block other than raw JSON content):\n"
                "{\n"
                '  "intent": "AGREE" | "MODIFY_CONTEXT" | "RE_ANALYZE" | "REQUEST_FEEDBACK" | "GENERATE_IMAGE" | "ZOOM" | "CHAT",\n'
                '  "reasoning": "...",\n'
                '  "is_confirming_generation": true | false,\n'
                '  "extracted_context": {\n'
                '    "thoi_gian": null | "...",\n'
                '    "dia_diem": null | "...",\n'
                '    "lich_su_xa_hoi": null | "...",\n'
                '    "kinh_te": null | "...",\n'
                '    "van_hoa": null | "...",\n'
                '    "art_style": null | "...",\n'
                '    "ty_le": null | "...",\n'
                '    "chat_lieu": null | "..."\n'
                '  },\n'
                '  "generate_image_prompt": null,\n'
                '  "zoom_target": {\n'
                '    "error_index": null,\n'
                '    "description": null\n'
                '  },\n'
                f'  "reply": "{reply_field_hint}"\n'
                "}"
            )

            if is_reanalyze_request:
                intent = "RE_ANALYZE"
                payload = {"intent": "RE_ANALYZE"}
            else:
                agent = get_agent()
                payload = agent.qwen_agent.chat_json(
                    system_prompt=system_prompt_intent,
                    user_text=msg,
                    history_messages=history_messages
                )
                intent = payload.get("intent", "CHAT")
            
            reply = str(payload.get("reply", "")).strip() if not is_reanalyze_request else ""
            is_confirming_gen = payload.get("is_confirming_generation", False) if not is_reanalyze_request else False
            pay_usage = payload.get("_usage", {}) if not is_reanalyze_request else {}

            print(f"[Antigraviti Routing] Classified intent={intent}, phase={phase}")

            # -------------------------------------------------------------------
            # A. PHẢN HỒI Ý ĐỊNH GENERATE_IMAGE (LẬP TỨC THỰC THI KHÔNG CẦN DUYỆT)
            # -------------------------------------------------------------------
            if intent == "GENERATE_IMAGE" and (payload.get("generate_image_prompt") or _msg_lower):
                gen_prompt = payload.get("generate_image_prompt") or msg
                print(f"[Generate Image] Thực thi lập tức với prompt: '{gen_prompt}'")
                
                # Gọi hàm sinh/sửa ảnh
                res = generate_or_edit_image(key, gen_prompt, image_bytes)
                if res.get("success"):
                    image_url = res.get("image_url")
                    new_image_bytes = res.get("image_bytes")
                    if new_image_bytes:
                        memory_store.set_last_analysis(key, new_image_bytes, {"e": []})
                    
                    # Reset phase về 0 vì đã hoàn thành yêu cầu vẽ/sửa ảnh mới
                    memory_store.set_antigraviti_state(key, phase=0, image=new_image_bytes or image_bytes)
                    
                    reply_with_img = reply if (reply and reply != "normal chat" and "generate_image" not in reply.lower()) else f"Mình đã vẽ/sửa xong bức ảnh theo yêu cầu của bạn dựa trên mô tả:\n*{gen_prompt}*"
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply_with_img)
                    return {
                        "type": "chat",
                        "reply": reply_with_img,
                        "image_data_url": image_url,
                        "usage": {
                            "input_tokens": pay_usage.get("input_tokens", 0),
                            "output_tokens": pay_usage.get("output_tokens", 0),
                            "total_tokens": pay_usage.get("total_tokens", 0)
                        }
                    }
                else:
                    reply_err = f"Đã có lỗi khi tạo/sửa ảnh: {res.get('error')}"
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply_err)
                    return {"type": "chat", "reply": reply_err}

            # -------------------------------------------------------------------
            # B. PHẢN HỒI Ý ĐỊNH ZOOM (LẬP TỨC THỰC THI)
            # -------------------------------------------------------------------
            elif intent == "ZOOM":
                print("Xử lý Smart Auto-Zoom bằng LLM...")
                zoom_target = payload.get("zoom_target", {})
                error_index = zoom_target.get("error_index")
                
                box = None
                if error_index is not None and last_result:
                    errors = last_result.get("e", [])
                    if 0 <= error_index < len(errors):
                        err = errors[error_index]
                        box = err.get("box_2d") or err.get("c")
                
                if not box:
                    ctx_str = None
                    if last_result:
                        errs = last_result.get("e", [])
                        if errs:
                            ctx_str = json.dumps([{"i": i, "c": e.get("c"), "r": f"{e.get('issue') or e.get('r') or ''} {e.get('suggestion') or ''}".strip()} for i, e in enumerate(errs[:5])], ensure_ascii=False)
                    
                    try:
                        loc = agent.qwen_agent.locate_box(
                            image_bytes=image_bytes,
                            mime_type="image/jpeg",
                            user_request=msg,
                            context=ctx_str
                        )
                        raw_box_zoom = loc.get("box_2d")
                        if raw_box_zoom and isinstance(raw_box_zoom, list) and len(raw_box_zoom) == 4:
                            ymin_z, xmin_z, ymax_z, xmax_z = raw_box_zoom
                            box = [xmin_z, ymin_z, xmax_z, ymax_z]
                        loc_usage = loc.get("_usage", {})
                        if loc_usage:
                            pay_usage.update(loc_usage)
                    except Exception as e:
                        print(f"Lỗi vision zoom: {e}")
                        
                if isinstance(box, list) and len(box) == 4:
                    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    cs = last_result.get("coord_space") if last_result else ""
                    pixel_box = _box_to_pixel_xyxy(
                        box,
                        img.width,
                        img.height,
                        ref_w=(last_result.get("isz") or {}).get("w") if last_result else img.width,
                        ref_h=(last_result.get("isz") or {}).get("h") if last_result else img.height,
                        coord_space=cs,
                        force_pixel=(cs == COORD_FRAME_PIXEL)
                    )
                    if pixel_box:
                        x1, y1, x2, y2 = pixel_box
                    else:
                        x1 = int(box[0] / 1000.0 * img.width)
                        y1 = int(box[1] / 1000.0 * img.height)
                        x2 = int(box[2] / 1000.0 * img.width)
                        y2 = int(box[3] / 1000.0 * img.height)
                    
                    x1, x2 = min(x1, x2), max(x1, x2)
                    y1, y2 = min(y1, y2), max(y1, y2)
                    x1 = max(0, min(x1, img.width))
                    y1 = max(0, min(y1, img.height))
                    x2 = max(0, min(x2, img.width))
                    y2 = max(0, min(y2, img.height))
                    
                    pad = 40
                    cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
                    cx2, cy2 = min(img.width, x2 + pad), min(img.height, y2 + pad)
                    crop = img.crop((cx1, cy1, cx2, cy2))
                    draw = ImageDraw.Draw(crop)
                    draw.rectangle([x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1], outline=(255, 77, 109), width=4)
                    
                    buf = io.BytesIO()
                    crop.save(buf, format="PNG")
                    b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
                    
                    if not reply or reply == "normal chat":
                        reply = "Đây là khu vực thiết kế chi tiết mà bạn muốn phóng to:" if actual_lang == 'vi' else "Here is the detailed design area you requested to zoom in on:"
                        
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply)
                    return {
                        "type": "zoom",
                        "reply": reply,
                        "image_data_url": b64,
                        "usage": {
                            "input_tokens": pay_usage.get("input_tokens", 0),
                            "output_tokens": pay_usage.get("output_tokens", 0),
                            "total_tokens": pay_usage.get("total_tokens", 0)
                        }
                    }
                else:
                    reply = "Xin lỗi, tôi không thể xác định được khu vực bạn muốn phóng to. Bạn có thể mô tả rõ hơn được không?" if actual_lang == 'vi' else "Sorry, I couldn't identify the area you want to zoom in on. Could you please describe it more clearly?"
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply)
                    return {"type": "chat", "reply": reply}

            # -------------------------------------------------------------------
            # C. ĐANG TRONG PHASE 10 (HỎI BỐI CẢNH)
            # -------------------------------------------------------------------
            elif phase == 10:
                memory_store.add_turn(key, "user", msg)
                _msg_lower_phase = msg.lower().strip()
                
                # Kiểm tra xem user có muốn AI tự phát hiện không
                _ai_detect_keywords = [
                    "ai tự phát hiện", "ai detect", "ai tự", "tự phát hiện",
                    "ai nhận diện", "ai tự nhận", "để ai tự", "cho ai phân tích",
                    "ai tự phân tích", "tự động phân tích", "tự scan", "tự phân tích",
                    "không biết", "không rõ", "chịu", "không biết nha", "don't know", "no", "không"
                ]
                
                if any(kw in _msg_lower_phase for kw in _ai_detect_keywords):
                    print("[Phase-10] User yêu cầu AI tự phát hiện. Đang chạy full Phase 2A + 2B...")
                    try:
                        merged_context = run_antigraviti_phase_2a(image_bytes)
                    except Exception as e:
                        print(f"Lỗi chạy Phase 2A: {e}")
                        merged_context = {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}
                else:
                    user_knows, user_context = extract_user_context(msg)
                    if user_knows:
                        merged_context = {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}
                        for k in merged_context.keys():
                            merged_context[k] = user_context.get(k)
                            
                        missing_fields = [k for k, v in merged_context.items() if not v]
                        if missing_fields:
                            print(f"Bối cảnh thiếu các trường: {missing_fields}. Đang chạy Phase 2A để tự động điền khuyết...")
                            try:
                                ai_context = run_antigraviti_phase_2a(image_bytes)
                                for k in missing_fields:
                                    if k in ai_context:
                                        merged_context[k] = ai_context[k]
                            except Exception as e:
                                print(f"Lỗi chạy Phase 2A khi điền khuyết: {e}")
                    else:
                        print("Không trích xuất được bối cảnh, dùng AI tự phát hiện...")
                        try:
                            merged_context = run_antigraviti_phase_2a(image_bytes)
                        except Exception as e:
                            merged_context = {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}

                print("Chạy Phase 2B (RAG Enrichment & Second Pass)...")
                try:
                    analysis_result = run_antigraviti_phase_2b(image_bytes, merged_context)
                except Exception as e:
                    print(f"Lỗi chạy Phase 2B: {e}")
                    analysis_result = {
                        "conflicts": [],
                        "coherence_total": 5.0,
                        "rag_references": []
                    }
                    for k in merged_context.keys():
                        analysis_result[k] = {"analysis": "Unable to analyze the context due to a system error.", "score": 5}

                memory_store.set_antigraviti_state(
                    key,
                    phase=12,
                    image=image_bytes,
                    context=merged_context,
                    rag_results=analysis_result.get("rag_references", []),
                    coherence_scores={k: analysis_result.get(k, {}).get("score", 0) if isinstance(analysis_result.get(k), dict) else 0 for k in merged_context.keys()},
                    conflicts=analysis_result.get("conflicts", []),
                    coherence_total=analysis_result.get("coherence_total", 0.0)
                )

                ctx_keys = ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]
                _display_analysis = {}
                for k in ctx_keys:
                    v = merged_context.get(k)
                    _display_analysis[k] = {"analysis": v if v else "No analysis data available.", "score": analysis_result.get(k, {}).get("score", 5) if isinstance(analysis_result.get(k), dict) else 5}
                _display_analysis["conflicts"] = analysis_result.get("conflicts", [])
                _display_analysis["coherence_total"] = analysis_result.get("coherence_total", 5.0)

                report_text = format_antigraviti_report(_display_analysis, actual_lang)

                if actual_lang == "vi":
                    reply = (
                        "Dưới đây là bối cảnh thiết kế tôi đã thu thập và đối chiếu với hệ thống cơ sở dữ liệu RAG! 🔍\n\n"
                        f"{report_text}"
                    )
                else:
                    reply = (
                        "Here is the design context I captured and cross-referenced with the RAG knowledge base! 🔍\n\n"
                        f"{report_text}"
                    )

                memory_store.add_turn(key, "assistant", reply)
                return {
                    "type": "chat",
                    "reply": reply
                }

            # -------------------------------------------------------------------
            # D. ĐANG TRONG PHASE 12 (XÁC NHẬN BỐI CẢNH)
            # -------------------------------------------------------------------
            elif phase == 12:
                _msg_lower_phase = msg.lower().strip()
                
                # A1: Xác nhận bối cảnh (OK / Đồng ý)
                if check_is_confirm(msg) or _msg_lower_phase in ["ok", "ok nhé", "ok nha", "đồng ý", "tiếp tục"]:
                    memory_store.add_turn(key, "user", msg)
                    print("[Phase-12] User xác nhận bối cảnh. Tiến hành chạy Phase 3 critique...")
                    
                    ag_phase, ag_image, ag_context, ag_rag, ag_scores, ag_conflicts, ag_total = memory_store.get_antigraviti_state(key)
                    ag_image = ag_image or image_bytes
                    ag_context = ag_context or {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}
                    
                    keywords = [
                        ag_context.get("thoi_gian"),
                        ag_context.get("dia_diem"),
                        ag_context.get("van_hoa"),
                        ag_context.get("art_style")
                    ]
                    query_str = ", ".join([str(k) for k in keywords if k]) or "graphic design poster advertisement"
                    print(f"[Phase-12 OK] Đang chạy lại critique với query: '{query_str}'...")
                    
                    agent = get_agent()
                    result = agent.analyze(
                        image_bytes=ag_image,
                        filename="image.jpg",
                        query=query_str,
                        confirmed_context=ag_context,
                        persona_context=persona_dict,
                        lang=actual_lang
                    )
                    
                    if "e" in result and isinstance(result["e"], list):
                        severity_weight = {"critical": 3, "major": 2, "minor": 1}
                        result["e"].sort(key=lambda x: severity_weight.get(x.get("s", "minor"), 0), reverse=True)
                        
                    try:
                        img_for_size = Image.open(io.BytesIO(ag_image))
                        result["analyzed_size"] = [img_for_size.width, img_for_size.height]
                    except Exception:
                        pass
                        
                    memory_store.add_query(key, query_str)
                    memory_store.set_last_analysis(key, ag_image, result)
                    # Reset phase về 0 sau khi hoàn thành
                    memory_store.set_antigraviti_state(key, phase=0, image=ag_image, context=ag_context)
                    
                    agree_reply = format_post_context_analysis_reply(result, actual_lang, deep=True)
                    
                    memory_store.add_turn(key, "assistant", agree_reply)
                    
                    img_b64 = base64.b64encode(ag_image).decode('utf-8')
                    mime = "image/jpeg" if ag_image.startswith(b'\xff\xd8') else "image/png"
                    image_data_url = f"data:{mime};base64,{img_b64}"
                    
                    return {
                        "type": "analysis",
                        "reply": agree_reply,
                        "has_analysis": True,
                        "analysis_data": result,
                        "image_data_url": image_data_url
                    }
                    
                # A2: Yêu cầu điều chỉnh bối cảnh (Chỉnh sửa: [điểm cần sửa] hoặc thô)
                elif "chỉnh sửa" in _msg_lower_phase or "sửa lại" in _msg_lower_phase or "sửa bối cảnh" in _msg_lower_phase or "edit" in _msg_lower_phase or "modify" in _msg_lower_phase:
                    memory_store.add_turn(key, "user", msg)
                    print("[Phase-12] User requested context modification...")
                    
                    ag_phase, ag_image, ag_context, ag_rag, ag_scores, ag_conflicts, ag_total = memory_store.get_antigraviti_state(key)
                    ag_context = ag_context or {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}
                    
                    user_knows, user_context = extract_user_context(msg)
                    if user_knows:
                        for k in ag_context.keys():
                            if user_context.get(k) is not None:
                                ag_context[k] = user_context.get(k)
                                
                    try:
                        analysis_result = run_antigraviti_phase_2b(ag_image, ag_context)
                    except Exception as e:
                        analysis_result = {"conflicts": [], "coherence_total": 5.0, "rag_references": []}
                        
                    memory_store.set_antigraviti_state(
                        key,
                        phase=12,
                        image=ag_image,
                        context=ag_context,
                        rag_results=analysis_result.get("rag_references", []),
                        coherence_scores={k: analysis_result.get(k, {}).get("score", 0) if isinstance(analysis_result.get(k), dict) else 0 for k in ag_context.keys()},
                        conflicts=analysis_result.get("conflicts", []),
                        coherence_total=analysis_result.get("coherence_total", 0.0)
                    )
                    
                    ctx_keys = ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]
                    _display_analysis = {}
                    for k in ctx_keys:
                        v = ag_context.get(k)
                        _display_analysis[k] = {"analysis": v if v else "No analysis data available.", "score": analysis_result.get(k, {}).get("score", 5) if isinstance(analysis_result.get(k), dict) else 5}
                    _display_analysis["conflicts"] = analysis_result.get("conflicts", [])
                    _display_analysis["coherence_total"] = analysis_result.get("coherence_total", 5.0)

                    report_text = format_antigraviti_report(_display_analysis, actual_lang)
                    
                    reply = _t(
                        actual_lang,
                        "Tôi đã điều chỉnh bối cảnh theo yêu cầu của bạn! 🛠️\n\n",
                        "I have adjusted the context according to your request! 🛠️\n\n",
                    ) + report_text
                    memory_store.add_turn(key, "assistant", reply)
                    return {
                        "type": "chat",
                        "reply": reply
                    }

            # -------------------------------------------------------------------
            # E. MÁY TRẠNG THÁI PHASE 0 (CHAT TỰ DO) HOẶC CÁC Ý ĐỊNH KHÁC
            # -------------------------------------------------------------------
            else:
                # 1. Ý định AGREE hoặc CONFIRM GENERATE
                if (is_confirming_gen or intent == "AGREE") and pending_gen_prompt:
                    print(f"Bắt đầu gọi sinh ảnh với prompt: '{pending_gen_prompt}'")
                    res = generate_or_edit_image(key, pending_gen_prompt, image_bytes)
                    memory_store.clear_pending_state(key)
                    if res.get("success"):
                        image_url = res.get("image_url")
                        new_image_bytes = res.get("image_bytes")
                        if new_image_bytes:
                            memory_store.set_last_analysis(key, new_image_bytes, {"e": []})
                        
                        reply_with_img = reply if reply else "I have generated a sample image based on your context."
                        memory_store.add_turn(key, "user", msg)
                        memory_store.add_turn(key, "assistant", reply_with_img)
                        return {
                            "type": "chat",
                            "reply": reply_with_img,
                            "image_data_url": image_url,
                            "usage": {
                                "input_tokens": pay_usage.get("input_tokens", 0),
                                "output_tokens": pay_usage.get("output_tokens", 0),
                                "total_tokens": pay_usage.get("total_tokens", 0)
                            }
                        }
                    else:
                        reply_err = f"Image generation error: {res.get('error')}"
                        memory_store.add_turn(key, "user", msg)
                        memory_store.add_turn(key, "assistant", reply_err)
                        return {"type": "chat", "reply": reply_err}

                elif intent == "AGREE":
                    print("User confirmed the context. Re-running Phase 3 with the new context.")
                    ag_phase, ag_image, ag_context, ag_rag, ag_scores, ag_conflicts, ag_total = memory_store.get_antigraviti_state(key)
                    
                    if ag_image and ag_context:
                        keywords = [
                            ag_context.get("thoi_gian"),
                            ag_context.get("dia_diem"),
                            ag_context.get("van_hoa"),
                            ag_context.get("art_style")
                        ]
                        query_str = ", ".join([str(k) for k in keywords if k]) or "graphic design poster advertisement"
                        print(f"Đang chạy lại critique với query: '{query_str}'...")
                        
                        agent = get_agent()
                        result = agent.analyze(
                            image_bytes=ag_image,
                            filename="image.jpg",
                            query=query_str,
                            confirmed_context=ag_context,
                            persona_context=persona_dict,
                            lang=actual_lang
                        )
                        
                        if "e" in result and isinstance(result["e"], list):
                            severity_weight = {"critical": 3, "major": 2, "minor": 1}
                            result["e"].sort(key=lambda x: severity_weight.get(x.get("s", "minor"), 0), reverse=True)
                            
                        try:
                            img_for_size = Image.open(io.BytesIO(ag_image))
                            result["analyzed_size"] = [img_for_size.width, img_for_size.height]
                        except Exception:
                            pass
                            
                        memory_store.add_query(key, query_str)
                        memory_store.set_last_analysis(key, ag_image, result)
                        memory_store.clear_antigraviti_state(key)
                        
                        agree_reply = format_post_context_analysis_reply(result, actual_lang, deep=False)
                        reply = agree_reply
                        memory_store.add_turn(key, "user", msg)
                        memory_store.add_turn(key, "assistant", reply)
                        
                        img_b64 = base64.b64encode(ag_image).decode('utf-8')
                        mime = "image/jpeg" if ag_image.startswith(b'\xff\xd8') else "image/png"
                        image_data_url = f"data:{mime};base64,{img_b64}"
                        
                        return {
                            "type": "analysis",
                            "reply": reply,
                            "has_analysis": True,
                            "analysis_data": result,
                            "image_data_url": image_data_url
                        }
                    else:
                        stored = memory_store.get_last_analysis(key)
                        memory_store.clear_antigraviti_state(key)
                        if stored:
                            stored_bytes, stored_result = stored
                            agree_reply = format_post_context_analysis_reply(
                                stored_result, actual_lang, stored_only=True
                            )
                            reply = agree_reply
                            memory_store.add_turn(key, "user", msg)
                            memory_store.add_turn(key, "assistant", reply)
                            
                            img_b64 = base64.b64encode(stored_bytes).decode('utf-8')
                            mime = "image/jpeg" if stored_bytes.startswith(b'\xff\xd8') else "image/png"
                            image_data_url = f"data:{mime};base64,{img_b64}"
                            
                            return {
                                "type": "analysis",
                                "reply": reply,
                                "has_analysis": True,
                                "analysis_data": stored_result,
                                "image_data_url": image_data_url
                            }
                        else:
                            reply = ("Tuyệt vời! Bối cảnh đã được xác nhận. Bạn có thể tiếp tục chat để sửa các lỗi thiết kế!") if actual_lang == 'vi' else ("Excellent! Context has been confirmed. You can continue chatting to fix any design errors!")
                            memory_store.add_turn(key, "user", msg)
                            memory_store.add_turn(key, "assistant", reply)
                            return {"type": "chat", "reply": reply}

                # 2. Ý định MODIFY_CONTEXT: Sửa lại bối cảnh
                elif intent == "MODIFY_CONTEXT":
                    ext_ctx = payload.get("extracted_context", {})
                    has_new_details = ext_ctx and any(v is not None for v in ext_ctx.values())
                    
                    if has_new_details:
                        print(f"Cập nhật bối cảnh trực tiếp: {ext_ctx}")
                        if not context:
                            context = {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}
                        merged_context = {}
                        for k in context.keys():
                            merged_context[k] = ext_ctx.get(k) if ext_ctx.get(k) is not None else context.get(k)
                        
                        try:
                            analysis_result = run_antigraviti_phase_2b(image_bytes, merged_context)
                        except Exception as e:
                            print(f"Lỗi Phase 2B: {e}")
                            analysis_result = {"conflicts": [], "coherence_total": 5.0, "rag_references": []}
                        
                        memory_store.set_antigraviti_state(
                            key,
                            phase=2,
                            context=merged_context,
                            rag_results=analysis_result.get("rag_references", []),
                            coherence_scores={k: analysis_result.get(k, {}).get("score", 0) if isinstance(analysis_result.get(k), dict) else 0 for k in merged_context.keys()},
                            conflicts=analysis_result.get("conflicts", []),
                            coherence_total=analysis_result.get("coherence_total", 0.0)
                        )
                        
                        report_text = format_antigraviti_report(analysis_result, actual_lang)
                        reply = (
                            "I have successfully updated the design context! 🛠️\n"
                            "Here is the adjusted context:\n\n"
                            f"{report_text}"
                        )
                        memory_store.add_turn(key, "user", msg)
                        memory_store.add_turn(key, "assistant", reply)
                        return {
                            "type": "chat",
                            "reply": reply
                        }
                    else:
                        print("User requested context modification. Transitioning to context gathering flow...")
                        reply = (
                            "Would you like to modify the design context? 🛠️\n"
                            "Please share the new context information you'd like to target (e.g., time period, location, culture, art style, materials, etc.).\n"
                            "Once I receive this new context information, I will immediately update and re-analyze the design!"
                        )
                        memory_store.set_antigraviti_state(key, phase=10, image=image_bytes)
                        memory_store.add_turn(key, "user", msg)
                        memory_store.add_turn(key, "assistant", reply)
                        return {"type": "chat", "reply": reply}

                # 3. Ý định RE_ANALYZE
                elif intent == "RE_ANALYZE":
                    print("User requested AI context auto-detection. Running Phase 2A + 2B...")
                    try:
                        reanalyzed_context = run_antigraviti_phase_2a(image_bytes)
                    except Exception as e:
                        print(f"[Antigraviti RE_ANALYZE] Lỗi Phase 2A: {e}")
                        reanalyzed_context = {k: None for k in ["thoi_gian", "dia_diem", "lich_su_xa_hoi", "kinh_te", "van_hoa", "art_style", "ty_le", "chat_lieu"]}

                    try:
                        reanalyzed_result = run_antigraviti_phase_2b(image_bytes, reanalyzed_context)
                    except Exception as e:
                        print(f"[Antigraviti RE_ANALYZE] Lỗi Phase 2B: {e}")
                        reanalyzed_result = {"conflicts": [], "coherence_total": 5.0, "rag_references": []}
                        for k in reanalyzed_context.keys():
                            reanalyzed_result[k] = {"analysis": "Unable to analyze the context due to a system error.", "score": 5}

                    memory_store.set_antigraviti_state(
                        key,
                        phase=12,
                        image=image_bytes,
                        context=reanalyzed_context,
                        rag_results=reanalyzed_result.get("rag_references", []),
                        coherence_scores={k: reanalyzed_result.get(k, {}).get("score", 0) if isinstance(reanalyzed_result.get(k), dict) else 0 for k in reanalyzed_context.keys()},
                        conflicts=reanalyzed_result.get("conflicts", []),
                        coherence_total=reanalyzed_result.get("coherence_total", 0.0)
                    )

                    report_text = format_antigraviti_report(reanalyzed_result, actual_lang)
                    reanalyze_reply = (
                        "I have automatically scanned the entire design context from the image! 🔍\n\n"
                        f"{report_text}"
                    )
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reanalyze_reply)
                    return {"type": "chat", "reply": reanalyze_reply}

                # 4. Ý định REQUEST_FEEDBACK
                elif intent == "REQUEST_FEEDBACK":
                    print("User requested re-critique. Transitioning to context gathering flow...")
                    reply = (
                        "To provide the most accurate and suitable design feedback, "
                        "please share the desired context for this artwork (e.g., time period, location, culture, art style, etc.).\n"
                        "Once you provide the context, I will compare it against the knowledge base and give you a fresh, detailed critique!"
                    )
                    memory_store.set_antigraviti_state(key, phase=10, image=image_bytes)
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply)
                    return {"type": "chat", "reply": reply}

                # 7. Ý định CHAT thuần túy — gọi LLM với lịch sử + lỗi thiết kế để nối ngữ cảnh
                else:
                    chat_turns = memory_store.get_recent_turns(key, limit=12)
                    chat_history_messages = [{"role": r, "content": [{"text": t}]} for r, t in chat_turns]
                    chat_rules = retrieve_design_rules_context(msg, top_k=4)
                    chat_system = _build_feedback_chat_system_prompt(
                        actual_lang,
                        rules_context=chat_rules or "",
                        errors_context_str=errors_context_str,
                    )
                    reply, chat_usage = agent.qwen_agent.chat_text(
                        system_prompt=chat_system,
                        user_text=msg,
                        history_messages=chat_history_messages,
                    )
                    if isinstance(chat_usage, dict):
                        pay_usage = {**pay_usage, **chat_usage}
                    memory_store.add_turn(key, "user", msg)
                    memory_store.add_turn(key, "assistant", reply)
                    return {
                        "type": "chat",
                        "reply": reply,
                        "usage": {
                            "input_tokens": pay_usage.get("input_tokens", 0),
                            "output_tokens": pay_usage.get("output_tokens", 0),
                            "total_tokens": pay_usage.get("total_tokens", 0)
                        }
                    }
        else:
            # Không có ảnh trong phiên chat -> Chat thuần túy
            agent = get_agent()
            
            # Lấy lịch sử turns gần nhất để tăng tính nhất quán
            turns = memory_store.get_recent_turns(key, limit=12)
            history_messages = [{"role": r, "content": [{"text": t}]} for r, t in turns]
            
            # Truy vấn RAG cho câu hỏi của người dùng
            rules_context = retrieve_design_rules_context(msg, top_k=4)
            
            system_prompt = _build_feedback_chat_system_prompt(
                actual_lang,
                rules_context=rules_context or "",
            )
                
            reply, pay_usage = agent.qwen_agent.chat_text(
                system_prompt=system_prompt,
                user_text=msg,
                history_messages=history_messages
            )
            memory_store.add_turn(key, "user", msg)
            memory_store.add_turn(key, "assistant", reply)
            return {
                "type": "chat",
                "reply": reply,
                "usage": {
                    "input_tokens": pay_usage.get("input_tokens", 0),
                    "output_tokens": pay_usage.get("output_tokens", 0),
                    "total_tokens": pay_usage.get("total_tokens", 0)
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------------------------
# ENDPOINT: SEED-ANALYSIS – Khôi phục memory_store từ BE (sau restart / session cũ)
# -------------------------------------------------------------------
@app.post("/seed-analysis")
async def seed_analysis(
    session_id: Optional[str] = Form(""),
    analysis_json: Optional[str] = Form("{}"),
    file: UploadFile = File(...),
):
    """
    BE gọi khi memory_store mất (restart AI server) nhưng DB vẫn có kết quả phân tích.
    Không chạy lại pipeline phân tích — chỉ nạp ảnh + JSON lỗi vào RAM.
    """
    key = session_id.strip() if session_id else "anonymous"
    img_data = await file.read()
    if not img_data:
        raise HTTPException(status_code=400, detail="Empty image file.")

    try:
        result = json.loads(analysis_json) if analysis_json else {}
        if not isinstance(result, dict):
            result = {}
    except Exception:
        result = {}

    memory_store.set_last_analysis(key, img_data, result)
    err_count = len((result or {}).get("e") or [])
    print(f"[seed-analysis] session={key} errors={err_count} image_bytes={len(img_data)}")
    return {"ok": True, "session_id": key, "error_count": err_count}


# -------------------------------------------------------------------
# HELPER: Dịch Khuyến nghị Việt -> Chỉ thị English cho AI sinh ảnh
# -------------------------------------------------------------------
def translate_vi_to_en(text: str) -> str:
    """
    Dịch và chuyển đổi Khuyến nghị tiếng Việt của chuyên gia thành chỉ thị hành động tiếng Anh chuyên nghiệp cho AI sinh ảnh.
    """
    try:
        agent = get_agent()
        system_prompt = (
            "You are an expert English-Vietnamese translator and professional graphic designer.\n"
            "Translate the given Vietnamese design edit/suggestion text into clear, concise, action-oriented English instructions suitable for an AI image generator (inpaint/image edits prompt).\n"
            "Rules:\n"
            "- Focus only on the instructions. Do not include any intro, outro, explanations, or conversational filler.\n"
            "- Use active, direct visual verbs (e.g., 'Change...', 'Replace...', 'Decrease opacity of...', 'Add a soft shadow to...', 'Adjust saturation of...').\n"
            "- If the suggestion specifies changing a text string (e.g., 'đổi chữ việt đồng tâm thành Việt Nam'), translate it to a precise text replacement directive (e.g., 'Change the text \"việt đồng tâm\" to \"Việt Nam\"')."
        )
        translated, _ = agent.qwen_agent.chat_text(
            system_prompt=system_prompt,
            user_text=text
        )
        return translated.strip()
    except Exception as e:
        print(f"Error during translation: {e}")
        return text


def retrieve_design_rules_context(query: str, top_k: int = 3) -> str:
    """
    Tìm kiếm các quy tắc thiết kế liên quan từ cơ sở tri thức (RAG)
    và định dạng thành chuỗi văn bản ngữ cảnh để nhúng vào prompt của AI.
    """
    try:
        agent = get_agent()
        rules = agent.retriever.retrieve(query.lower())
        if not rules:
            return ""
        
        context_str = "\n=== RELEVANT DESIGN RULES FROM KNOWLEDGE BASE ===\n"
        for idx, r in enumerate(rules[:top_k]):
            title = r.get("rule_title", "Quy tắc")
            cat = r.get("category", "Chung")
            text = r.get("text", "")
            context_str += f"[{idx+1}] {title} (Category: {cat}):\n{text}\n\n"
        context_str += "=================================================\n"
        return context_str
    except Exception as e:
        print(f"Error retrieving rules context: {e}")
        return ""


# -------------------------------------------------------------------
# ENDPOINT: PREPARE-REGEN – Chuẩn bị preview mask và prompt gợi ý
# -------------------------------------------------------------------
@app.post("/prepare-regen")
async def prepare_regen(
    session_id: Optional[str] = Form(""),
    error_indices: Optional[str] = Form("[]"),  # JSON array string, e.g. "[0,2]"
    replyLang: Optional[str] = Form("auto"),
):
    """
    Bước 1: Nhận danh sách index lỗi muốn fix.
    Trả về:
      - mask_preview_b64: preview ảnh gốc + overlay đỏ vùng lỗi
      - suggested_prompt: prompt gợi ý từ mô tả lỗi
      - error_count: số lỗi được chọn
    """
    key = session_id.strip() if session_id else "anonymous"

    last = memory_store.get_last_analysis(key)
    if not last:
        raise HTTPException(status_code=404, detail="Need to analyze the image first.")
    image_bytes, last_result = last

    try:
        indices = json.loads(error_indices)
        if not isinstance(indices, list):
            indices = []
    except Exception:
        indices = []

    errors = (last_result or {}).get("e", [])
    if not errors:
        raise HTTPException(status_code=400, detail="No error data available.")

    agent = get_inpaint_agent()

    # Tạo preview mask (overlay UI)
    preview_bytes = agent.build_mask_preview(image_bytes, errors, indices, last_result or {})
    preview_b64 = "data:image/png;base64," + base64.b64encode(preview_bytes).decode("utf-8")

    # Tạo prompt gợi ý
    actual_lang = replyLang if replyLang in ["vi", "en"] else "en" ; print(f"DEBUG prepare-regen: replyLang={replyLang}, actual_lang={actual_lang}")
    suggested_prompt = agent.build_prompt(errors, indices, translator_cb=translate_vi_to_en, lang=actual_lang)

    # Chỉ lưu local (không upload ImgBB ở đây - tránh lỗi network không cần thiết)
    agent.save_local_image(image_bytes, key)


    return {
        "type": "regen_preview",
        "mask_preview_b64": preview_b64,
        "suggested_prompt": suggested_prompt,
        "error_count": len([i for i in indices if 0 <= i < len(errors)])
    }


# ENDPOINT: REGEN-IMAGE – Thực thi gen lại ảnh qua WillaAI
@app.post("/regen-image")
async def regen_image(
    session_id: Optional[str] = Form(""),
    error_indices: Optional[str] = Form("[]"),
    final_prompt: Optional[str] = Form(""),
    replyLang: Optional[str] = Form("auto"),
):
    """
    Bước 2: Gọi WillaAI Image Edits API để gen lại ảnh đã sửa lỗi.
    Trả về ảnh kết quả dạng base64.
    """
    key = session_id.strip() if session_id else "anonymous"

    last = memory_store.get_last_analysis(key)
    if not last:
        raise HTTPException(status_code=404, detail="Need to analyze the image first.")
    image_bytes, last_result = last

    try:
        indices = json.loads(error_indices)
        if not isinstance(indices, list):
            indices = []
    except Exception:
        indices = []

    agent = get_inpaint_agent()

    try:
        actual_lang = replyLang if replyLang in ["vi", "en"] else "en" ; print(f"DEBUG prepare-regen: replyLang={replyLang}, actual_lang={actual_lang}")
        result = agent.fix_errors(
            image_bytes=image_bytes,
            analysis_result=last_result or {},
            error_indices=indices,
            session_id=key,
            custom_prompt=final_prompt.strip() if final_prompt else None,
            translator_cb=translate_vi_to_en,
            lang=actual_lang,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error calling WillaAI API: {e}")

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=f"WillaAI API failed: {result.get('error', 'Unknown error')}"
        )

    result_bytes = result["result_bytes"]
    
    # Save the newly generated image into memory_store so follow-up edits build upon it
    # We keep the remaining errors list so the user can continue fixing other errors
    memory_store.set_last_analysis(key, result_bytes, last_result if last_result else {"e": []})
    
    result_b64 = "data:image/png;base64," + base64.b64encode(result_bytes).decode("utf-8")

    return {
        "type": "regen_result",
        "image_data_url": result_b64,
        "prompt_used": result["prompt_used"],
        "reply": f"✅ Successfully fixed {len(indices)} error regions using WillaAI. Here is the improved design:"
    }



@app.post("/api/suggest-style")
async def api_suggest_style(
    file: UploadFile = File(...),
    box_2d: str = Form("[]"),
    suggest_type: str = Form("typo")
):
    """
    Nhận ảnh và tọa độ box, gọi Qwen VL qua StyleSuggestAgent
    để gợi ý Font chữ hoặc Bảng màu.
    """
    try:
        image_bytes = await file.read()
        box_coords = json.loads(box_2d)
        if not isinstance(box_coords, list) or len(box_coords) != 4:
            box_coords = [0, 0, 0, 0]
            
        agent = get_style_agent()
        result = agent.suggest(image_bytes=image_bytes, box_2d=box_coords, suggest_type=suggest_type)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class ExtractLayersRequest(BaseModel):
    image_base64: str
    mime_type: str
    api_key: str
    num_layers: int = 5
    guidance_scale: float = 5.0
    num_inference_steps: int = 30
    auto_detect: bool = False

@app.post("/extract-layers")
def extract_layers(req: ExtractLayersRequest):
    fal_model = "fal-ai/qwen-image-layered"
    fal_base = "https://fal.run"
    
    num_layers = req.num_layers
    guidance_scale = req.guidance_scale
    num_inference_steps = req.num_inference_steps
    qwen_reason = None

    if req.auto_detect:
        try:
            print("[Qwen-VL Parameter Auto-Detection] Starting visual analysis...")
            image_bytes = base64.b64decode(req.image_base64)
            
            system_prompt = (
                "You are an expert design layer analyzer. "
                "Analyze the provided image and determine the optimal parameters for separating it into transparent design layers using Qwen-Image-Layered.\n"
                "Recommend:\n"
                "- num_layers: integer between 2 and 10 (count the distinct elements: background, primary character/subject, text/typography blocks, decorations, foreground overlays, icons, etc.)\n"
                "- guidance_scale: float between 1.0 and 10.0 (Recommend higher values (e.g. 6.0 - 8.0) if there is sharp text, complex fine details, or crisp boundaries to preserve. Recommend lower values (e.g. 3.0 - 5.0) if the image is a simple illustration or soft painting)\n"
                "- num_inference_steps: integer between 20 and 50 (Recommend higher values for complex images with many details, and lower for simpler images)\n\n"
                "Return ONLY a valid JSON object with the following keys:\n"
                "{\n"
                '  "num_layers": <int>,\n'
                '  "guidance_scale": <float>,\n'
                '  "num_inference_steps": <int>,\n'
                '  "reason": "A brief explanation of what elements were detected and why these parameters are recommended."\n'
                "}"
            )
            
            agent = get_agent()
            qwen_res = agent.qwen_agent.analyze(
                image_bytes=image_bytes,
                system_prompt=system_prompt,
                instruction="Analyze the uploaded image and recommend optimal layered separation parameters.",
                mime_type=req.mime_type
            )
            
            num_layers = int(qwen_res.get("num_layers", num_layers))
            guidance_scale = float(qwen_res.get("guidance_scale", guidance_scale))
            num_inference_steps = int(qwen_res.get("num_inference_steps", num_inference_steps))
            qwen_reason = str(qwen_res.get("reason", "Determined automatically by Qwen-VL."))
            
            # Clamp values to safe ranges
            num_layers = max(2, min(10, num_layers))
            guidance_scale = max(1.0, min(10.0, guidance_scale))
            num_inference_steps = max(10, min(50, num_inference_steps))
            
            print(f"[Qwen-VL Parameter Auto-Detection] Success: num_layers={num_layers}, guidance_scale={guidance_scale}, num_inference_steps={num_inference_steps}")
            print(f"[Qwen-VL Parameter Auto-Detection] Reason: {qwen_reason}")
        except Exception as e:
            print(f"[Qwen-VL Parameter Auto-Detection] Error: {e}. Falling back to default parameters.")
            import traceback
            traceback.print_exc()

    image_url = f"data:{req.mime_type};base64,{req.image_base64}"
    
    payload = {
        "image_url": image_url,
        "num_layers": num_layers,
        "guidance_scale": guidance_scale,
        "num_inference_steps": num_inference_steps
    }
    
    headers = {
        "Authorization": f"Key {req.api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(f"{fal_base}/{fal_model}", json=payload, headers=headers, timeout=60)
        
        if not resp.ok:
            raise HTTPException(status_code=resp.status_code, detail=f"fal.ai API error: {resp.text}")
            
        result = resp.json()
        
        if "images" in result or "output" in result:
            pass
        elif "request_id" in result:
            request_id = result["request_id"]
            status_url = f"{fal_base}/{fal_model}/requests/{request_id}/status"
            result_url = f"{fal_base}/{fal_model}/requests/{request_id}"
            
            attempts = 0
            while attempts < 120:
                time.sleep(3)
                attempts += 1
                s_resp = requests.get(status_url, headers=headers, timeout=10)
                if not s_resp.ok:
                    continue
                s_data = s_resp.json()
                state = s_data.get("status", "").lower()
                
                if state == "completed":
                    r_resp = requests.get(result_url, headers=headers, timeout=10)
                    result = r_resp.json()
                    break
                elif state == "failed":
                    raise HTTPException(status_code=500, detail=f"fal.ai job failed: {s_data}")
            else:
                raise HTTPException(status_code=504, detail="fal.ai processing timeout")
        else:
            raise HTTPException(status_code=500, detail="fal.ai returned unknown format")
            
        images = result.get("images") or result.get("output") or []
        if not images:
            raise HTTPException(status_code=500, detail="No layers found in response")
            
        layers = []
        for i, img in enumerate(images):
            url = img if isinstance(img, str) else img.get("url")
            c_type = img.get("content_type", "image/png") if isinstance(img, dict) else "image/png"
            layers.append({
                "index": i,
                "url": url,
                "contentType": c_type,
                "label": f"Layer {i+1}"
            })
            
        return {
            "layers": layers,
            "qwen_analysis": {
                "num_layers": num_layers,
                "guidance_scale": guidance_scale,
                "num_inference_steps": num_inference_steps,
                "reason": qwen_reason
            } if qwen_reason else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ChatGenerateRequest(BaseModel):
    messages: List[Dict[str, str]]
    grok_api_key: Optional[str] = ""
    fal_api_key: Optional[str] = ""

@app.post("/chat-generate")
async def chat_generate(req: ChatGenerateRequest):
    messages = req.messages
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided.")
    
    # Lấy tin nhắn cuối cùng của user để truy vấn RAG
    user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break
            
    rules_context = ""
    if user_msg:
        rules_context = retrieve_design_rules_context(user_msg, top_k=3)
        
    # Prepend system prompt to guide Grok
    system_prompt_text = (
        "You are WillaAI, a design AI assistant developed by Ewill. You can chat normally with the user. Do not mention Grok or x.ai. "
        "CRITICAL: If the user asks for facts, statistics, users, customers, or information about WillaAI, Ewill, or any real-world data that you do not have explicitly in your context, DO NOT hallucinate or invent information. You must honestly state that you do not have that information.\n"
        "However, if the user asks you to generate, draw, or create an image, you MUST respond EXACTLY in the following format and nothing else:\n"
        "[GENERATE_IMAGE] <detailed_english_prompt_for_image_generation>\n"
        "Example: [GENERATE_IMAGE] A highly detailed cyberpunk city at night with neon lights and flying cars, 8k resolution, photorealistic.\n\n"
    )
    if rules_context:
        system_prompt_text += (
            "Refer to the following project design rules to ground your graphic design advice and answers:\n"
            f"{rules_context}\n"
        )
        
    system_prompt = {
        "role": "system", 
        "content": system_prompt_text
    }
    
    grok_messages = [system_prompt] + messages
    
    actual_grok_key = req.grok_api_key or os.getenv("XAI_API_KEY", "")
    actual_fal_key = req.fal_api_key or os.getenv("FAL_API_KEY", "")
    
    if not actual_grok_key:
        raise HTTPException(status_code=400, detail="xAI API Key is missing. Please set XAI_API_KEY in .env or enter it in UI.")

    headers = {
        "Authorization": f"Bearer {actual_grok_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "grok-4.3",
        "messages": grok_messages,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        if not resp.ok:
            safe_error = sanitize_secret(resp.text, actual_grok_key)
            raise HTTPException(status_code=resp.status_code, detail=f"WillaAI API error: {safe_error}")
            
        data = resp.json()
        reply = data["choices"][0]["message"]["content"].strip()
        
        image_url = None
        
        # Check if Grok wants to generate an image
        if "[GENERATE_IMAGE]" in reply:
            prompt_match = re.search(r"\[GENERATE_IMAGE\](.*)", reply, re.IGNORECASE)
            if prompt_match:
                image_prompt = prompt_match.group(1).strip()
                
                # Call xAI Image Generation API
                xai_headers = {
                    "Authorization": f"Bearer {actual_grok_key}",
                    "Content-Type": "application/json"
                }
                xai_payload = {
                    "prompt": image_prompt,
                    "model": "grok-imagine-image-quality"
                }
                
                xai_resp = requests.post("https://api.x.ai/v1/images/generations", headers=xai_headers, json=xai_payload, timeout=60)
                if xai_resp.ok:
                    xai_data = xai_resp.json()
                    images = xai_data.get("data", [])
                    if images:
                        image_url = images[0].get("url")
                        reply = f"Mình đã vẽ xong bức ảnh theo yêu cầu của bạn dựa trên mô tả:\n*{image_prompt}*"
                else:
                    safe_error = sanitize_secret(xai_resp.text, actual_grok_key)
                    reply = f"Đã có lỗi khi tạo ảnh từ WillaAI: {safe_error}"
                    
        return {"text": reply, "image_url": image_url}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


from utils.image_prep import prepare_image
from services.dna_extractor import extract_dna
from services.asset_analyzer import analyze_batch
from services.aggregator import aggregate

@app.post("/brand-check")
async def brand_check(
    ref_images: List[UploadFile] = File(...),
    check_images: List[UploadFile] = File(...)
):
    try:
        # 1. Load & prep images
        ref_b64s = []
        for f in ref_images:
            data = await f.read()
            if data:
                ref_b64s.append(prepare_image(data))
                
        check_assets = []
        for f in check_images:
            data = await f.read()
            if data:
                check_assets.append((prepare_image(data), f.filename))
                
        if not ref_b64s or not check_assets:
            raise HTTPException(status_code=400, detail="Missing required images")
        
        # 2. Extract DNA
        dna = extract_dna(ref_b64s)
        
        # 3. Analyze all assets in parallel
        results = await analyze_batch(dna, check_assets)
        
        # 4. Aggregate
        report = aggregate(dna, results)
        return report
    except Exception as e:
        import traceback
        traceback.print_exc()

class WorkspaceChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    grok_api_key: Optional[str] = ""

@app.post("/workspace-chat")
async def workspace_chat(req: WorkspaceChatRequest):
    messages = req.messages
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided.")
        
    actual_grok_key = req.grok_api_key or os.getenv("XAI_API_KEY", "")
    
    if not actual_grok_key:
        raise HTTPException(status_code=400, detail="xAI API Key is missing.")

    headers = {
        "Authorization": f"Bearer {actual_grok_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "grok-build-0.1",
        "messages": messages,
        "temperature": 0.7
    }
    
    try:
        resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
        if not resp.ok:
            # Fallback if grok-build-0.1 doesn't exist, try grok-beta
            if resp.status_code == 404 or "model" in resp.text.lower():
                payload["model"] = "grok-beta"
                resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            
            if not resp.ok:
                safe_error = sanitize_secret(resp.text, actual_grok_key)
                raise HTTPException(status_code=resp.status_code, detail=f"WillaAI API error: {safe_error}")
            
        data = resp.json()
        reply = data["choices"][0]["message"]["content"].strip()
                    
        return {"text": reply}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
