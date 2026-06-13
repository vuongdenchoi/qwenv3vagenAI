import re

def process(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define actual_lang at the top of unified_chat
    # unified_chat starts around line 766
    content = content.replace(
        '    action = action_type.strip().lower() if action_type else ""\n',
        '    action = action_type.strip().lower() if action_type else ""\n    actual_lang = lang if lang else detect_feedback_language(msg)\n'
    )
    
    # 1. Rubic prompt
    rubic_en = """                    "Awesome! Let's analyze the suitability of this design using **8 dimensions of Rubic** context! 🎨\\n\\n"
                    "Could you share some details about your design context?\\n"
                    "*(For example: time period, location, cultural context, art style, economic segment, print or digital medium...)*\\n\\n"
                    "  Or reply **\\"AI tự phát hiện\\"** (or **\\"AI detect\\"**) to let me automatically analyze the context from your image!\""""

    rubic_vi = """                    "Tuyệt vời! Hãy cùng phân tích bối cảnh thiết kế này qua **8 chiều Rubic** nhé! 🎨\\n\\n"
                    "Bạn có thể chia sẻ thêm một chút về bối cảnh thiết kế không?\\n"
                    "*(Ví dụ: thời gian, địa điểm, văn hóa, phong cách nghệ thuật, phân khúc kinh tế, in ấn hay kỹ thuật số...)*\\n\\n"
                    "Hoặc hãy trả lời **\\"AI tự phát hiện\\"** để tôi tự động phân tích bối cảnh từ ảnh của bạn!\""""

    content = content.replace(rubic_en, f"({rubic_vi}) if actual_lang == 'vi' else ({rubic_en})")

    # 2. Context captured
    ctx_cap_en = """                    "Here is the design context I captured and cross-referenced with the RAG knowledge base! 📚\\n\\n"
                    f"{report_text}\""""
    ctx_cap_vi = """                    "Đây là bối cảnh thiết kế tôi đã thu thập và đối chiếu với hệ tri thức RAG! 📚\\n\\n"
                    f"{report_text}\""""
    content = content.replace(ctx_cap_en, f"({ctx_cap_vi}) if actual_lang == 'vi' else ({ctx_cap_en})")

    # 3. Context adjusted
    ctx_adj_en = """                        "I have adjusted the context according to your request! ✨🎯\\n\\n"
                        f"{report_text}\""""
    ctx_adj_vi = """                        "Tôi đã điều chỉnh lại bối cảnh theo yêu cầu của bạn! ✨🎯\\n\\n"
                        f"{report_text}\""""
    content = content.replace(ctx_adj_en, f"({ctx_adj_vi}) if actual_lang == 'vi' else ({ctx_adj_en})")

    # 4. Context confirmed 1
    ctx_conf1_en = """                        f"✅ Design context confirmed successfully!\\n\\n"
                        f"{compliments_text}"
                        "You can now continue chatting to fix any design errors!\""""
    ctx_conf1_vi = """                        f"✅ Bối cảnh thiết kế đã được xác nhận thành công!\\n\\n"
                        f"{compliments_text}"
                        "Bạn có thể tiếp tục trò chuyện để sửa các lỗi thiết kế nhé!\""""
    content = content.replace(ctx_conf1_en, f"({ctx_conf1_vi}) if actual_lang == 'vi' else ({ctx_conf1_en})")

    # 5. Context confirmed 2
    ctx_conf2_en = """                            f"✅ Context confirmed!\\n\\n"
                            f"{compliments_text}"
                            "I have regenerated the design feedback using this new context.\\n"
                            "You can see the highlighted errors on the image, or continue chatting to fix them (e.g., 'fix error #1', 'fix all errors').\""""
    ctx_conf2_vi = """                            f"✅ Bối cảnh đã được xác nhận!\\n\\n"
                            f"{compliments_text}"
                            "Tôi đã phân tích lại thiết kế dựa trên bối cảnh mới này.\\n"
                            "Bạn có thể xem các lỗi được đánh dấu trên ảnh, hoặc tiếp tục chat để sửa lỗi nhé (vd: 'sửa lỗi số 1', 'sửa tất cả lỗi').\""""
    content = content.replace(ctx_conf2_en, f"({ctx_conf2_vi}) if actual_lang == 'vi' else ({ctx_conf2_en})")

    # 6. Context confirmed 3 (already done via 5 usually, but let's be sure)
    ctx_conf3_en = """                                f"✅ Context confirmed!\\n\\n"
                                f"{compliments_text}"
                                "I have regenerated the design feedback using this new context.\\n"
                                "You can see the highlighted errors on the image, or continue chatting to fix them (e.g., 'fix error #1', 'fix all errors').\""""
    content = content.replace(ctx_conf3_en, f"({ctx_conf2_vi}) if actual_lang == 'vi' else ({ctx_conf3_en})")

    # 7. Context confirmed short
    ctx_short_en = '"Excellent! Context has been confirmed. You can continue chatting to fix any design errors!"'
    ctx_short_vi = '"Tuyệt vời! Bối cảnh đã được xác nhận. Bạn có thể tiếp tục chat để sửa các lỗi thiết kế!"'
    content = content.replace(ctx_short_en, f"({ctx_short_vi}) if actual_lang == 'vi' else ({ctx_short_en})")

    # 8. Successfully updated
    upd_en = """                            "I have successfully updated the design context! ✨🎯\\n"
                            "Here is the adjusted context:\\n\\n"
                            f"{report_text}\""""
    upd_vi = """                            "Tôi đã cập nhật bối cảnh thiết kế thành công! ✨🎯\\n"
                            "Dưới đây là bối cảnh đã được điều chỉnh:\\n\\n"
                            f"{report_text}\""""
    content = content.replace(upd_en, f"({upd_vi}) if actual_lang == 'vi' else ({upd_en})")

    # 9. Modify request
    mod_en = """                            "Would you like to modify the design context? 🤔✨\\n"
                            "Please share the new context information you'd like to target (e.g., time period, location, culture, art style, materials, etc.).\\n"
                            "*(Example: \\"Change art style to Cyberpunk\\", \\"Add 90s vintage vibe\\")*\""""
    mod_vi = """                            "Bạn có muốn chỉnh sửa lại bối cảnh thiết kế không? 🤔✨\\n"
                            "Hãy chia sẻ thông tin bối cảnh mới mà bạn muốn hướng đến nhé (vd: thời gian, địa điểm, văn hóa, phong cách nghệ thuật, chất liệu...).\\n"
                            "*(Ví dụ: \\"Đổi phong cách thành Cyberpunk\\", \\"Thêm cảm giác vintage thập niên 90\\")*\""""
    content = content.replace(mod_en, f"({mod_vi}) if actual_lang == 'vi' else ({mod_en})")

    # 10. Automatically scanned
    scan_en = """                        "I have automatically scanned the entire design context from the image! 🕵️‍♂️✨\\n\\n"
                        f"{report_text}\""""
    scan_vi = """                        "Tôi đã tự động quét và nhận diện toàn bộ bối cảnh thiết kế từ hình ảnh! 🕵️‍♂️✨\\n\\n"
                        f"{report_text}\""""
    content = content.replace(scan_en, f"({scan_vi}) if actual_lang == 'vi' else ({scan_en})")

    # 11. Request critique
    crit_en = """                        "To provide the most accurate and suitable design feedback, "
                        "please share the desired context for this artwork (e.g., time period, location, culture, art style, etc.).\\n"
                        "Or reply **\\"AI detect\\"** to let me automatically analyze it for you!\""""
    crit_vi = """                        "Để cung cấp feedback chính xác và phù hợp nhất, "
                        "bạn vui lòng chia sẻ bối cảnh mong muốn cho thiết kế này nhé (vd: thời gian, địa điểm, văn hóa, phong cách...).\\n"
                        "Hoặc hãy trả lời **\\"AI tự phát hiện\\"** để tôi tự động phân tích giúp bạn!\""""
    content = content.replace(crit_en, f"({crit_vi}) if actual_lang == 'vi' else ({crit_en})")

    # 12. Zoom in on
    zoom_en = '"Here is the detailed design area you requested to zoom in on:"'
    zoom_vi = '"Đây là khu vực thiết kế chi tiết mà bạn muốn phóng to:"'
    content = content.replace(zoom_en, f"{zoom_vi} if actual_lang == 'vi' else {zoom_en}")

    # 13. Couldn't identify area
    cant_zoom_en = '"Sorry, I couldn\'t identify the area you want to zoom in on. Could you please describe it more clearly?"'
    cant_zoom_vi = '"Xin lỗi, tôi không thể xác định được khu vực bạn muốn phóng to. Bạn có thể mô tả rõ hơn được không?"'
    content = content.replace(cant_zoom_en, f"{cant_zoom_vi} if actual_lang == 'vi' else {cant_zoom_en}")

    # 14. Normal chat fallback
    norm_en = '"Is there anything else I can help you with regarding your design?"'
    norm_vi = '"Tôi có thể giúp gì thêm cho bạn về thiết kế này không?"'
    content = content.replace(norm_en, f"{norm_vi} if actual_lang == 'vi' else {norm_en}")

    # Remove the redundant actual_lang assignments inside unified_chat to avoid UnboundLocalError or confusion
    content = content.replace("actual_lang = lang if lang else detect_feedback_language(msg)", "pass # removed")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

process('backend/main.py')
print("Done processing main.py")
