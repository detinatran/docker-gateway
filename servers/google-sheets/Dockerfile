FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir mcp-google-sheets

COPY entrypoint.py /app/entrypoint.py

# Default to stdio transport; Docker MCP Gateway will speak over stdio.
ENTRYPOINT ["python", "-u", "/app/entrypoint.py"]
