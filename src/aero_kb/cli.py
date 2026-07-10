from __future__ import annotations

import sys
from pathlib import Path

import typer

from aero_kb import models

# Console Windows mặc định dùng cp1252 → crash UnicodeEncodeError khi in ký
# tự '§'/tiếng Việt có dấu. Ép lại UTF-8 khi stream chưa ở UTF-8 (guarded:
# một số stream test/redirect không có .reconfigure()).
for _stream in (sys.stdout, sys.stderr):
    _enc = getattr(_stream, "encoding", None) or ""
    if _enc.lower().replace("-", "") != "utf8" and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

app = typer.Typer(
    help="AERO-KB — Knowledge Base as Code cho tài liệu hàng không.",
    no_args_is_help=True,
)

context_app = typer.Typer(help="Thao tác với block kb-context (citation máy-đọc-được).")
app.add_typer(context_app, name="context")


@app.callback()
def main() -> None:
    """AERO-KB CLI."""


def _resolve_hub_option(hub: str, quiet: bool = False):
    """'' → None; ngược lại resolve qua hub.resolve_hub (None nếu không truy cập được).

    quiet=True bỏ qua cảnh báo stderr ở đây — dùng khi caller (vd `doctor`,
    qua check_hub) đã tự báo warning riêng, tránh cảnh báo đôi.
    """
    if not hub:
        return None
    from aero_kb.hub import resolve_hub

    handle = resolve_hub(hub)
    if handle is None and not quiet:
        typer.secho(
            f"[warn] không truy cập được hub '{hub}' — chạy tiếp với KB cục bộ",
            fg=typer.colors.YELLOW,
            err=True,
        )
    return handle


@app.command()
def ingest(
    pdf: Path = typer.Argument(..., help="File PDF nguồn"),
    doc_id: str = typer.Option(..., "--id", help="ID tài liệu, vd arinc-424"),
    tags: str = typer.Option("", help="Tags, phân cách bằng dấu phẩy"),
    revision: str = typer.Option("", help="Bản sửa đổi, vd 'Supplement 22'"),
    sections: str = typer.Option(
        "", help="Chỉ scaffold các chương này, vd '5,6' (rỗng = tất cả)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    work_dir: Path = typer.Option(Path(".kb-work"), help="Thư mục cache trung gian"),
    chapter_pattern: str = typer.Option(
        "", help="Regex heading chương (mặc định: 'Chapter N', tự nhớ từ lần ingest trước)"
    ),
    appendix_pattern: str = typer.Option(
        "", help="Regex heading appendix (mặc định: 'Appendix X', tự nhớ từ lần ingest trước)"
    ),
) -> None:
    """Parse PDF → cắt section → sinh L3 + khung L1/L2 chờ summarize."""
    from aero_kb.ingest import parser, scaffold, sectioner

    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    previous = None
    if manifest_path.exists():
        previous = models.load_yaml_model(manifest_path, models.Manifest).ingest
    try:
        heading_config = sectioner.resolve_heading_config(
            chapter_pattern, appendix_pattern, previous
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    doc = parser.load_or_parse(pdf, work_dir / doc_id)
    items = parser.doc_to_items(doc)
    units = sectioner.build_units(items, config=heading_config)

    bm_ids = parser.bookmark_ids(pdf, heading_config)
    if bm_ids:
        for warning in parser.crosscheck({u.id for u in units}, bm_ids):
            typer.secho(f"  [warn] {warning}", fg=typer.colors.YELLOW)

    chapters = {s.strip() for s in sections.split(",") if s.strip()} or None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    report = scaffold.scaffold_doc(
        units,
        doc_id=doc_id,
        title=doc_id if not hasattr(doc, "name") else (getattr(doc, "name", "") or doc_id),
        tags=tag_list,
        revision=revision,
        source_path=pdf,
        kb_dir=kb_dir,
        chapters=chapters,
        heading_config=heading_config,
    )
    typer.echo(
        f"Ingested '{report.doc_id}': {report.n_sections} sections, "
        f"{len(report.files)} files trong {kb_dir / report.doc_id}"
    )
    typer.echo("Tiếp theo: mở Claude Code và chạy skill kb-summarize, rồi `kb build`.")


@app.command()
def status(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Liệt kê các section đang chờ summarize (status=pending)."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        typer.echo("KB trống — chưa có index.yaml.")
        raise typer.Exit(0)
    index = models.load_yaml_model(index_path, models.KBIndex)
    total_pending = 0
    for entry in index.docs:
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        pending = [s for s in manifest.sections if s.status == "pending"]
        total_pending += len(pending)
        typer.echo(
            f"{entry.id}: {len(pending)}/{len(manifest.sections)} section pending"
        )
        for sec in pending:
            typer.echo(f"  - §{sec.id} {sec.title} (file: {sec.file}.md)")
    typer.echo(f"Tổng: {total_pending} section pending.")


@app.command()
def build(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    allow_pending: bool = typer.Option(
        False, "--allow-pending", help="Không fail khi còn section pending"
    ),
) -> None:
    """Validate KB: hết TODO, toàn vẹn bảng, cập nhật token counts."""
    from aero_kb.build import build_kb

    report = build_kb(kb_dir, allow_pending=allow_pending)
    for warning in report.warnings:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(1)

    db_path = kb_dir.resolve().parent / ".kb-work" / "embeddings.db"
    if db_path.exists():
        from aero_kb.embed import default_embedder, ensure_index

        embedder = default_embedder()
        if embedder is not None:
            n = ensure_index(kb_dir, db_path, embedder)
            if n:
                typer.echo(f"embeddings.db: re-embed {n} section.")
    typer.echo("kb build: OK")


@app.command()
def query(
    text: str = typer.Argument(..., help="Câu truy vấn"),
    tags: str = typer.Option("", help="Tags lọc doc, phân cách bằng dấu phẩy"),
    budget: int = typer.Option(2000, help="Token budget cho nội dung trả về"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
    semantic: bool = typer.Option(
        False, "--semantic", help="Ép dùng embedding search (bước 3 routing)"
    ),
) -> None:
    """Tag match → BM25 → trả section L2 trong budget, kèm citation."""
    from aero_kb.query import search

    handle = _resolve_hub_option(hub)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(
        kb_dir, text, tags=tag_list, budget=budget, hub=handle, semantic=semantic
    )
    if not results:
        typer.echo("Không tìm thấy section phù hợp.")
        raise typer.Exit(0)
    for r in results:
        mark = " [remote]" if r.source.startswith("remote:") else ""
        typer.secho(
            f"--- [{r.citation}]{mark} score={r.score:.2f} ~{r.tokens}tk", bold=True
        )
        typer.echo(r.content)
        typer.echo("")


@app.command()
def get(
    doc_id: str = typer.Argument(..., help="ID tài liệu"),
    section: str = typer.Argument(..., help="ID section, vd 5.3 hoặc §5.3"),
    level: str = typer.Option("l2", help="Tầng: l2 hoặc l3"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
) -> None:
    """Lấy chính xác một section ở tầng chỉ định."""
    from aero_kb.query import get_section

    handle = _resolve_hub_option(hub)
    result = get_section(kb_dir, doc_id, section, level=level, hub=handle)
    if result is None:
        typer.secho(f"Không thấy {doc_id} §{section}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"--- [{result.citation}] ~{result.tokens}tk", bold=True)
    typer.echo(result.content)


@app.command()
def stats(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Token size từng tầng, từng tài liệu — theo dõi chi phí."""
    from aero_kb.build import kb_stats

    l0_tokens, docs = kb_stats(kb_dir)
    typer.echo(f"L0 index.yaml: {l0_tokens} tokens")
    if not docs:
        typer.echo("KB trống.")
        raise typer.Exit(0)
    header = f"{'doc':<20} {'sections':>8} {'L1':>8} {'L2':>10} {'L3':>10} {'saving':>8}"
    typer.echo(header)
    for d in docs:
        typer.echo(
            f"{d.doc_id:<20} {d.n_sections:>8} {d.l1_tokens:>8} "
            f"{d.l2_tokens:>10} {d.l3_tokens:>10} {d.saving_pct:>7.1f}%"
        )


@app.command()
def publish(
    hub: str = typer.Option(
        ..., "--hub", envvar="AERO_KB_HUB", help="URL hoặc path kb-hub"
    ),
    repo_id: str = typer.Option(
        "", "--repo-id", help="ID repo trên hub (mặc định: tên thư mục git root)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Publish snapshot L0+L1 của repo này lên federation/<repo-id>/ trên hub."""
    from aero_kb import gitio
    from aero_kb.publish import PublishError
    from aero_kb.publish import publish as publish_kb

    try:
        report = publish_kb(kb_dir, hub, repo_id=repo_id or None)
    except (PublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "push" if report.pushed else "commit tại chỗ (hub không có remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )


@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Refs phân cách dấu phẩy, vd 'arinc-424 §5.3,arinc-424 §5.3.2'"
    ),
    tags: str = typer.Option("", help="Tags, phân cách bằng dấu phẩy"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
) -> None:
    """Sinh block kb-context pin tại HEAD — dán vào Jira ticket."""
    from aero_kb import gitio, kbcontext
    from aero_kb.query import get_section

    try:
        ref_list = [kbcontext.parse_ref(r) for r in refs.split(",") if r.strip()]
        root = gitio.git_root(kb_dir.resolve())
        version = gitio.head_commit(root)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    if not ref_list:
        typer.secho(
            "--refs rỗng — cần ít nhất 1 ref, vd 'arinc-424 §5.3'", fg=typer.colors.RED
        )
        raise typer.Exit(1)

    handle = _resolve_hub_option(hub)
    bad: list[str] = []
    needs_hub = False
    for r in ref_list:
        if r.repo_id:
            found = handle is not None and (
                handle.federation_dir / r.repo_id / "manifests" / f"{r.doc_id}.yaml"
            ).exists()
            needs_hub = True
        else:
            found = get_section(kb_dir, r.doc_id, r.section_id) is not None
            if not found and handle is not None:
                found = (
                    get_section(kb_dir, r.doc_id, r.section_id, hub=handle) is not None
                )
                needs_hub = needs_hub or found
        if not found:
            bad.append(str(r))
    if bad:
        typer.secho(
            f"Ref không resolve được ở worktree: {', '.join(bad)}", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if gitio.is_dirty(root, kb_dir.resolve()):
        typer.secho(
            "[warn] .kb/ có thay đổi chưa commit — hash pin sẽ không chứa thay đổi đó",
            fg=typer.colors.YELLOW,
            err=True,
        )
    hub_version = None
    if needs_hub and handle is not None:
        hub_version = gitio.head_commit(gitio.git_root(handle.root))
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ctx = kbcontext.KBContext(
        version=version, hub_version=hub_version, refs=ref_list, tags=tag_list
    )
    typer.echo(kbcontext.render(ctx))


@app.command()
def resolve(
    source: str = typer.Argument(
        ..., help="File chứa block kb-context (hoặc '-' đọc từ stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
) -> None:
    """Resolve block kb-context: trả section đúng version pin + freshness."""
    from aero_kb import gitio, kbcontext
    from aero_kb.resolve import render_resolved, resolve_refs

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            typer.secho(f"không đọc được file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
    handle = _resolve_hub_option(hub)
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(kb_dir, ctx, hub=handle)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_resolved(results))
    if any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)


@app.command()
def diff(
    doc_id: str = typer.Argument(..., help="ID tài liệu"),
    against: str = typer.Option("HEAD", help="Git rev để so, vd HEAD, a3f9c21"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """So section added/removed/changed giữa worktree và một git rev."""
    from aero_kb import gitio
    from aero_kb.diff import diff_doc, render_diff

    try:
        report = diff_doc(kb_dir, doc_id, against=against)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_diff(report))


@app.command()
def doctor(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    context: str | None = typer.Option(
        None, "--context", help="File chứa block kb-context (hoặc '-' đọc từ stdin)"
    ),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
) -> None:
    """Kiểm tra sức khỏe KB; kèm --context để check staleness của citation."""
    from aero_kb.doctor import check_context, check_hub, check_kb

    issues = check_kb(kb_dir)
    # quiet=True: check_hub() bên dưới tự báo warning "không truy cập được
    # hub" riêng khi cần — tránh in cảnh báo đôi.
    handle = _resolve_hub_option(hub, quiet=True)
    hub_stale = False
    if hub:  # chỉ check hub khi được khai --hub / env AERO_KB_HUB
        repo_root_name = None
        try:
            from aero_kb import gitio as _gitio

            repo_root_name = _gitio.git_root(kb_dir.resolve()).name
        except Exception:
            pass
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_root_name)
        issues += hub_issues
    has_stale = False
    if context is not None:
        text = sys.stdin.read() if context == "-" else Path(context).read_text(
            encoding="utf-8"
        )
        ctx_issues, results = check_context(kb_dir, text, hub=handle)
        issues += ctx_issues
        has_stale = any(r.status == "stale" for r in results)

    for issue in issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"[{issue.level}] {issue.message}", fg=color)
    if any(i.level == "error" for i in issues):
        raise typer.Exit(1)
    if has_stale or hub_stale:
        raise typer.Exit(2)
    typer.echo("kb doctor: OK")
