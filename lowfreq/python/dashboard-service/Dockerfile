# Dashboard.Service - FastAPI backend for Dashboard.Web
# Offline build pattern: wheels are pre-downloaded as cp312 manylinux into
# artifacts/wheels/ by scripts/deploy/dashboard_service.sh and installed
# with --no-index so the build needs no network.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies from pre-downloaded Linux wheels (no network needed).
COPY artifacts/wheels/ /wheels/
RUN pip install --no-cache-dir --no-index /wheels/*.whl && rm -rf /wheels

# Copy the package.
COPY dashboard_service/ ./dashboard_service/

EXPOSE 8080

# Run via uvicorn; configuration comes from environment variables.
CMD ["uvicorn", "dashboard_service.main:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--log-level", "info"]
