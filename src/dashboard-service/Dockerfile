# Dashboard.Service - FastAPI backend for Dashboard.Web
# Uses python:3.12-slim (already cached locally on this host). Pure-Python
# deps so 3.11 vs 3.12 doesn't matter; 3.12 avoids an extra base-image pull.
FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first to leverage Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the package.
COPY dashboard_service/ ./dashboard_service/

EXPOSE 8080

# Run via uvicorn; configuration comes from environment variables.
CMD ["uvicorn", "dashboard_service.main:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--log-level", "info"]
