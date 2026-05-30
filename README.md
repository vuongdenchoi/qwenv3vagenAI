# Design Check AI – Hệ thống kiểm tra lỗi thiết kế 2D

Hệ thống AI phát hiện lỗi trong bản thiết kế 2D sử dụng **RAG + Qwen Multimodal Vision**.

## Kiến trúc

```
User Upload Image
      │
      ▼
DesignCheckAgent (Orchestrator)
      │
      ├─► RetrievalAgent  → Multilingual Embedding → Top-10 Design Rules
      ├─► PromptAgent     → Multimodal Prompt (Quick-Fix Priority)
      ├─► QwenAgent       → Qwen 3 VL API → JSON errors (Max 5)
      └─► PostProcessAgent→ Validate + WCAG Analysis + Render
                                  │
                              Frontend HTML
                         (bounding box overlay)
```

## Cấu trúc thư mục

```
qwen3v/
├── design_rules/          # Knowledge base (markdown)
│   ├── typography.md
│   ├── color_theory.md
│   ├── layout_rules.md
│   ├── poster_design.md
│   └── logo_design.md
├── backend/
│   ├── main.py            # FastAPI server
│   ├── requirements.txt
│   ├── agents/
│   │   ├── design_check_agent.py   # Orchestrator
│   │   ├── retrieval_agent.py      # FAISS search
│   │   ├── prompt_agent.py         # Prompt builder
│   │   ├── qwen_agent.py           # Qwen VL API
│   │   └── post_process_agent.py   # Validate + clean
│   └── knowledge_base/
│       └── build_index.py          # Build FAISS index (run once)
├── frontend/
│   └── index.html         # Web UI
└── run.py                 # Unified runner script
```

## Cách chạy

### Bước 0: Set API Key

```bash
# Windows PowerShell
$env:DASHSCOPE_API_KEY = "sk-your-key-here"; $env:IMGBB_API_KEY = "your-imgbb-key-here  "; $env:PUBLIC_BASE_URL = "http://localhost:8000"; python run.py serve
# Linux/Mac
export DASHSCOPE_API_KEY="sk-your-key-here"
export IMGBB_API_KEY="your-imgbb-key-here"
```

> Lấy API key tại: https://dashscope.aliyun.com

### Bước 1: Cài thư viện

```bash
cd d:\qwen3v
python run.py install
```

### Bước 2: Build knowledge base index (chỉ cần 1 lần)

```bash
python run.py build-index
```

### Bước 3: Chạy server

```bash
python run.py serve
```

Hoặc chạy tất cả cùng lúc:

```bash
python run.py all
```

### Bước 4: Mở browser

Truy cập: **http://localhost:8000**

## API Endpoint

```
POST /chat
Content-Type: multipart/form-data

file  : <image file>  (JPEG/PNG/WEBP, max 10MB) - Tuỳ chọn
message : <string>    (Câu hỏi hoặc yêu cầu zoom/sửa ảnh)
session_id : <string> (Để backend quản lý lịch sử hội thoại)
action_type : "zoom"  (Nếu dùng nút bấm zoom)
error_index : <int>   (Index lỗi cần zoom)

Ghi nhớ hội thoại:
- Backend sẽ lưu thêm "turns" (user query + assistant JSON tóm tắt) theo `session_id/user_id`
- Các turns gần nhất sẽ được gửi kèm vào `messages` khi gọi Qwen, giúp LLM trả lời nhất quán khi người dùng hỏi lại

Response:
{
  "type": "analysis" | "chat" | "zoom",
  "reply": "Text response",
  "analysis_data": {
    "e": [
      {
        "c": [x1, y1, x2, y2],
        "r": "Vấn đề: ... Khuyến nghị: ...",
        "s": "severity",
        "g": "category"
      }
    ],
    "isz": {"w": W, "h": H},
    "te": total_errors
  }
}
```

## Models & APIs sử dụng

| Component         | Model/Tool                    |
|-------------------|-------------------------------|
| Embedding         | paraphrase-multilingual-MiniLM|
| Vector DB         | FAISS (local flat index)      |
| Vision Language   | Qwen 3 VL Flash (DashScope)   |
| Image Edit        | WillaAI Imagine (x.ai)      |
| Backend           | FastAPI + Uvicorn             |
| Frontend          | Plain HTML + Canvas Overlay   |
