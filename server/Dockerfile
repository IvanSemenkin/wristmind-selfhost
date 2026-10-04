FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN addgroup --system wristmind && adduser --system --ingroup wristmind wristmind \
    && mkdir -p /data/private && chown -R wristmind:wristmind /data
USER wristmind

EXPOSE 8000
CMD ["uvicorn", "wristmind_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
