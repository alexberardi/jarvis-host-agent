"""Linux provider: pactl/amixer for volume, wmctrl/xdotool for windows.

Two Linux realities the contract has to survive:

* **Headless boxes.** A Pi voice node has no display at all, so window
  capabilities are simply absent and ``open`` is best-effort. Volume still
  works, which is the common case for a node.
* **Wayland.** It deliberately forbids one app from enumerating or controlling
  another's windows -- there is no privileged client and no EWMH equivalent.
  That is a security decision upstream, not a missing library, so we report the
  window capabilities as unavailable rather than pretending and failing later.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from ..capabilities import (
    OPEN,
    VOLUME_GET,
    VOLUME_SET,
    WINDOWS_CLOSE,
    WINDOWS_FOCUS,
    WINDOWS_LIST,
    WINDOWS_MINIMIZE,
)
from ..errors import HostOperationFailed, NotSupported, WindowNotFound
from .base import HostProvider, Window

_PACTL_SINK = "@DEFAULT_SINK@"


class LinuxProvider(HostProvider):
    @property
    def platform(self) -> str:
        return "linux"

    def capabilities(self) -> set[str]:
        names: set[str] = set()
        # xdg-open on a headless box exits cleanly having done nothing, and
        # `open` is fire-and-forget, so a caller would see 202 and no effect.
        # Requiring a session makes the absence visible instead.
        if shutil.which("xdg-open") and self._session_available():
            names.add(OPEN)
        if self._mixer() is not None:
            names |= {VOLUME_GET, VOLUME_SET}
        if self._x11_available():
            names |= {WINDOWS_LIST, WINDOWS_MINIMIZE, WINDOWS_FOCUS, WINDOWS_CLOSE}
        return self._validated_capabilities(names)

    # ---- environment probes ---------------------------------------------

    @staticmethod
    def _mixer() -> str | None:
        for binary in ("pactl", "amixer"):
            if shutil.which(binary):
                return binary
        return None

    @staticmethod
    def _session_available() -> bool:
        """Any graphical session -- X11 or Wayland. Enough to launch an app."""
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    @staticmethod
    def _x11_available() -> bool:
        """Window control needs X11 *and* wmctrl. Wayland cannot qualify."""
        if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
            return False
        if not os.environ.get("DISPLAY"):
            return False
        return shutil.which("wmctrl") is not None

    @staticmethod
    def _run(args: list[str], timeout: int = 15) -> str:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            raise HostOperationFailed(
                result.stderr.strip() or f"{args[0]} exited {result.returncode}"
            )
        return result.stdout.strip()

    # ---- volume ---------------------------------------------------------

    def get_volume(self) -> int:
        mixer = self._mixer()
        if mixer is None:
            raise NotSupported("neither pactl nor amixer is installed")
        if mixer == "pactl":
            raw = self._run(["pactl", "get-sink-volume", _PACTL_SINK])
            match = re.search(r"(\d+)%", raw)
            if not match:
                raise HostOperationFailed(f"could not parse pactl output: {raw!r}")
            return min(100, int(match.group(1)))
        raw = self._run(["amixer", "sget", "Master"])
        match = re.search(r"\[(\d+)%\]", raw)
        if not match:
            raise HostOperationFailed(f"could not parse amixer output: {raw!r}")
        return int(match.group(1))

    def _set_volume(self, level: int) -> None:
        mixer = self._mixer()
        if mixer is None:
            raise NotSupported("neither pactl nor amixer is installed")
        if mixer == "pactl":
            self._run(["pactl", "set-sink-volume", _PACTL_SINK, f"{level}%"])
        else:
            self._run(["amixer", "sset", "Master", f"{level}%"])

    # ---- windows --------------------------------------------------------

    def _require_x11(self) -> None:
        if not self._x11_available():
            raise NotSupported(
                "window control needs X11 plus wmctrl; unavailable on this host "
                "(headless, or Wayland, which forbids cross-app window control)"
            )

    def list_windows(self) -> list[Window]:
        self._require_x11()
        windows: list[Window] = []
        for line in self._run(["wmctrl", "-l", "-x"]).splitlines():
            # 0xHANDLE  desktop  CLASS  host  title
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            handle, _desktop, win_class, _host, title = parts
            windows.append(Window(id=handle, title=title, app=win_class, minimized=False))
        return windows

    def _require_window(self, window_id: str) -> None:
        if all(w.id != window_id for w in self.list_windows()):
            raise WindowNotFound(f"window {window_id} no longer exists")

    def minimize_window(self, window_id: str) -> None:
        self._require_x11()
        self._require_window(window_id)
        if not shutil.which("xdotool"):
            raise NotSupported("minimize needs xdotool (wmctrl cannot iconify)")
        self._run(["xdotool", "windowminimize", window_id])

    def focus_window(self, window_id: str) -> None:
        self._require_x11()
        self._require_window(window_id)
        self._run(["wmctrl", "-i", "-a", window_id])

    def close_window(self, window_id: str) -> None:
        self._require_x11()
        self._require_window(window_id)
        # -c is a graceful close request, not a kill.
        self._run(["wmctrl", "-i", "-c", window_id])

    # ---- open -----------------------------------------------------------

    def open_target(self, target: str) -> None:
        if not shutil.which("xdg-open"):
            raise NotSupported("xdg-open is unavailable")
        if not self._session_available():
            raise NotSupported(
                "no graphical session on this host; xdg-open would silently "
                "do nothing (headless node?)"
            )
        try:
            subprocess.Popen(
                ["xdg-open", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise HostOperationFailed(f"could not open {target!r}: {exc}") from exc
