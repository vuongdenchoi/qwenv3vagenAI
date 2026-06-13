import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update run_antigraviti_phase_2a
    old_2a = '''def run_antigraviti_phase_2a(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
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
    )'''

    new_2a = '''def run_antigraviti_phase_2a(image_bytes: bytes, mime_type: str = "image/jpeg", lang: str = "vi") -> dict:
    """
    Chạy Phase 2A: Quét hình ảnh bằng Vision API để phân tích 8 chiều bối cảnh + đặc tính trực quan
    """
    lang_req = "You must output all text values in Vietnamese (Tiếng Việt)." if lang == "vi" else "You must output all text values in English."
    system_prompt = (
        "You are a visual context analyzer for design critique. "
        "Analyze the uploaded image strictly along these 8 dimensions and extract visual style traits. "
        "Be specific, factual, and concise. Return structured JSON only. "
        f"{lang_req}"
    )
    instruction = (
        f"Analyze this design image and return a JSON object with these exact keys. {lang_req}\\n"
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
    )'''
    content = content.replace(old_2a, new_2a)

    # 2. Update run_antigraviti_phase_2b
    old_2b = '''def run_antigraviti_phase_2b(
    image_bytes: bytes,
    context: dict,
    mime_type: str = "image/jpeg"
) -> dict:'''
    new_2b = '''def run_antigraviti_phase_2b(
    image_bytes: bytes,
    context: dict,
    mime_type: str = "image/jpeg",
    lang: str = "vi"
) -> dict:'''
    content = content.replace(old_2b, new_2b)

    old_2b_inst = '''        f"Re-analyze the design image. Return ONLY valid JSON with these exact keys:\\n"
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
    )'''

    new_2b_inst = '''        f"Re-analyze the design image. Return ONLY valid JSON with these exact keys:\\n"
        "{\\n"
        '  "thoi_gian": {"analysis": "Analysis string...", "score": 8},\\n'
        '  "dia_diem": {"analysis": "Analysis string...", "score": 7},\\n'
        '  "lich_su_xa_hoi": {"analysis": "Analysis string...", "score": 9},\\n'
        '  "kinh_te": {"analysis": "Analysis string...", "score": 8},\\n'
        '  "van_hoa": {"analysis": "Analysis string...", "score": 8},\\n'
        '  "art_style": {"analysis": "Analysis string...", "score": 9},\\n'
        '  "ty_le": {"analysis": "Analysis string...", "score": 8},\\n'
        '  "chat_lieu": {"analysis": "Analysis string...", "score": 7},\\n'
        '  "conflicts": [\\n'
        '     "Conflict 1 description if any",\\n'
        '     "Conflict 2 description if any"\\n'
        '  ],\\n'
        '  "coherence_total": 8.2\\n'
        "}\\n\\n"
        "Note:\\n"
        f"- You MUST write the 'analysis' fields and 'conflicts' strings entirely in {'Vietnamese (Tiếng Việt)' if lang == 'vi' else 'English'}.\\n"
        "- Each score must be an integer between 1 and 10.\\n"
        "- coherence_total is the overall coherence score (float between 1.0 and 10.0).\\n"
        "- If there are no conflicts, conflicts must be an empty list []."
    )'''
    content = content.replace(old_2b_inst, new_2b_inst)

    # 3. Update calls to 2a and 2b inside unified_chat
    content = content.replace(
        'agent.qwen_agent.analyze(\n        image_bytes=image_bytes,\n        system_prompt=system_prompt,\n        instruction=instruction,\n        mime_type=mime_type\n    )',
        'agent.qwen_agent.analyze(\n        image_bytes=image_bytes,\n        system_prompt=system_prompt,\n        instruction=instruction,\n        mime_type=mime_type\n    )'
    ) # just a sanity check

    content = content.replace(
        '_display_analysis = run_antigraviti_phase_2a(ag_image)',
        '_display_analysis = run_antigraviti_phase_2a(ag_image, lang=actual_lang)'
    )
    content = content.replace(
        'analysis_result = run_antigraviti_phase_2b(ag_image, current_context)',
        'analysis_result = run_antigraviti_phase_2b(ag_image, current_context, lang=actual_lang)'
    )
    content = content.replace(
        'reanalyzed_result = run_antigraviti_phase_2b(ag_image, new_ctx)',
        'reanalyzed_result = run_antigraviti_phase_2b(ag_image, new_ctx, lang=actual_lang)'
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process('backend/main.py')
print("Fixed Phase 2A and 2B prompts")
