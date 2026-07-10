from __future__ import annotations

import sys
from pathlib import Path

import typer

from aero_kb import models

app = typer.Typer(
    help="AERO-KB — Knowledge Base as Code cho tài liệu hàng không.",
    no_args_is_help=True,
)

context_app = typer.Typer(help="Thao tác với block kb-context (citation máy-đọc-được).")
app.add_typer(context_app, name="context")


@app.callback()
def main() -> None:
    """AERO-KB CLI."""


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
) -> None:
    """Parse PDF → cắt section → sinh L3 + khung L1/L2 chờ summarize."""
    from aero_kb.ingest import parser, scaffold, sectioner

    doc = parser.load_or_parse(pdf, work_dir / doc_id)
    items = parser.doc_to_items(doc)
    units = sectioner.build_units(items)

    bm_ids = parser.bookmark_ids(pdf)
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
    typer.echo("kb build: OK")


@app.command()
def query(
    text: str = typer.Argument(..., help="Câu truy vấn"),
    tags: str = typer.Option("", help="Tags lọc doc, phân cách bằng dấu phẩy"),
    budget: int = typer.Option(2000, help="Token budget cho nội dung trả về"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Tag match → BM25 → trả section L2 trong budget, kèm citation."""
    from aero_kb.query import search

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(kb_dir, text, tags=tag_list, budget=budget)
    if not results:
        typer.echo("Không tìm thấy section phù hợp.")
        raise typer.Exit(0)
    for r in results:
        typer.secho(f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk", bold=True)
        typer.echo(r.content)
        typer.echo("")


@app.command()
def get(
    doc_id: str = typer.Argument(..., help="ID tài liệu"),
    section: str = typer.Argument(..., help="ID section, vd 5.3 hoặc §5.3"),
    level: str = typer.Option("l2", help="Tầng: l2 hoặc l3"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Lấy chính xác một section ở tầng chỉ định."""
    from aero_kb.query import get_section

    result = get_section(kb_dir, doc_id, section, level=level)
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


@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Refs phân cách dấu phẩy, vd 'arinc-424 §5.3,arinc-424 §5.3.2'"
    ),
    tags: str = typer.Option("", help="Tags, phân cách bằng dấu phẩy"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
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

    bad = [str(r) for r in ref_list
           if get_section(kb_dir, r.doc_id, r.section_id) is None]
    if bad:
        typer.secho(
            f"Ref không resolve được ở worktree: {', '.join(bad)}", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if gitio.is_dirty(root, kb_dir.resolve()):
        typer.secho(
            "[warn] .kb/ có thay đổi chưa commit — hash pin sẽ không chứa thay đổi đó",
            fg=typer.colors.YELLOW,
        )
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ctx = kbcontext.KBContext(version=version, refs=ref_list, tags=tag_list)
    typer.echo(kbcontext.render(ctx))


@app.command()
def resolve(
    source: str = typer.Argument(
        ..., help="File chứa block kb-context (hoặc '-' đọc từ stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Resolve block kb-context: trả section đúng version pin + freshness."""
    from aero_kb import gitio, kbcontext
    from aero_kb.resolve import render_resolved, resolve_refs

    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(kb_dir, ctx)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_resolved(results, ctx.version))
    if any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)
