import typer

app = typer.Typer(
    help="AERO-KB — Knowledge Base as Code cho tài liệu hàng không.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """AERO-KB CLI."""
