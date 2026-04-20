FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying source to leverage Docker layer cache
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY main.py .

EXPOSE 8000

# Run as non-root user
RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
