import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Stronger lang_req in Phase 2a
    old_lang_req_2a = '    lang_req = "You must output all text values in Vietnamese (Tiếng Việt)." if lang == "vi" else "You must output all text values in English."'
    new_lang_req_2a = '    lang_req = "You MUST output all text values in Vietnamese (Tiếng Việt)." if lang == "vi" else "CRITICAL: You MUST write all output strings entirely in English. Do NOT use Vietnamese under any circumstances, even if the JSON keys are in Vietnamese."'
    content = content.replace(old_lang_req_2a, new_lang_req_2a)

    # 2. Stronger lang_req in Phase 2b
    old_lang_req_2b = '''        f"- You MUST write the 'analysis' fields and 'conflicts' strings entirely in {'Vietnamese (Tiếng Việt)' if lang == 'vi' else 'English'}.\\n"'''
    new_lang_req_2b = '''        f"- CRITICAL INSTRUCTION: You MUST write the 'analysis' fields and 'conflicts' strings entirely in {'Vietnamese (Tiếng Việt)' if lang == 'vi' else 'English. Do NOT use Vietnamese under any circumstances, even if the RAG references or JSON keys are in Vietnamese'}.\\n"'''
    content = content.replace(old_lang_req_2b, new_lang_req_2b)

    # 3. Add lang_req to system_prompt in Phase 2b
    # Find the system_prompt of Phase 2b:
    old_sp_2b = '''    system_prompt = (
        "You are a senior design critic. Re-analyze this design image and produce a refined, enriched analysis across 8 dimensions. "
        "Flag any CONFLICTS between the design's visual language and its stated/detected context. "
        "Rate contextual coherence on a scale of 1-10 for each dimension.\\n\\n"
        "Analyze strictly across these 8 dimensions:\\n"'''
    new_sp_2b = '''    lang_req_sp = "Answer in Vietnamese." if lang == "vi" else "CRITICAL: You MUST answer entirely in English. ABSOLUTELY NO VIETNAMESE."
    system_prompt = (
        "You are a senior design critic. Re-analyze this design image and produce a refined, enriched analysis across 8 dimensions. "
        "Flag any CONFLICTS between the design's visual language and its stated/detected context. "
        "Rate contextual coherence on a scale of 1-10 for each dimension.\\n\\n"
        f"{lang_req_sp}\\n\\n"
        "Analyze strictly across these 8 dimensions:\\n"'''
    content = content.replace(old_sp_2b, new_sp_2b)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process('backend/main.py')
print("Applied stronger language constraints")
