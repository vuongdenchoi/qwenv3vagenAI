import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Replace format_antigraviti_report signature and body
    old_func = '''def format_antigraviti_report(analysis_result: dict) -> str:
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
    
    return report'''

    new_func = '''def format_antigraviti_report(analysis_result: dict, lang: str = "vi") -> str:
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
            "═══════════════════════════════════════════════\\n"
            "🔍 PHÂN TÍCH BỐI CẢNH THIẾT KẾ\\n"
            "═══════════════════════════════════════════════\\n\\n"
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
        report += "⚠️ CÁC ĐIỂM XUNG ĐỘT:\\n" if lang == "vi" else "⚠️ CONFLICTS (if any):\\n"
        for conflict in conflicts:
            report += f"- {conflict}\\n"
    else:
        report += "⚠️ CÁC ĐIỂM XUNG ĐỘT: Không phát hiện xung đột đáng kể.\\n" if lang == "vi" else "⚠️ CONFLICTS (if any): No significant conflicts detected.\\n"
        
    report += "───────────────────────────────────────────────\\n\\n"
    if lang == "vi":
        report += "✅ Mô tả bối cảnh này đã chính xác chưa?\\n"
        report += "→ Trả lời **\\"OK\\"** để nhận đánh giá chi tiết thiết kế dựa trên bối cảnh này.\\n"
        report += "→ Trả lời **\\"Sửa: [chi tiết]\\"** để điều chỉnh lại bối cảnh."
    else:
        report += "✅ Is this context description accurate?\\n"
        report += "→ Reply **\\"OK\\"** to receive feedback on the artwork based on the context above.\\n"
        report += "→ Reply **\\"Edit: [details]\\"** to modify the context."
    
    return report'''

    content = content.replace(old_func, new_func)

    # 2. Update calls inside unified_chat
    content = content.replace('report_text = format_antigraviti_report(_display_analysis)', 'report_text = format_antigraviti_report(_display_analysis, actual_lang)')
    content = content.replace('report_text = format_antigraviti_report(analysis_result)', 'report_text = format_antigraviti_report(analysis_result, actual_lang)')
    content = content.replace('report_text = format_antigraviti_report(reanalyzed_result)', 'report_text = format_antigraviti_report(reanalyzed_result, actual_lang)')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process('backend/main.py')
print("Fixed format_antigraviti_report")
