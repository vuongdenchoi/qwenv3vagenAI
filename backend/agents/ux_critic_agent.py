from __future__ import annotations
import json
from typing import Optional
from .qwen_agent import QwenAgent

class UXCriticAgent:
    def __init__(self, api_key=None):
        self.qwen_agent = QwenAgent(api_key=api_key)

    def generate_critique(
        self, 
        image_bytes: bytes, 
        errors: list[dict], 
        rag_rules: list[dict], 
        lang: str = "vi",
        persona_context: Optional[dict] = None
    ) -> dict:
        """
        Calls Qwen-VL to perform a deep UX critique based on detected errors, image, and RAG rules.
        Filters out mathematical false positives and adds high-level graphic design errors.
        """
        # Formulate description of rules
        rules_text = ""
        for idx, rule in enumerate(rag_rules[:15]):
            category = rule.get("category", "general").replace("_", " ").title()
            section = rule.get("section", "General")
            rule_num = rule.get("rule_number", 0)
            title = rule.get("rule_title", "Quy tắc thiết kế")
            text = rule.get("text", "")
            rules_text += f"[{category} > {section}] — Rule {rule_num}: {title}\n{text}\n\n"
            
        # Formulate description of errors
        errors_text = json.dumps(errors, ensure_ascii=False, indent=2)
        
        # Build persona preference text if available
        persona_text = ""
        if persona_context and isinstance(persona_context, dict):
            design_patterns = persona_context.get("designPatterns", {})
            recent_count = design_patterns.get("recentAnalysisCount", 0)
            if recent_count > 0:
                behavior = persona_context.get("behavior", {})
                categories = [cat.replace("_", " ") for cat in design_patterns.get("topIssueCategories", [])]
                categories_str = ", ".join(categories) if categories else "none"
                severity_mix = design_patterns.get("severityMix", {})
                severity_mix_str = ", ".join([f"{k}: {v}" for k, v in severity_mix.items()]) if severity_mix else "none"
                focus_hints = design_patterns.get("focusHints", [])
                focus_hints_str = ", ".join(focus_hints) if focus_hints else "none"
                primary_workflow = behavior.get("primaryWorkflow", "none")
                
                persona_text = (
                    "\n=== USER DESIGN PERSONA (SOFT PREFERENCES) ===\n"
                    "Aggregated from the user's recent design analyses (no raw chat or images).\n"
                    f"- Often struggles with: {categories_str}\n"
                    f"- Typical severity mix: {severity_mix_str}\n"
                    f"- Focus areas: {focus_hints_str}\n"
                    f"- Primary use: {primary_workflow}\n\n"
                    "Instructions:\n"
                    "- When writing recommendations, place a slightly higher emphasis on the categories and focus areas listed above if they exist among the detected errors.\n"
                    "- Do NOT invent errors or make up feedback only because of this persona.\n"
                    "- Ensure the design critique remains fully professional and grounded in the actual image.\n"
                    "=== END USER DESIGN PERSONA ===\n\n"
                )
        
        system_prompt = (
            "You are an expert graphic design critic named WillaAI, a project developed by the Ewill team, focusing on design feedback solutions to help users analyze errors, identify areas for improvement, and optimize designs more clearly and quickly.\n"
            "You are a strict, professional Art Director and Senior UX/UI Critic. Your job is to analyze the design image and the list of candidate technical errors detected by our automated tools.\n"
            "You must perform two critical tasks:\n"
            "1. ERROR FILTERING (Lọc nhiễu): Review the candidate technical errors. Filter out false positives (e.g., alignment checks between organic/decorative elements like faces/bodies and text, tiny 1-2px shifts, or contrast warnings on purely decorative/stylistic background text).\n"
            "2. GRAPHIC DESIGN AUDIT (Quét lỗi đồ họa): Scan the entire image for other major design violations. Look for issues like:\n"
            "   - Figure-ground contrast and readability (e.g. text/characters overlapping characters' bodies/faces or blending into busy backgrounds).\n"
            "   - Typography overload and Visual Hierarchy (e.g. text that is too large, bright, or has heavy glowing effects/gradients/drop shadows that compete for visual dominance with the main focal point, such as the subject's face).\n"
            "   - Lack of Breathing Room / Crowded Details (e.g. chibis or decorative assets placed too close to the main subject, causing visual tension and clutter).\n"
            "   - Rhythm, Pattern, and Campaign Inconsistency (e.g. lack of structure or repeating motifs across elements).\n\n"
            "Format your reply as a structured report with:\n"
            "1. 'critique_summary': A general overview of the design strengths and weaknesses (2-3 paragraphs).\n"
            "2. 'critique_details': Detailed explanations and suggestions for each major validated issue. Connect them to the design rules (e.g., WCAG 2.1 contrast, alignment, proximity).\n"
            "3. 'validated_errors': A list of validated errors (filtered candidate errors plus new graphic design errors you detected). Each error MUST match the schema below (with keys 'c', 'r', 's', 'g'):\n"
            "   - 'c': [x1, y1, x2, y2] bounding box on grid 0-1000.\n"
            "   - 'r': A concise description of the issue and specific fix recommendation in natural language.\n"
            "   - 's': severity ('minor' | 'major' | 'critical').\n"
            "   - 'g': category ('color_theory' | 'typography' | 'layout_rules' | 'logo_design' | 'poster_design' | 'icon_design' | 'pattern_design' | 'general').\n"
            "4. 'export_markdown': A complete copy of the critique formatted in clean Markdown, ready to be exported for developers or designers.\n\n"
            "Output your entire response ONLY as a valid JSON object matching the schema below (do not include markdown fences outside the JSON):\n"
            "{\n"
            '  "critique_summary": "...",\n'
            '  "critique_details": [\n'
            '     {\n'
            '       "box_2d": [x1, y1, x2, y2],\n'
            '       "issue": "...",\n'
            '       "guideline_violation": "...",\n'
            '       "ux_explanation": "...",\n'
            '       "suggestion": "..."\n'
            '     }\n'
            '  ],\n'
            '  "validated_errors": [\n'
            '     {\n'
            '       "c": [x1, y1, x2, y2],\n'
            '       "r": "...",\n'
            '       "issue": "...",\n'
            '       "suggestion": "...",\n'
            '       "s": "minor|major|critical",\n'
            '       "g": "color_theory|typography|layout_rules|logo_design|poster_design|icon_design|pattern_design|general"\n'
            '     }\n'
            '  ],\n'
            '  "compliments": [\n'
            '     "Khen ngợi 1...",\n'
            '     "Khen ngợi 2...",\n'
            '     "Khen ngợi 3..."\n'
            '  ],\n'
            '  "export_markdown": "..."\n'
            "}"
        )
        
        if lang == "vi":
            system_prompt += (
                "\nLanguage Requirement: All text values (in critique_summary, critique_details, validated_errors 'r', and export_markdown) MUST be written entirely in natural, professional Vietnamese (Tiếng Việt). Keep JSON keys in English, but the string values must be in Vietnamese.\n\n"
                "=== VÍ DỤ MINH HỌA (FEW-SHOT EXAMPLE) ===\n"
                "{\n"
                '  "critique_summary": "Thiết kế poster có điểm mạnh về màu sắc và bố cục, phù hợp với phong cách Genshin Impact. Tuy nhiên, thiết kế còn gặp lỗi về độ tương phản chữ và sắp xếp các yếu tố phụ...",\n'
                '  "critique_details": [\n'
                '     {\n'
                '       "box_2d": [69, 54, 209, 69],\n'
                '       "issue": "Dòng chữ \'GENSHIN IMPACT\' có độ tương phản cực kỳ thấp (1.02:1), không đạt tiêu chuẩn WCAG.",\n'
                '       "guideline_violation": "[Color Theory > Color Contrast] — Contrast Ratio Standard",\n'
                '       "ux_explanation": "Chữ quá mờ trên nền xanh đậm làm giảm khả năng nhận diện thương hiệu từ xa.",\n'
                '       "suggestion": "Chuyển chữ sang màu trắng hoặc vàng sáng để tăng độ tương phản rõ rệt."\n'
                '     },\n'
                '     {\n'
                '       "box_2d": [20, 85, 970, 690],\n'
                '       "issue": "Ký tự chữ Trung Quốc màu trắng kích thước lớn đè lên đầu và thân nhân vật chính gây nhiễu và tranh chấp hình nền (figure-ground confusion).",\n'
                '       "guideline_violation": "[Poster Design > II. Composition and Spatial Structure] — Figure-ground must be clear at a glance",\n'
                '       "ux_explanation": "Chữ lớn màu trắng đè lên cosplayer làm mờ nhạt tiêu điểm chính của tác phẩm.",\n'
                '       "suggestion": "Giảm độ mờ (opacity) của dòng chữ này xuống còn 15-20% hoặc chuyển chữ ra phía sau nhân vật chính."\n'
                '     }\n'
                '  ],\n'
                '  "validated_errors": [\n'
                '     {\n'
                '       "c": [69, 54, 209, 69],\n'
                '       "r": "Độ tương phản chữ \'GENSHIN IMPACT\' quá thấp (1.02:1), không đạt mức tối thiểu 4.5:1 theo WCAG. Cần thay đổi màu chữ thành trắng hoặc vàng sáng, hoặc thêm lớp nền tối nhẹ để tăng độ tương phản.",\n'
                '       "issue": "Dòng chữ \'GENSHIN IMPACT\' có độ tương phản cực kỳ thấp (1.02:1)",\n'
                '       "suggestion": "Chuyển chữ sang màu trắng hoặc vàng sáng để tăng độ tương phản rõ rệt.",\n'
                '       "s": "critical",\n'
                '       "g": "color_theory"\n'
                '     },\n'
                '     {\n'
                '       "c": [20, 85, 970, 690],\n'
                '       "r": "Các ký tự chữ Trung Quốc màu trắng lớn đè lên cosplayer tạo ra hiện tượng tranh chấp hình nền (figure-ground confusion) nghiêm trọng, làm mất đi tính nổi bật của nhân vật chính.",\n'
                '       "issue": "Ký tự chữ Trung Quốc màu trắng kích thước lớn đè lên đầu và thân nhân vật chính gây nhiễu và tranh chấp hình nền",\n'
                '       "suggestion": "Giảm độ mờ (opacity) của dòng chữ này xuống còn 15-20% hoặc chuyển chữ ra phía sau nhân vật chính.",\n'
                '       "s": "critical",\n'
                '       "g": "poster_design"\n'
                '     }\n'
                '  ],\n'
                '  "compliments": [\n'
                '     "Màu sắc nổi bật, mang đậm phong cách anime đặc trưng.",\n'
                '     "Bố cục tổng thể phân bổ hợp lý, hướng mắt người xem tốt.",\n'
                '     "Hình ảnh nhân vật được xử lý sắc nét, thu hút."\n'
                '  ],\n'
                '  "export_markdown": "# Báo cáo Đánh giá UX\\n... "\n'
                "}\n"
            )
            
        instruction = (
            f"Here is the list of candidate technical layout/semantic/contrast errors detected in this design:\n"
            f"=== CANDIDATE ERRORS ===\n"
            f"{errors_text}\n"
            f"========================\n\n"
            f"{persona_text}"
            f"Here are the relevant Design Guidelines retrieved from our knowledge base:\n"
            f"=== DESIGN GUIDELINES ===\n"
            f"{rules_text}\n"
            f"=========================\n\n"
            f"Analyze the UI image and the candidate errors. Filter out false positives, detect additional graphic design errors, and write the UX Critique.\n"
            f"Write all text fields in {'Vietnamese (Tiếng Việt)' if lang == 'vi' else 'English'}.\n"
            "Ensure the bounding boxes ('box_2d' and 'c') are correct and match the objects in the image. Be precise and professional. Keep the total count of errors under 5-6 to avoid overwhelming the user, prioritizing the most critical."
        )
        
        try:
            raw_result = self.qwen_agent.analyze(
                image_bytes=image_bytes,
                system_prompt=system_prompt,
                instruction=instruction,
                mime_type="image/jpeg"
            )
            return raw_result
        except Exception as e:
            print(f"[UXCriticAgent] Error generating critique: {e}")
            # Fallback: construct standard response from errors list
            lang_label = "Báo cáo UX Audit" if lang == "vi" else "UX Audit Report"
            overview_label = "Tổng quan" if lang == "vi" else "Overview"
            issues_label = "Chi tiết lỗi:" if lang == "vi" else "Detailed Issues:"
            fallback_md = f"# {lang_label}\n\n## {overview_label}\nHệ thống đã quét và phát hiện các lỗi thiết kế.\n\n## {issues_label}\n"
            details = []
            for idx, err in enumerate(errors):
                reason = err.get("r", "")
                box = err.get("c", [0, 0, 0, 0])
                fallback_md += f"### Lỗi {idx+1} (Tọa độ: {box})\n- **Vấn đề & Gợi ý**: {reason}\n- **Mức độ nghiêm trọng**: {err.get('s', 'minor')}\n\n"
                details.append({
                    "box_2d": box,
                    "issue": reason,
                    "guideline_violation": "WCAG / Design Grid",
                    "ux_explanation": f"Lỗi thiết kế tại tọa độ {box}. {reason}",
                    "fix_recommendation": "Hãy điều chỉnh phần tử theo chỉ dẫn kỹ thuật."
                })
            return {
                "critique_summary": "Quá trình đánh giá bằng LLM gặp lỗi kỹ thuật. Dưới đây là tổng hợp lỗi từ công cụ kiểm tra toán học và ngữ nghĩa.",
                "critique_details": details,
                "validated_errors": errors,
                "export_markdown": fallback_md
            }

