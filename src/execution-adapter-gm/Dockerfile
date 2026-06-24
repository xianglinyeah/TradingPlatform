FROM python:3.12-slim

WORKDIR /app

COPY artifacts/wheels/ /wheels/
RUN pip install --no-cache-dir --no-index /wheels/*.whl && rm -rf /wheels

COPY . .

ENTRYPOINT ["python", "-u", "main.py", "config.yaml"]
