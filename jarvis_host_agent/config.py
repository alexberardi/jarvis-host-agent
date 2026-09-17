"""Agent configuration.

Defaults are chosen so an unconfigured agent is safe rather than convenient:
loopback-only bind, and a token that is generated once and persisted 0600
instead of a blank default that would leave the machine open.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 7724
TOKEN_FILENAME = "host-agent.token"


def _token_path() -> Path:
    root = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
    return root / TOKEN_FILENAME


def get_or_create_token() -> str:
    """Read the shared token, creating it on first run.

    Mirrors ``jarvis-node-setup``'s ``db.py`` key handling. Note the chmod is a
    no-op on Windows -- see the README; an ACL is the Windows equivalent and is
    tracked separately.
    """
    override = os.environ.get("JARVIS_HOST_AGENT_TOKEN", "").strip()
    if override:
        return override

    path = _token_path()
    if path.exists():
        existing = path.read_text().strip()
        if existing:
            return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    token: str
    platform_override: str | None

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            # Loopback by default. Widening this exposes volume and window
            # control to the LAN; the co-located-with-the-node design means you
            # should not need to.
            host=os.environ.get("JARVIS_HOST_AGENT_BIND", "127.0.0.1"),
            port=int(os.environ.get("JARVIS_HOST_AGENT_PORT", DEFAULT_PORT)),
            token=get_or_create_token(),
            platform_override=os.environ.get("JARVIS_HOST_OS") or None,
        )
