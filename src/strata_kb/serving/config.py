"""config — `ServerConfig`, the settings one MCP or web server runs with.

A plain dataclass: the KB directory, the hub, the transport and the bind
address. `strata_kb.mcp.parse_args()` builds it from the command line; the MCP
server and the `web` app both read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerConfig:
    kb_dir: Path
    hub: str
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8321


def hub_serves_own_checkout(config: ServerConfig) -> bool:
    """True when this server runs inside the hub's own checkout (the HTTP
    server, or stdio with `--kb <hub>/.kb`) -- the only place the Q&A store is
    the one shared copy. A dev repo pointing at a local hub path is refused."""
    from strata_kb import hub as hub_mod

    return (
        hub_mod.is_local_hub(config.hub)
        and Path(config.hub).resolve() == config.kb_dir.resolve().parent
    )
