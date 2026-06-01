# Cải tiến Hệ thống Chỉ đạo AI Kiểm tra Thiết kế (Willa)

Dưới đây là tóm tắt những thay đổi cốt lõi của hệ thống Willa AI (Design Check) vừa qua, lý do output chuyển sang tiếng Việt và bảng phân tích chuyên sâu so sánh sự khác biệt.

## 1. Chi tiết chuyên sâu về các thay đổi kỹ thuật (Technical Changes)

Để đạt được sự lột xác về chất lượng phân tích, hệ thống đã được tác động trực tiếp vào 2 Agent trọng yếu của Pipeline:

### A. Tinh chỉnh `post_process_agent.py` (Bộ lọc hậu kỳ)
Đây là chốt chặn cuối cùng trước khi data được gửi về Web App. Để giải quyết dứt điểm vấn đề "rác hiển thị" (hiển thị quá nhiều lỗi phụ), mình đã can thiệp đoạn code xử lý mảng `cleaned` (danh sách lỗi đã lọc sơ bộ):
1. **Thuật toán Sắp xếp (Sorting)**: Đưa ra bộ trọng số ưu tiên `severity_priority = {"critical": 0, "major": 1, "minor": 2}` và dùng hàm `sort()` để chèn ép các khối lỗi có tag `critical` và `major` lên đầu mảng.
2. **Cắt tỉa mảng (Hard-Limiting)**: Thêm biến hằng số `MAX_STEPS = 5` và cắt lát trực tiếp tệp kết quả bằng cờ `cleaned = cleaned[:MAX_STEPS]`. Thao tác này cắt gọt thẳng tay mọi lỗi thừa thãi (chiếm vị trí từ số 6 trở đi) giúp frontend hoàn toàn rảnh tay.

### B. Tinh chỉnh `prompt_agent.py` (Kỹ thuật điều hướng LLM - Prompt Engineering)
Phần lớn sức mạnh suy luận đến từ cách chúng ta dặn dò AI. Prompt mới đã được "vũ khí hóa" qua 3 kỹ thuật:
1. **Giới hạn số lượng từ trong trứng nước**: Thêm hẳn yêu cầu `Identify a maximum of 5 most critical design violations` vào file prompt. Việc này giúp LLM chủ động bỏ qua những lỗi lặt vặt (tiết kiệm token) và dành thời gian "suy nghĩ" thật kỹ về 5 lỗi nghiêm trọng nhất.
2. **Ép khung trọng tâm (Enhanced Focus Focus)**: Cụ thể hóa `Instructions` để AI chỉ soi chiếu 4 lăng kính thiết kế chuyên nghiệp:
   * **Typography (Kiểu chữ)**: Khó đọc cỡ chữ sai.
   * **Colors & Contrast (Màu sắc)**: Tương phản tiền cảnh/hậu cảnh.
   * **Layout & Hierarchy (Bố cục)**: Mất điểm neo, thiết kế lộn xộn, thiếu khoảng trắng.
   * **CTA & Messaging (Điều hướng)**: Nút hành động bị chìm, thông điệp chồng chéo.
3. **Mẫu In-Context Learning 100% tiếng Việt**:
   * Sửa cấu trúc đầu ra chuẩn mực từ chuỗi text lộn xộn thành 2 biến tách biệt trong nội tại đoạn văn: `"Vấn đề: <giải thích>. Khuyến nghị: <đề xuất sửa>."`
   * Mình đã ghi đè (override) phần **FEW-SHOT EXAMPLE** (khối ví dụ JSON mồi) bên trong hệ thống sang tiếng Việt hoàn chỉnh. Nhờ vậy, Qwen3-VL-Flash tự động "học lỏm" ngữ điệu và format từ ví dụ mẫu, đem lại output tự nhiên và đầy đủ thuật ngữ thiết kế chứ không còn là một hệ thống dịch thuật ngô nghê.

---

## 2. So sánh 2 Output (Trước sửa vs. Sau sửa)

| Tiêu chí | 🔴 Output TRƯỚC khi sửa | 🟢 Output SAU khi sửa | Đánh giá / Hiệu quả |
| :--- | :--- | :--- | :--- |
| **Ngôn ngữ** | 100% Tiếng Anh | 100% Tiếng Việt tự nhiên, đi kèm các thuật ngữ ngành thiết kế (typography, figure-ground...) | Gần gũi và ứng dụng được ngay với người dùng design nội địa. |
| **Số lượng lỗi** | Dài tay, trả về tận 7 lỗi lắt nhắt (1 critical, 5 major, 1 minor) | Giới hạn cứng trong **5 lỗi** đáng quan tâm nhất (1 critical, 1 major, 3 minor) | Giảm tải nhận thức (Cognitive load). Người dùng biết ngay vấn đề cốt lõi. |
| **Cấu trúc nội dung** | Format văn xuôi lộn xộn, bị trộn lẫn phân tích lỗi và nhắc lại quy tắc chung chung. | Tách đôi thông tin vô cùng sắc bén:<br>• **Vấn đề**: Yếu tố nào đang hỏng.<br>• **Khuyến nghị**: Action cụ thể. | Tính hành động (Actionable) triệt để. User biết ngay phải thao tác gì. |
| **Tính trọng tâm** | Câu chữ đôi lúc lan man phê bình sáo rỗng (như "editorial choice"). | Xoáy trực tiếp đúng vào yếu tố UI/UX: *hiệu ứng figure blending, nhiễu ánh sáng, mất visual weight, chìm nền CTA...* | Nhận xét đanh thép, mang đến cảm giác của một Senior Designer Reviewer thực thụ. |
