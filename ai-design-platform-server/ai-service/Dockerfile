FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY app/ ./app/

# Generated proto stubs are mounted at runtime via docker-compose volume
# The /gen/python path must be in PYTHONPATH for imports
ENV PYTHONPATH="/app:/gen/python"
ENV PYTHONUNBUFFERED=1

EXPOSE 50051

CMD ["python", "-m", "app.main"]
