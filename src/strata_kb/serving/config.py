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
