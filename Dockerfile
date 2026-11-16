FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/ ./
RUN pip install --no-cache-dir --no-deps . && useradd --create-home --uid 10001 clipforge && mkdir -p /data/storage && chown -R clipforge:clipforge /data
COPY --from=ui /ui/dist /app/frontend/dist
USER clipforge
ENV DATABASE_URL=sqlite:////data/clipforge.db STORAGE_ROOT=/data/storage
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
