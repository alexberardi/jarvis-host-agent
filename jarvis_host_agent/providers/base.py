"""The host provider contract.

This ABC is the anti-drift mechanism, so read the shape before adding to it.

Shared semantics are implemented **here as concrete template methods**; only
the genuinely platform-specific step is abstract. Clamping, for instance, lives
in ``set_volume`` and the abstract hook is ``_set_volume``, which is documented
to receive an already-valid level. That is deliberate: if each provider clamped
for itself, three implementations would eventually disagree about whether 150
means 100 or an error, and no amount of docstring would catch it. With one
implementation there is nothing to diverge.

**Providers must be constructible on any OS.** Contract tests instantiate all
three on whatever machine CI is running, so ``__init__`` must not import
platform modules, probe hardware, or shell out. Do that work lazily inside the
methods (and inside ``capabilities``, which is called per request).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..capabilities import KNOWN_CAPABILITIES

VOLUME_MIN = 0
VOLUME_MAX = 100


@dataclass(frozen=True)
class Window:
    """One top-level window.

    ``id`` is an opaque, platform-defined handle as a string (HWND on Windows,
    an X11 window id on Linux, a CGWindowID on macOS). Callers must treat it as
    a cookie from ``list_windows`` and must not parse it. Ids are only valid
    until the window closes.
    """

    id: str
    title: str
    app: str
    minimized: bool


class HostProvider(ABC):
    """Everything the agent can do to the machine it runs on."""

    # ---- identity -------------------------------------------------------

    @property
    @abstractmethod
    def platform(self) -> str:
        """``"windows"``, ``"darwin"`` or ``"linux"``.

        Matches ``platform.system().lower()`` so it lines up with the node's
        existing command gating in ``services/command_store_service.py``.
        """

    @abstractmethod
    def capabilities(self) -> set[str]:
        """Names from ``KNOWN_CAPABILITIES`` that work on this host *right now*.

        Evaluated per request rather than cached, because the answer genuinely
        changes at runtime: a macOS Accessibility grant can be revoked, and a
        Linux box can gain a compositor between calls.
        """

    # ---- volume ---------------------------------------------------------

    def set_volume(self, level: int) -> int:
        """Set master volume, clamping out-of-range values to the nearest bound.

        Returns the level actually applied, so a caller asking for 150 can see
        it got 100. Providers override ``_set_volume``, never this.
        """
        applied = max(VOLUME_MIN, min(VOLUME_MAX, int(level)))
        self._set_volume(applied)
        return applied

    @abstractmethod
    def get_volume(self) -> int:
        """Current master volume as an int 0-100."""

    @abstractmethod
    def _set_volume(self, level: int) -> None:
        """Apply a master volume level.

        ``level`` is guaranteed to be an int within [0, 100] -- ``set_volume``
        has already clamped it. Do not re-clamp or validate; a provider that
        does is duplicating a decision that is not its to make.
        """

    # ---- windows --------------------------------------------------------

    @abstractmethod
    def list_windows(self) -> list[Window]:
        """Top-level windows, most recently focused first where the platform says."""

    @abstractmethod
    def minimize_window(self, window_id: str) -> None:
        """Minimise/hide a window. Raises ``WindowNotFound`` if it is gone."""

    @abstractmethod
    def focus_window(self, window_id: str) -> None:
        """Raise and focus a window. Raises ``WindowNotFound`` if it is gone."""

    @abstractmethod
    def close_window(self, window_id: str) -> None:
        """Request a graceful close -- never a kill. ``WindowNotFound`` if gone."""

    # ---- open -----------------------------------------------------------

    @abstractmethod
    def open_target(self, target: str) -> None:
        """Hand a path or URI to the OS handler and return immediately.

        Fire-and-forget by contract: no provider waits for or reports on the
        launched process. Confirming a GUI app actually came up is unreliable
        across all three platforms, so the contract does not promise it. A
        return means "the OS accepted the request", nothing more.
        """

    # ---- shared helper --------------------------------------------------

    def _validated_capabilities(self, names: set[str]) -> set[str]:
        """Guard against typo'd capability names escaping a provider."""
        unknown = names - KNOWN_CAPABILITIES
        if unknown:
            raise ValueError(f"unknown capability names: {sorted(unknown)}")
        return names
