# 🔄 Luồng Code Chạy – Design Check AI

## 📁 Cấu trúc dự án

```
qwen3v - genAI/
├── run.py                          ← Entrypoint khởi động hệ thống
├── frontend/
│   └── index.html                  ← Giao diện người dùng (HTML/CSS/JS)
└── backend/
    ├── main.py                     ← FastAPI app, định nghĩa các endpoint
    ├── memory_store.py             ← Lưu trữ session trong RAM
    ├── requirements.txt
    ├── knowledge_base/
    │   ├── build_index.py          ← Build embedding index từ design rules
    │   └── faiss_index/
    │       ├── embeddings.npy      ← Vector embedding (N × 384)
    │       └── metadata.json       ← Metadata từng rule
    ├── agents/
    │   ├── design_check_agent.py   ← Orchestrator pipeline phân tích
    │   ├── retrieval_agent.py      ← Tìm design rules liên quan (TF-IDF / Embedding)
    │   ├── prompt_agent.py         ← Build prompt gửi cho Qwen VL
    │   ├── qwen_agent.py           ← Gọi Qwen VL API (DashScope)
    │   ├── post_process_agent.py   ← Validate, clean JSON kết quả
    │   ├── inpaint_agent.py        ← Gọi Willa (x.ai) để sửa ảnh
    │   └── color_analyzer.py       ← Kiểm tra WCAG contrast ratio
    └── static_temp/                ← Ảnh gốc lưu tạm trước khi upload ImgBB
```

---

## 🚀 BƯỚC 0 — Khởi động hệ thống

```
python run.py serve
```

**`run.py`** làm các việc:
1. (Tuỳ chọn) `install` → `pip install -r requirements.txt`
2. (Tuỳ chọn) `build-index` → chạy `build_index.py` tạo embedding index
3. `serve` → khởi động FastAPI qua `uvicorn main:app --reload`

**Env vars cần thiết:**
| Biến | Dùng cho |
|---|---|
| `DASHSCOPE_API_KEY` | Qwen VL API (phân tích ảnh + chat) |
| `XAI_API_KEY` | WillaAI (x.ai) API (sửa ảnh) |
| `IMGBB_API_KEY` | Upload ảnh lên ImgBB lấy public URL |
| `PUBLIC_BASE_URL` | Base URL server (mặc định `http://localhost:8000`) |

---

## 🖥️ Giao diện người dùng (`frontend/index.html`)

Frontend gọi các API sau:
- `POST /chat` → Upload ảnh phân tích, chat hỏi đáp, zoom lỗi
- `POST /prepare-regen` → Xem preview vùng lỗi sẽ sửa
- `POST /regen-image` → Thực thi sửa ảnh bằng WillaAI

---

## 🔁 LUỒNG 1 — Phân tích ảnh (`POST /chat` + file)

```
User upload ảnh
      │
      ▼
main.py /chat
  ├─ Scale ảnh xuống ≤ 1536px (tiết kiệm token)
  ├─ Lấy/ghép query từ MemoryStore (session_id)
  └─ Gọi DesignCheckAgent.analyze()
          │
          ▼
    [1] RetrievalAgent.retrieve(query)
          ├─ Encode query → vector 384D (SentenceTransformer multilingual)
          ├─ Cosine similarity với embeddings.npy
          ├─ Category boost ×1.3 nếu query khớp domain
          │   (color, typography, layout, logo, poster, icon, pattern)
          ├─ Fallback: nếu score ≤ 0.01 → dùng query mẫu generic
          └─ Trả về top-10 design rules

          │
          ▼
    [2] PromptAgent.build_prompt(rules)
          ├─ Tổng hợp các rule thành system_prompt + instruction
          ├─ Quick-Fix Priority Flow: Yêu cầu Qwen chỉ tìm tối đa 5 lỗi quan trọng nhất
          └─ Prompt yêu cầu Qwen trả về JSON schema { "e": [...] } với Enhanced Structured Feedback

          │
          ▼
    [3] QwenAgent.analyze(image_bytes, system_prompt, instruction)
          ├─ Encode ảnh → base64 data URL
          ├─ Gọi DashScope MultiModalConversation.call()
          │   Model: qwen3-vl-flash (endpoint quốc tế)
          │   Format: messages = [system, (history), user{image + text}]
          ├─ Parse response: strip <think>...</think>, strip markdown fences
          └─ Trả về dict { "e": [...errors...], "_usage": {...} }

          │
          ▼
    [4] PostProcessAgent.process(raw_result, image_bytes)
          ├─ Validate JSON structure
          ├─ Convert tọa độ: nếu all ≤ 1000 → normalize (÷1000 × img_size)
          ├─ Clamp vào bounds ảnh
          ├─ Deduplication (box_key = tọa độ ÷ 10)
          ├─ Lọc bỏ box quá nhỏ (< 5×5 px)
          ├─ Validate severity: minor / major / critical
          ├─ Validate category: color_theory / typography / layout_rules / ...
          ├─ ColorAnalyzer: check WCAG contrast ratio cho vùng typography/color
          │   → Nếu ratio < 4.5:1 → append cảnh báo WCAG vào reason
          │   → ratio < 3.0 → tự động nâng severity lên "critical"
          ├─ Enhanced Structured Feedback: 
          │   - Nội dung reason (r) định dạng "Vấn đề: ... Khuyến nghị: ..."
          │   - Phân tích sâu ngữ cảnh (Layout, Typography, Colors, CTA, Messaging)
          ├─ Xóa "Rule X" mentions khỏi reason text
          └─ Trả về:
              {
                "e": [ {"c":[x1,y1,x2,y2], "r":"...", "s":"major", "g":"typography"} ],
                "isz": {"w": W, "h": H},
                "te": <tổng số lỗi>,
                "ss": {"minor":N, "major":N, "critical":N},
                "inputtoken": N, "outputtoken": N, "totaltoken": N
              }

      │
      ▼
main.py
  ├─ Lưu kết quả vào MemoryStore (session_id → image_bytes + result)
  ├─ Lưu file latest_result.json ra disk
  └─ Trả về JSON cho frontend
      {
        "type": "analysis",
        "reply": "Tôi đã quét xong...",
        "has_analysis": true,
        "analysis_data": { ...result... },
        "usage": { input_tokens, output_tokens, total_tokens }
      }
```

---

## 💬 LUỒNG 2 — Chat thuần tuý (`POST /chat` + text only)

```
User gõ câu hỏi (không có file)
      │
      ▼
main.py /chat
  ├─ Lấy lịch sử hội thoại từ MemoryStore (last 10 turns)
  └─ Gọi QwenAgent.chat_json(system_prompt, user_text, history)
          ├─ Text-only call (không có ảnh)
          ├─ System prompt: "You are WillaAI – design assistant. Return JSON: {reply, zoom_command}"
          └─ Trả về { "reply": "...", "zoom_command": null | {box_2d:[...]} }

  ├─ Nếu user hỏi "phóng to / zoom / lỗi số X":
  │     └─ Gọi QwenAgent.locate_box(image_bytes, user_request, context)
  │           ├─ Gửi ảnh + yêu cầu zoom
  │           └─ Trả về { "box_2d": [x1,y1,x2,y2] }
  │     └─ Crop ảnh + vẽ bounding box đỏ → trả về base64 PNG
  │
  ├─ Lưu turn vào MemoryStore
  └─ Trả về { "type": "chat" | "zoom", "reply": "...", "image_data_url": "..." }
```

---

## 🔍 LUỒNG 3 — Zoom lỗi từ nút bấm (`POST /chat` + action=zoom)

```
User click nút zoom trên error card (error_index = N)
      │
      ▼
main.py /chat  [action="zoom", error_index=N]
  ├─ Lấy image_bytes + last_result từ MemoryStore
  ├─ Lấy box = errors[N]["c"] hoặc errors[N]["box_2d"]
  ├─ Crop ảnh tại vùng box + padding 40px
  ├─ Vẽ viền đỏ neon (#FF4D6D) width=4
  └─ Trả về base64 PNG crop
      { "type": "zoom", "reply": "...", "image_data_url": "data:image/png;base64,..." }
```

---

## 🎨 LUỒNG 4 — Sửa ảnh bằng WillaAI AI (2 bước)

### Bước 4a — Preview mask (`POST /prepare-regen`)

```
User chọn checkbox các lỗi muốn sửa → click "Preview"
      │
      ▼
main.py /prepare-regen  [session_id, error_indices=[0,2,3]]
  ├─ Lấy image_bytes + errors từ MemoryStore
  ├─ Gọi InpaintAgent.build_mask_preview(image_bytes, errors, indices)
  │     ├─ Vẽ overlay đỏ mờ (rgba 220,30,30,100) lên các vùng lỗi
  │     └─ Trả về PNG bytes
  ├─ Gọi InpaintAgent.build_prompt(errors, indices)
  │     ├─ Lấy description từng lỗi được chọn
  │     ├─ Tính spatial location từ bounding box (Top/Center/Bottom - Left/Right)
  │     └─ Ghép thành prompt tiếng Anh ≤ 1000 ký tự
  ├─ Lưu ảnh gốc xuống static_temp/ (save_local_image)
  └─ Trả về:
      { "mask_preview_b64": "...", "suggested_prompt": "...", "error_count": N }
```

### Bước 4b — Thực thi sửa ảnh (`POST /regen-image`)

```
User (tuỳ chỉnh prompt nếu muốn) → click "Sửa ảnh"
      │
      ▼
main.py /regen-image  [session_id, error_indices, final_prompt]
  └─ Gọi InpaintAgent.fix_errors(image_bytes, analysis_result, indices, session_id, custom_prompt)
          │
          ▼
    [A] save_local_image(image_bytes, session_id)
          ├─ Convert sang RGB, scale lên ≥ 768px nếu cần
          └─ Lưu JPEG vào static_temp/original_{session_id}.jpg

          │
          ▼
    [B] upload_to_imgbb(local_path)
          ├─ Đọc file từ disk
          ├─ Encode base64
          ├─ POST https://api.imgbb.com/1/upload (key, image, expiration=600s)
          ├─ Compress nếu > 20MB (quality steps: 90 → 75 → 60)
          └─ Trả về public URL ImgBB

          │
          ▼
    [C] run_inpainting(image_url=imgbb_url, prompt)
          ├─ POST https://api.x.ai/v1/images/edits
          │   Headers: Authorization: Bearer {XAI_API_KEY}
          │   Body: {
          │     "model": "grok-imagine-image",
          │     "prompt": "Please edit this image to fix...",
          │     "image": { "url": "<imgbb_url>", "type": "image_url" }
          │   }
          ├─ Response: { "data": [{ "url": "<result_url>" }] }
          └─ Download ảnh kết quả từ result_url

      │
      ▼
main.py
  └─ Trả về:
      {
        "type": "regen_result",
        "image_data_url": "data:image/png;base64,...",
        "prompt_used": "...",
        "reply": "✅ Đã sửa N vùng lỗi bằng WillaAI (x.ai)..."
      }
```

---

## 🗄️ MemoryStore (RAM-only, thread-safe)

```
MemoryStore  [Dict[session_id → SessionMemory]]
  ├─ queries[]          ← Lịch sử query (max 10, tránh trùng liên tiếp)
  ├─ turns[]            ← Lịch sử hội thoại (max 20 turns, role: user/assistant)
  ├─ last_image_bytes   ← Ảnh gốc cuối cùng được upload
  ├─ last_result        ← Kết quả phân tích cuối cùng
  └─ updated_at         ← TTL 7 ngày (auto prune)
```

---

## 🧩 Sơ đồ tổng thể

```
                    ┌─────────────┐
                    │  Frontend   │
                    │ index.html  │
                    └──────┬──────┘
                           │ HTTP (FormData)
                    ┌──────▼──────┐
                    │  FastAPI    │
                    │  main.py   │
                    └──┬───┬───┬─┘
                       │   │   │
          ┌────────────┘   │   └────────────────┐
          │                │                    │
   ┌──────▼──────┐  ┌──────▼──────┐   ┌────────▼────────┐
   │DesignCheck  │  │MemoryStore  │   │ InpaintAgent    │
   │   Agent     │  │  (RAM)      │   │ (WillaAI x.ai)    │
   └──┬──┬──┬───┘  └─────────────┘   └──┬──────────────┘
      │  │  │                            │
 ┌────┘  │  └────┐                  ┌───┴──────┐
 │       │       │                  │          │
 ▼       ▼       ▼                  ▼          ▼
RAG    Qwen    Post              ImgBB    api.x.ai
Index  VL API  Process          Upload   /v1/images/edits
(emb)  (Dash   Agent            (host)   (WillaAI model)
       Scope)
```

---

## ⚙️ Các API Key và Model

| Thành phần | API / Model | Key |
|---|---|---|
| Phân tích ảnh | `qwen3-vl-flash` via DashScope | `DASHSCOPE_API_KEY` |
| Chat / Zoom AI | `qwen3-vl-flash` via DashScope | `DASHSCOPE_API_KEY` |
| Sửa ảnh | `grok-imagine-image` via WillaAI (x.ai) | `XAI_API_KEY` |
| Image hosting | ImgBB Upload API | `IMGBB_API_KEY` |
| RAG Embedding | `paraphrase-multilingual-MiniLM-L12-v2` | _(local, offline)_ |
