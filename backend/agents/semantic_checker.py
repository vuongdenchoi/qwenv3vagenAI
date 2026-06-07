from __future__ import annotations
import re

def calculate_box_distance(boxA: list[int], boxB: list[int]) -> float:
    """Calculates the minimum distance between two bounding boxes [x1, y1, x2, y2]."""
    x1_A, y1_A, x2_A, y2_A = boxA
    x1_B, y1_B, x2_B, y2_B = boxB
    
    dx = max(0, x1_B - x2_A, x1_A - x2_B)
    dy = max(0, y1_B - y2_A, y1_A - y2_B)
    
    return (dx**2 + dy**2) ** 0.5

class SemanticChecker:
    def __init__(self):
        pass

    def check_casing(self, text: str) -> str | None:
        """
        Checks if text casing is weird/inconsistent (e.g. mIxEd cAsE).
        Returns the warning description if inconsistent, else None.
        """
        t = text.strip()
        if not t or len(t) < 4:
            return None
            
        # Ignore normal Title Case, Sentence case, UPPERCASE, and lowercase
        if t.isupper() or t.islower():
            return None
        
        # Check if first character is uppercase and the rest is lowercase (Sentence case)
        if t[0].isupper() and t[1:].islower():
            return None
            
        # Check if it's Title Case (words start with uppercase)
        words = t.split()
        if all(w[0].isupper() and (len(w) == 1 or w[1:].islower()) for w in words if w.isalpha()):
            return None
            
        # If it doesn't match standard patterns, check if it has random capitalizations
        # E.g. "sUbmit", "clIcK"
        if re.search(r'[a-z][A-Z][a-z]', t) or re.search(r'[A-Z][A-Z][a-z][A-Z]', t):
            return f"Kiểu viết chữ không đồng nhất hoặc bị lỗi capitalization: '{text}'."
            
        return None

    def audit(self, elements: list[dict]) -> list[dict]:
        """
        Audits UI elements semantically.
        elements format: list of dicts: {"box_2d": [x1,y1,x2,y2], "label": str, "score": float}
        Returns a list of error dicts.
        """
        errors = []
        
        # Separate text elements for proximity checking
        text_boxes = []
        for el in elements:
            lbl = el["label"].lower()
            if "text" in lbl or lbl.startswith("text:"):
                text_boxes.append(el["box_2d"])

        for el in elements:
            label_raw = el["label"]
            label_lower = label_raw.lower().strip()
            box = el["box_2d"]
            
            # --- 1. Button Audit ---
            if label_lower == "button" or label_lower.startswith("text: button") or label_lower.startswith("text: btn"):
                # If we have extracted button text (e.g. "text: click here to submit")
                btn_text = ""
                if label_raw.startswith("text:"):
                    btn_text = label_raw[5:].strip()
                
                # Check button text word count
                if btn_text:
                    words_count = len(btn_text.split())
                    if words_count > 5:
                        errors.append({
                            "box_2d": box,
                            "issue": f"Nhãn nút hành động (Button label) quá dài ({words_count} từ): '{btn_text}'.",
                            "suggestion": "Nhãn nút nên ngắn gọn, súc tích và bắt đầu bằng một động từ hành động (ví dụ: 'Đăng nhập', 'Gửi ngay', 'Tìm kiếm').",
                            "severity": "major",
                            "category": "typography"
                        })
                    
                    # Check casing
                    case_warn = self.check_casing(btn_text)
                    if case_warn:
                        errors.append({
                            "box_2d": box,
                            "issue": case_warn,
                            "suggestion": "Hãy chuyển nhãn nút sang viết hoa đầu từ (Title Case) hoặc chỉ viết hoa chữ cái đầu tiên (Sentence case) để đảm bảo tính thẩm mỹ chuyên nghiệp.",
                            "severity": "minor",
                            "category": "typography"
                        })
                else:
                    # Generic button with no label text detected
                    pass

            # --- 2. Input Field Proximity Audit ---
            elif label_lower == "input field" or label_lower == "input":
                # Find if there is any text label nearby (max distance 120 units in normalized grid)
                has_label = False
                for t_box in text_boxes:
                    dist = calculate_box_distance(box, t_box)
                    if dist <= 120.0:
                        has_label = True
                        break
                
                if not has_label:
                    errors.append({
                        "box_2d": box,
                        "issue": "Trường nhập liệu (Input field) không tìm thấy nhãn văn bản (Label) kề cận.",
                        "suggestion": "Thêm nhãn văn bản phía trên hoặc bên trái trường nhập liệu để người dùng biết họ cần nhập thông tin gì.",
                        "severity": "major",
                        "category": "layout_rules"
                    })

            # --- 3. Casing Check for Text Elements ---
            elif label_raw.startswith("text:"):
                text_content = label_raw[5:].strip()
                case_warn = self.check_casing(text_content)
                if case_warn:
                    errors.append({
                        "box_2d": box,
                        "issue": case_warn,
                        "suggestion": "Đảm bảo quy tắc viết hoa được nhất quán trên toàn bộ thiết kế.",
                        "severity": "minor",
                        "category": "typography"
                    })

        return errors
