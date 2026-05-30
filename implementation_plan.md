# Kế hoạch Triển khai: Tính năng X-Quang Thiết Kế (Design Decoding Engine)

Kế hoạch này vạch ra lộ trình chi tiết để xây dựng tính năng "Quét & Giải mã thiết kế" cho hệ thống WILLA, biến ứng dụng thành một người cố vấn thiết kế thực thụ (Design Mentor).

## 1. Trải nghiệm người dùng (UI/UX Flow)

### Bước 1: Đầu vào (Input)
- **Giao diện:** Khu vực kéo/thả ảnh chuyên dụng với tiêu đề: *"Tải lên một thiết kế bạn thích, WILLA sẽ giải mã công thức đằng sau nó."*
- **Xử lý:** Người dùng upload ảnh (PNG/JPG). Có thể thêm tùy chọn crop ảnh nếu chỉ muốn phân tích một phần.

### Bước 2: Hiệu ứng X-Quang (Processing state)
- Thay vì biểu tượng loading xoay tròn nhàm chán, hiển thị hiệu ứng vạch quét laser (Scanner effect) chạy dọc bức ảnh.
- Hiện các popup text nhỏ lướt qua (giả lập AI đang làm việc): *"Đang đo lường không gian trống...", "Đang phân tích tâm lý màu...", "Đang vẽ sơ đồ mắt nhìn..."*

### Bước 3: Giao diện Kết quả (Decoding Dashboard)
Màn hình kết quả chia làm 2 phần (Split view):
- **Bên trái (Visual):** Bức ảnh gốc được hiển thị với các "lớp phủ" (overlay) có thể bật/tắt:
  - **Lớp Heatmap (Quét Luồng Thị Giác):** Hiển thị sơ đồ nhiệt hoặc các đường mũi tên (Z-pattern, F-pattern) để chỉ ra luồng ánh mắt: *"Mắt người xem sẽ bị thu hút vào điểm A đầu tiên, di chuyển sang B và dừng lại ở C"*.
  - **Lớp Không gian trống (Negative Space):** Tô sáng (highlight nhẹ) các vùng "Breathing Room" để cho thấy cách thiết kế dùng khoảng trống để tôn lên chủ thể.
  - **Lớp Grid & Typography:** Hiện các đường kẻ khung, đóng khung các đoạn text (H1, H2, Body).
- **Bên phải (Data & Insights):** Báo cáo phân tích chi tiết gồm các Tab:
  - **Hệ thống Phân cấp (Visual Hierarchy):** Đánh giá tỷ lệ tương phản kích thước (Ví dụ: Tiêu đề lớn gấp 2.5 lần đoạn văn). Phân tích điểm nhấn chính.
  - **Màu sắc & Tâm lý học:** Hiển thị công thức phân bổ màu (Quy tắc 60-30-10) dạng biểu đồ tròn. Cung cấp nhận định về **Tâm trạng màu sắc (Color Mood)** (VD: "Bảng màu mang phong cách Earthy/Minimalism, tạo cảm giác tin cậy").
  - **Không gian & Tương phản:** Đo lường **Tỷ lệ thở (Breathing Room %)** và chấm điểm **Chỉ số tương phản (Contrast Score)** giữa chữ và nền.
  - **Bố cục tổng thể:** Tên bố cục đang dùng, lý do nó hoạt động tốt.

### Bước 4: Hành động (Action - Remix)
- Nút Call-to-Action: **"Tạo cấu trúc nháp từ thiết kế này"** (Tự động tạo ra các khối placeholder trên một Canvas mới).
- Nút: **"Lưu công thức vào thư viện"**.

---

## 2. Luồng xử lý Kỹ thuật (Technical Architecture)

### Tầng AI (Vision LLM & Xử lý ảnh)
Sử dụng các mô hình Vision (như GPT-4o, Claude 3.5 Sonnet, hoặc Gemini 1.5 Pro) kết hợp xử lý thuật toán:

1. **Phân tích Màu sắc & Tâm lý học (Color Psychology & Ratio):**
   - *Thuật toán:* Dùng Python (K-Means clustering) để trích xuất màu và tính % diện tích (Quy tắc 60-30-10: Nền, Cấu trúc, Nhấn).
   - *LLM Vision:* Đưa mảng màu và ảnh cho LLM để suy luận **Tâm trạng màu sắc (Mood)** dựa trên ngữ cảnh thiết kế.

2. **Hệ thống Phân cấp & Luồng thị giác (Hierarchy & Eye-tracking):**
   - *Thuật toán + LLM:* Dùng thuật toán Saliency Map (OpenCV) kết hợp nhận định của Vision LLM để vẽ ra lộ trình của mắt (A -> B -> C).
   - *Phân cấp Typography:* LLM phân tích tỷ lệ kích thước giữa Heading, Sub-heading và Body text để đưa ra con số tương phản cụ thể.

3. **Không gian trống & Độ tương phản (Negative Space & Contrast):**
   - *Thuật toán:* Dùng Edge detection hoặc entropy map để tính toán % diện tích không chứa thông tin (**Breathing Room**).
   - *Độ tương phản:* Dùng công thức WCAG (Web Content Accessibility Guidelines) để tính toán điểm tương phản màu sắc giữa text (lấy từ OCR) và background tại vị trí đó.

### Tầng Backend (FastAPI)
- **Endpoint 1 (`/analyze-design`):** Nhận file ảnh.
  - Chạy chuỗi pipeline đa luồng: Trích xuất màu + tính % không gian trống + đo Saliency Map + OCR tìm text.
  - Tổng hợp dữ liệu thô gửi lên Vision LLM để xin "Insight" sâu (Tâm lý học, Luồng thị giác).
  - Trả về JSON tổng hợp.

### Tầng Frontend (HTML/JS/CSS)
- Xây dựng component Canvas vẽ ảnh và nhiều lớp overlay (Heatmap, Saliency arrows, Grid, Negative Space mask).
- Biểu đồ trực quan cho Quy tắc 60-30-10.

---

## 3. Cấu trúc Prompt lõi (Core Prompting)

Prompt gửi cho Vision LLM sẽ được thiết kế để tập trung vào tính chuyên sâu:

```text
Bạn là một Giám đốc Nghệ thuật (Art Director) và chuyên gia UX/UI. Hãy phân tích "X-Quang" thiết kế này dưới dạng JSON:
1. "visual_path": [Mô tả chi tiết 3 bước luồng mắt người xem di chuyển (Vd: Tiêu đề -> Ảnh -> Nút bấm)]
2. "typography_hierarchy": [Đánh giá tỷ lệ tương phản chữ, ví dụ: "Tiêu đề gấp 3 lần Body, phân cấp tuyệt vời"]
3. "color_mood": [Nhận định tâm lý học của bảng màu này, cảm giác nó mang lại]
4. "color_ratio_insight": [Nhận xét về cách họ áp dụng quy tắc tỷ lệ màu]
5. "negative_space_usage": [Đánh giá cách thiết kế dùng khoảng trống để "thở" và tôn chủ thể]
6. "contrast_review": [Đánh giá sự nổi bật của text so với nền]
```

---

## 4. Lộ trình Phát triển (Phases)

- **Giai đoạn 1 (MVP - Hiện tại):** 
  - Chỉ dùng Vision LLM phân tích và trả về Text/Insight cho 3 hạng mục mới (Luồng thị giác, Tâm lý màu, Không gian trống).
  - Tích hợp trích xuất màu cơ bản.
- **Giai đoạn 2 (Advanced Visuals & Algorithms):** 
  - Áp dụng các thuật toán Computer Vision thực sự (Saliency Map cho Heatmap, tính toán % Breathing room chính xác).
  - Thêm các lớp phủ trực quan trên Frontend (Mũi tên luồng thị giác, highlight khoảng trống).
- **Giai đoạn 3 (Template Generator & Remix):** 
  - Tính năng "Tạo bản nháp" (Remix) - Chuyển đổi dữ liệu layout thành một wireframe HTML/CSS.

> [!IMPORTANT]
> **Câu hỏi chờ xác nhận:**
> 1. Với những bổ sung chi tiết này, bạn có muốn bắt tay vào việc setup Endpoint API cho Giai đoạn 1 ngay lập tức không?
> 2. Việc tính toán chính xác % (như 60-30-10 hay % Breathing room) sẽ cần cài thêm các thư viện xử lý ảnh cho Python (như `opencv-python`, `scikit-learn` cho K-Means). Tôi sẽ thêm chúng vào `requirements.txt` nếu bạn đồng ý.
