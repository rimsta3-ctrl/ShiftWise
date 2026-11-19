FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY models.py scheduler.py extractor.py graph.py api.py ./

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"

# GOOGLE_API_KEY is injected at runtime (docker run --env-file .env), never baked into the image
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
