# Build stage: build the wheel from source.
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

# Runtime stage: wheel + [ingest] extra (docling). git is required by
# center_kb.gitio (hub clone/pull, kb-context pinning).
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home app
COPY --from=build /dist /tmp/dist
RUN pip install --no-cache-dir "$(ls /tmp/dist/*.whl)[ingest]" && rm -rf /tmp/dist
USER app
WORKDIR /data
EXPOSE 8321
# The KB repo is mounted at /data; the hub is the repo itself (--hub /data).
CMD ["python", "-m", "center_kb.mcp", "--kb", "/data/.kb", "--hub", "/data", "--transport", "http", "--host", "0.0.0.0"]
