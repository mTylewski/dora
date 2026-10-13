# Production image: web app + worker (same image, different command).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin claims
WORKDIR /app

COPY pyproject.toml ./
COPY calculator ./calculator
COPY pipeline ./pipeline
COPY app ./app
RUN pip install ".[ocr]"

COPY config ./config
COPY prompts ./prompts
COPY clauses ./clauses
COPY schemas ./schemas
COPY templates ./templates
COPY web ./web

USER claims
EXPOSE 8000
CMD ["uvicorn", "app.main:build", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
