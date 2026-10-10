#!/usr/bin/env python3
"""Perf bench for the hub's read paths — run manually, NOT a CI gate.

    python scripts/perf_web_bench.py                      # 2,000 sections
    python scripts/perf_web_bench.py --repos 20 --docs 5  # 10,000 sections

Builds a synthetic hub (index revisions left empty, the `-code` shape that
makes `load_federation` open every manifest), then measures, median of
`--runs`:

- `load_federation` in-process (first call, then repeated);
- each web route over a real uvicorn server;
- `/api/health` latency while each slow route is in flight — the event-loop
  blocking the 2026-10-10 review measured at 9 s for `/ui` (§6.2 F3).
"""

from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

TOKEN = "bench-token-" + "0" * 40


def build_hub(root: Path, repos: int, docs: int, sections: int, per_file: int) -> None:
    from strata_kb import models
    from strata_kb.federation import FederationMeta, write_federation_index

    (root / ".kb").mkdir(parents=True)
    models.save_yaml_model(root / ".kb" / "index.yaml", models.KBIndex())
    fed = root / "federation"
    for r in range(repos):
        rid = f"repo-{r:02d}"
        entry = fed / rid
        index = models.KBIndex()
        for d in range(docs):
            doc_id = f"doc-{r:02d}-{d:02d}"
            doc_dir = entry / doc_id
            doc_dir.mkdir(parents=True)
            secs = []
            files: dict[str, list[str]] = {}
            for s in range(sections):
                sid = f"{s // 10 + 1}.{s % 10 + 1}"
                fname = f"ch{s // per_file + 1}"
                secs.append(
                    models.SectionEntry(
                        id=sid,
                        title=f"Section {sid} airspace records",
                        summary=f"Summary of {doc_id} section {sid}: designation and type.",
                        status="summarized",
                        file=fname,
                    )
                )
                files.setdefault(fname, []).append(
                    f"## {sid} Section {sid} airspace records\n\n"
                    + f"Condensed text about restrictive airspace {sid} in {doc_id}. "
                    * 6
                    + "\n"
                )
            for fname, bodies in files.items():
                text = "\n".join(bodies)
                (doc_dir / f"{fname}.md").write_text(
                    text, encoding="utf-8", newline="\n"
                )
                (doc_dir / f"{fname}.raw.md").write_text(
                    text * 2, encoding="utf-8", newline="\n"
                )
            models.save_yaml_model(
                doc_dir / "_manifest.yaml",
                models.Manifest(
                    id=doc_id, title=f"Document {doc_id}", revision="r1", sections=secs
                ),
            )
            index.docs.append(
                models.IndexEntry(
                    id=doc_id,
                    title=f"Document {doc_id}",
                    tags=[f"t{d}", "airspace"],
                    summary="A synthetic document.",
                )
            )
        models.save_yaml_model(entry / "index.yaml", index)
        models.save_yaml_model(
            entry / "_meta.yaml",
            FederationMeta(
                repo_id=rid,
                source_commit="abc1234",
                published_at="2026-10-10T00:00:00+00:00",
            ),
        )
    write_federation_index(fed)
    # A served checkout's files are minutes-to-days old; a just-written file
    # sits inside the YAML cache's 2 s racy window and is always re-parsed.
    past = time.time() - 3600
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (past, past))
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.name=b", "-c", "user.email=b@b", "commit", "-qm", "hub"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True)  # noqa: S603, S607 -- fixed argv; git from PATH, bench only


def _median_ms(fn, runs: int) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", type=int, default=8)
    ap.add_argument("--docs", type=int, default=5)
    ap.add_argument("--sections", type=int, default=50)
    ap.add_argument("--per-file", type=int, default=10)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--port", type=int, default=8399)
    args = ap.parse_args()

    import httpx
    import uvicorn

    from strata_kb.federation import load_federation
    from strata_kb.mcp import ServerConfig
    from strata_kb.web.app import create_app

    tmp = Path(tempfile.mkdtemp(prefix="kb-web-bench-"))
    try:
        hub = tmp / "hub"
        build_hub(hub, args.repos, args.docs, args.sections, args.per_file)
        total = args.repos * args.docs * args.sections
        print(
            f"hub: {args.repos} repos × {args.docs} docs × {args.sections} sections "
            f"= {total} sections, {args.per_file}/file"
        )

        t0 = time.perf_counter()
        load_federation(hub / "federation")
        first = (time.perf_counter() - t0) * 1000
        warm = _median_ms(lambda: load_federation(hub / "federation"), args.runs)
        print(
            f"load_federation           first {first:8.1f} ms   repeat {warm:8.1f} ms"
        )

        config = ServerConfig(kb_dir=hub / ".kb", hub=str(hub))
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(config, TOKEN),
                host="127.0.0.1",
                port=args.port,
                log_level="warning",
                proxy_headers=False,
            )
        )
        threading.Thread(target=server.run, daemon=True).start()
        base = f"http://127.0.0.1:{args.port}"
        auth = {"Authorization": f"Bearer {TOKEN}"}
        for _ in range(100):
            try:
                httpx.get(f"{base}/api/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.1)

        doc = "doc-00-00"
        routes = {
            "/api/search?q=airspace": "/api/search?q=restrictive+airspace",
            "/api/docs": "/api/docs",
            "/api/docs/<doc>": f"/api/docs/{doc}",
            "/api/docs/<doc>/sections/<s>": f"/api/docs/{doc}/sections/1.1",
            "/ui?q=airspace": "/ui?q=restrictive+airspace",
            "/ui": "/ui",
            "/ui/docs": "/ui/docs",
            "/ui/docs/<doc>/<s>": f"/ui/docs/{doc}/1.1",
        }
        with httpx.Client(base_url=base, headers=auth, timeout=120) as c:
            c.get("/api/search?q=warmup")  # index build happens once, not per route
            for label, path in routes.items():
                ms = _median_ms(lambda p=path: c.get(p).raise_for_status(), args.runs)
                probe: list[float] = []

                def slow(p=path):
                    with httpx.Client(base_url=base, headers=auth, timeout=120) as c2:
                        c2.get(p)

                th = threading.Thread(target=slow)
                th.start()
                time.sleep(0.02)
                t0 = time.perf_counter()
                httpx.get(f"{base}/api/health", timeout=120)
                probe.append((time.perf_counter() - t0) * 1000)
                th.join()
                print(
                    f"{label:32s} {ms:8.1f} ms   /api/health meanwhile {probe[0]:8.1f} ms"
                )
        server.should_exit = True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
