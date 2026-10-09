FROM python:3.12-slim

# Extra Tesseract language packs, space separated (e.g. "hin kan"). English is always installed.
ARG TESS_LANGS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
       $(for l in $TESS_LANGS; do echo "tesseract-ocr-$l"; done) \
       libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so code edits don't invalidate the layer.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install -e ".[dev]" \
    && rm -rf app

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
