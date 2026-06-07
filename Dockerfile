# syntax=docker/dockerfile:1.4
# Build nhanh hơn: DOCKER_BUILDKIT=1 docker compose build ai-server
# Lần đầu ~5–10 phút (torch + sentence-transformers); lần sau chỉ vài giây nếu requirements không đổi.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PUBLIC_BASE_URL=https://your-domain.com

WORKDIR /app

# Gói hệ thống — layer riêng, ít đổi.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# --- ML deps (layer cache: chỉ rebuild khi requirements thay đổi) ---
COPY backend/requirements.txt /app/backend/requirements.txt

# Torch CPU trước (nhỏ hơn CUDA) → pip không tải lại torch khi cài sentence-transformers.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r /app/backend/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# FAISS index — chỉ rebuild khi design_rules hoặc script index đổi (không rebuild khi sửa main.py).
COPY design_rules /app/design_rules
COPY backend/knowledge_base /app/backend/knowledge_base
RUN --mount=type=cache,target=/root/.cache/pip \
    python /app/backend/knowledge_base/build_index.py

# App source (đổi code thường xuyên — để cuối).
COPY backend /app/backend
COPY frontend /app/frontend

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
