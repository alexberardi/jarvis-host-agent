"""Provider selection.

``JARVIS_HOST_OS`` overrides detection, mirroring ``JARVIS_NODE_OS`` in
``jarvis-node-setup``'s ``PlatformFactory`` so the two behave alike.

Unlike the node's factory there is no silent fallback: an unrecognised platform
raises instead of quietly returning the Linux provider. The node could get away
with defaulting because a wrong audio provider degrades; here a wrong provider
would shell out to the wrong binaries and report capabilities it does not have.
"""

from __future__ import annotations

import platform as _platform

from .base import HostProvider
from .linux import LinuxProvider
from .macos import MacOSProvider
from .windows import WindowsProvider

PROVIDERS: dict[str, type[HostProvider]] = {
    "windows": WindowsProvider,
    "darwin": MacOSProvider,
    "linux": LinuxProvider,
}


def detect_platform(override: str | None = None) -> str:
    name = (override or "").strip().lower() or _platform.system().lower()
    if name not in PROVIDERS:
        raise RuntimeError(f"unsupported platform {name!r}; expected one of {sorted(PROVIDERS)}")
    return name


def create_provider(override: str | None = None) -> HostProvider:
    return PROVIDERS[detect_platform(override)]()
