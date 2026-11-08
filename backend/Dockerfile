FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY app ./app
RUN uv run playwright install --with-deps chromium
RUN mkdir -p /app/artifacts /app/data
ENV ARTIFACT_DIR=/app/artifacts
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
