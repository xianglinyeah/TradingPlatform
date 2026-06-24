FROM python:3.11

WORKDIR /app

# Copy local pre-downloaded dependencies (offline deployment)
# These are prepared by scripts/deploy/prepare_offline_deps.sh
COPY local-packages/ /tmp/local-packages/

# Install dependencies from local packages (no network required)
RUN pip install --no-cache-dir /tmp/local-packages/*.whl && \
    rm -rf /tmp/local-packages

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Volume for logs and data
VOLUME ["/app/logs", "/app/config"]

# Default command - can be overridden
CMD ["python", "main.py", "live", "--config", "config/live-mock.yaml"]
