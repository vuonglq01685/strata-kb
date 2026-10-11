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
