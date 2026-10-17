FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev, no virtualenv in container, skip project install)
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# Copy application code
COPY api/ ./api/
COPY core/ ./core/
COPY graph/ ./graph/
COPY models/ ./models/
COPY pipeline/ ./pipeline/
COPY vector/ ./vector/
COPY worker/ ./worker/
COPY scripts/ ./scripts/

# Expose port
EXPOSE 8000

# Run the API. The worker runs from the same image: python -m worker.consumer
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
