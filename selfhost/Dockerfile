FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Domain-specific Android app-link verification belongs to a future release step.
# The installation must never inherit the old deployment's association file.
RUN rm -rf public/.well-known && npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/pyproject.toml ./
COPY server/src ./src
RUN pip install --no-cache-dir .
COPY --from=web /web/dist /app/web-dist
RUN addgroup --system wristmind && adduser --system --ingroup wristmind wristmind \
    && mkdir -p /data/private && chown -R wristmind:wristmind /data
USER wristmind
EXPOSE 8000
CMD ["uvicorn", "wristmind_server.selfhost_app:app", "--host", "0.0.0.0", "--port", "8000"]
