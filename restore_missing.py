import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The missing code provided by the user
    missing_code = '''
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
        "You are an AI extracting design context information from the user's message.\\n"
        "Analyze the message and extract information for the following 8 context dimensions:\\n"
        "1. thoi_gian (Time / historical period)\\n"
        "2. dia_diem (Location / geographical context)\\n"
        "3. lich_su_xa_hoi (Historical / social / political context)\\n"
        "4. kinh_te (Economic segment / commercial or non-profit purpose)\\n"
        "5. van_hoa (Culture / community / beliefs)\\n"
        "6. art_style (Art style / dominant style)\\n"
        "7. ty_le (Aspect ratio / composition estimation)\\n"
        "8. chat_lieu (Print or digital material/medium)\\n\\n"
        "Return ONLY JSON in the following format (fields with no information should be set to null):\\n"
        "{\\n"
        '  "user_knows": true/false,\\n'
        '  "context": {\\n'
        '    "thoi_gian": "...",\\n'
        '    "dia_diem": "...",\\n'
        '    "lich_su_xa_hoi": "...",\\n'
        '    "kinh_te": "...",\\n'
        '    "van_hoa": "...",\\n'
        '    "art_style": "...",\\n'
        '    "ty_le": "...",\\n'
        '    "chat_lieu": "..."\\n'
        "  }\\n"
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

def run_antigraviti_phase_2a(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Chạy Phase 2A: Quét hình ảnh bằng Vision API để phân tích 8 chiều bối cảnh + đặc tính trực quan
    """
    system_prompt = (
        "You are a visual context analyzer for design critique. "
        "Analyze the uploaded image strictly along these 8 dimensions and extract visual style traits. "
        "Be specific, factual, and concise. Return structured JSON only."
    )
    instruction = (
        "Analyze this design image and return a JSON object with these exact keys:\\n"
        "{\\n"
        '  "thoi_gian": "Time period / historical era evoked by the design",\\n'
        '  "dia_diem": "Geographical setting, region, or cultural space",\\n'
        '  "lich_su_xa_hoi": "Historical events, social movements, or political background",\\n'
        '  "kinh_te": "Economic segment, commercial or non-profit purpose",\\n'
        '  "van_hoa": "Cultural background, symbols, or cultural community",\\n'
        '  "art_style": "Art style (specific name + identifying characteristics)",\\n'
        '  "ty_le": "Aspect ratio and layout structure estimate",\\n'
        '  "chat_lieu": "Evoked printing material or digital medium",\\n'
        '  "visual_style_description": "Detailed description of the visual layout, typography, main colors, contrast, composition style",\\n'
        '  "suggested_query": "Optimized English search query combining artistic and visual context for accurate RAG retrieval of design rules",\\n'
        '  "confidence": "high / medium / low",\\n'
        '  "notes": "Any special observations"\\n'
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
    mime_type: str = "image/jpeg"
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
            rag_results_text += f"[{idx+1}] {title}:\\n{text}\\n\\n"
    else:
        rag_results_text = "No reference documents found in the knowledge base."

    system_prompt = (
        "You are a senior design critic. Re-analyze this design image and produce a refined, enriched analysis across 8 dimensions. "
        "Flag any CONFLICTS between the design's visual language and its stated/detected context. "
        "Rate contextual coherence on a scale of 1-10 for each dimension.\\n\\n"
        "Analyze strictly across these 8 dimensions:\\n"
        "1. Time (thoi_gian)\\n"
        "2. Location (dia_diem)\\n"
        "3. History & Society (lich_su_xa_hoi)\\n"
        "4. Economy (kinh_te)\\n"
        "5. Culture (van_hoa)\\n"
        "6. Art Style (art_style)\\n"
        "7. Ratio (ty_le)\\n"
        "8. Material (chat_lieu)\\n"
    )
    
    instruction = (
        f"Given the following context retrieved from our design knowledge base:\\n"
        f"=== RAG REFERENCES ===\\n"
        f"{rag_results_text}\\n"
        f"======================\\n\\n"
        f"And the current design context:\\n"
        f"- Time: {context.get('thoi_gian')}\\n"
        f"- Location: {context.get('dia_diem')}\\n"
        f"- History & Society: {context.get('lich_su_xa_hoi')}\\n"
        f"- Economy: {context.get('kinh_te')}\\n"
        f"- Culture: {context.get('van_hoa')}\\n"
        f"- Art Style: {context.get('art_style')}\\n"
        f"- Ratio: {context.get('ty_le')}\\n"
        f"- Material: {context.get('chat_lieu')}\\n\\n"
        f"Re-analyze the design image. Return ONLY valid JSON with these exact keys:\\n"
        "{\\n"
        '  "thoi_gian": {"analysis": "Analysis in English...", "score": 8},\\n'
        '  "dia_diem": {"analysis": "Analysis in English...", "score": 7},\\n'
        '  "lich_su_xa_hoi": {"analysis": "Analysis in English...", "score": 9},\\n'
        '  "kinh_te": {"analysis": "Analysis in English...", "score": 8},\\n'
        '  "van_hoa": {"analysis": "Analysis in English...", "score": 8},\\n'
        '  "art_style": {"analysis": "Analysis in English...", "score": 9},\\n'
        '  "ty_le": {"analysis": "Analysis in English...", "score": 8},\\n'
        '  "chat_lieu": {"analysis": "Analysis in English...", "score": 7},\\n'
        '  "conflicts": [\\n'
        '     "Conflict 1 description if any",\\n'
        '     "Conflict 2 description if any"\\n'
        '  ],\\n'
        '  "coherence_total": 8.2\\n'
        "}\\n\\n"
        "Note:\\n"
        "- Each score must be an integer between 1 and 10.\\n"
        "- coherence_total is the overall coherence score (float between 1.0 and 10.0).\\n"
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

def format_antigraviti_report(analysis_result: dict) -> str:
    """
    Format context analysis results in Phase 2 layout
    """
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
        "═══════════════════════════════════════════════\\n"
        "🔍 DESIGN CONTEXT ANALYSIS\\n"
        "═══════════════════════════════════════════════\\n\\n"
    )
    
    for key, (label, friendly_name) in keys_map.items():
        data = analysis_result.get(key, {})
        if isinstance(data, dict):
            analysis = data.get("analysis", "No analysis data available.")
            score = data.get("score", 0)
        else:
            analysis = str(data)
            score = 0
            
        report += f"{label}\\n"
        report += f"[Analysis] {analysis}\\n\\n"
        
    report += "───────────────────────────────────────────────\\n"
    conflicts = analysis_result.get("conflicts", [])
    if conflicts and isinstance(conflicts, list):
        report += "⚠️ CONFLICTS (if any):\\n"
        for conflict in conflicts:
            report += f"- {conflict}\\n"
    else:
        report += "⚠️ CONFLICTS (if any): No significant conflicts detected.\\n"
        
    report += "───────────────────────────────────────────────\\n\\n"
    report += "✅ Is this context description accurate?\\n"
    report += "→ Reply **\\"OK\\"** to receive feedback on the artwork based on the context above.\\n"
    report += "→ Reply **\\"Edit: [details]\\"** to modify the context."
    
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

'''

    content = content.replace(
        '@app.post("/chat")',
        missing_code + '\\n\\n@app.post("/chat")'
    )

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process('backend/main.py')
print("Restored missing code")
