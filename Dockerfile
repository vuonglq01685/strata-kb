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
# docling → rapidocr pulls in full opencv-python, which needs X11 libs
# (libxcb & co.) absent from python:slim. The headless build is cv2
# API-compatible and needs none of them.
RUN pip install --no-cache-dir "$(ls /tmp/dist/*.whl)[ingest]" && rm -rf /tmp/dist \
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless
# Pre-fetch RapidOCR's assets (detector/classifier/recognizer weights, the
# recognition character dict, font) into its own default location under
# site-packages — while still root, which owns that path. The `app` runtime
# user does not: RapidOCR lazily downloads these into its package dir on
# first OCR use, and the character dict specifically has no config override
# to redirect it elsewhere (unlike the model weights, which do). Files
# created here as root stay world-readable, so `app` only ever needs to
# read them at runtime, never write. This constructs the exact engine
# center_kb.ingest.parser configures (backend="torch", lang=["en"]) so the
# pre-fetched files are the ones actually requested later.
RUN python -c "\
from docling.datamodel.accelerator_options import AcceleratorOptions; \
from docling.datamodel.pipeline_options import RapidOcrOptions; \
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel; \
RapidOcrModel(enabled=True, artifacts_path=None, \
    options=RapidOcrOptions(backend='torch', lang=['en']), \
    accelerator_options=AcceleratorOptions())"
USER app
WORKDIR /data
EXPOSE 8321
# The KB repo is mounted at /data; the hub is the repo itself (--hub /data).
CMD ["python", "-m", "center_kb.mcp", "--kb", "/data/.kb", "--hub", "/data", "--transport", "http", "--host", "0.0.0.0"]
