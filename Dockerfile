# uv-based image; single stage karena PoC.
FROM python:3.12-slim

# Docling PDF backend butuh X11 + graphics libs (libxcb untuk pypdfium2 image handling,
# libgl/libglib untuk OpenCV transitively pulled by docling). DOCX-only tidak butuh,
# tapi karena image sama dipakai untuk DOCX dan PDF, install semua.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxcb1 libxext6 libxrender1 libsm6 libice6 \
        libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# uv binary — official image too heavy untuk PoC; copy dari distroless image kecil
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Copy lock & manifest first untuk leverage layer cache
COPY pyproject.toml ./
# uv tidak butuh lock; resolve on install
RUN uv sync --no-dev

# Pre-download Docling models ke image cache.
# - layout + tableformer: layout detection + table parsing (~500MB, HuggingFace)
# - rapidocr: OCR engine (PP-OCRv4 det+cls+rec, ~40MB, ModelScope) — even untuk born-digital PDF, OCR model di-init saat pipeline load
# Tanpa ini, first PDF butuh 50-70s tambahan untuk download model dari runtime.
RUN uv run docling-tools models download layout tableformer rapidocr

# Copy source last (changes most often)
COPY *.py ./
COPY static/ ./static/

# Default port — uvicorn untuk API service, override CMD untuk worker
EXPOSE 8000

# Default CMD = API. docker-compose overrides ke "python worker.py" untuk worker service.
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
