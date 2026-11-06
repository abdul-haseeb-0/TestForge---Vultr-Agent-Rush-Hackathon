FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY app ./app
RUN mkdir -p /app/artifacts /app/data
ENV ARTIFACT_DIR=/app/artifacts
ENV DATABASE_URL=sqlite:////app/data/testforge.db
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
