from pathlib import Path


def build_code_repo(root: Path) -> Path:
    """A deliberately multi-stack repo: Python + Node/React + Java + Docker +
    migrations + OpenAPI + CI. Every extractor finds something here."""
    (root / "src" / "airspace").mkdir(parents=True)
    (root / "src" / "airspace" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "airspace" / "service.py").write_text(
        '"""Airspace approval service."""\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "airspace"\nversion = "1.0.0"\n'
        'dependencies = ["fastapi>=0.110", "pydantic>=2.7"]\n'
        "\n[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "package.json").write_text(
        '{\n  "name": "dashboard",\n  "dependencies": {"react": "^18.2.0"},\n'
        '  "devDependencies": {"eslint": "^9.0.0"},\n'
        '  "scripts": {"build": "vite build", "test": "vitest run",\n'
        '              "lint": "eslint .", "start": "vite"}\n}\n',
        encoding="utf-8",
    )
    (root / "pom.xml").write_text(
        '<?xml version="1.0"?>\n<project><dependencies>'
        "<dependency><groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId>"
        "<version>3.2.0</version></dependency>"
        "</dependencies></project>\n",
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        "volumes:\n"
        "  pgdata: {}\n"
        "services:\n"
        "  airspace-service:\n"
        "    image: airspace:1.0\n"
        '    ports: ["8080:8080"]\n'
        "    depends_on: [postgres]\n"
        "    environment:\n"
        "      AIRSPACE_DB_URL: postgres://db/airspace\n"
        "      KAFKA_BROKER_URL: kafka:9092\n"
        "    healthcheck:\n"
        '      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]\n'
        "    deploy:\n"
        "      resources:\n"
        "        reservations:\n"
        "          devices:\n"
        "            - driver: nvidia\n"
        "              capabilities: [gpu]\n"
        "  postgres:\n"
        "    image: postgres:16\n"
        '    ports: ["5432:5432"]\n'
        "    volumes:\n"
        "      - pgdata:/var/lib/postgresql/data\n"
        "      - ./init:/docker-entrypoint-initdb.d\n"
        "  gpuworker:\n"
        "    image: gpuworker:1.0\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "curl -s http://localhost/health | grep -q ok"]\n',
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        "FROM python:3.12-slim\nEXPOSE 8080\nCMD [\"uvicorn\", \"airspace:app\"]\n",
        encoding="utf-8",
    )
    (root / ".env.example").write_text(
        "AIRSPACE_DB_URL=postgres://localhost/airspace\n"
        "KAFKA_BROKER_URL=localhost:9092\n"
        "S3_BUCKET=airspace-assets\n"
        "SECRET_KEY=do-not-ship-this-value\n",
        encoding="utf-8",
    )
    migrations = root / "db" / "migration"
    migrations.mkdir(parents=True)
    (migrations / "V1__create_airspace.sql").write_text(
        "CREATE TABLE restrictive_airspace (\n"
        "  id BIGSERIAL PRIMARY KEY,\n"
        "  designation VARCHAR(20) NOT NULL,\n"
        "  airspace_type CHAR(1) NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    (migrations / "V2__add_effective_date.sql").write_text(
        "ALTER TABLE restrictive_airspace ADD COLUMN effective_date DATE;\n",
        encoding="utf-8",
    )
    (root / "openapi.yaml").write_text(
        "openapi: 3.0.0\n"
        "servers:\n  - url: https://api.example.com/v1\n"
        "paths:\n"
        "  /airspace:\n"
        "    get:\n      tags: [airspace]\n      summary: List airspace\n"
        "    post:\n      tags: [airspace]\n      summary: Create airspace\n",
        encoding="utf-8",
    )
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pip install -e .\n"
        "      - run: pytest -q --cov=airspace\n"
        "      - run: ruff check src\n",
        encoding="utf-8",
    )
    # Noise that must be ignored by the tree extractor.
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "node_modules" / "left-pad" / "index.js").write_text("", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    return root
