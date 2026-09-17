"""macOS provider: osascript for volume and windows, ``open`` for open.

No Python dependencies -- everything goes through system binaries, the same
approach ``jarvis-node-setup``'s ``MacOSAudioProvider`` takes with ``afplay``.

Window control needs an Accessibility (TCC) grant for whatever process hosts
the agent. Without it System Events raises, which surfaces as the window
capabilities being absent rather than as mysterious failures.
"""

from __future__ import annotations

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

_LIST_SCRIPT = """
tell application "System Events"
    set out to ""
    repeat with proc in (every process whose background only is false)
        set procName to name of proc
        repeat with w in (every window of proc)
            try
                set out to out & (id of w as string) & tab & procName & tab & ¬
                    (name of w) & tab & (value of attribute "AXMinimized" of w as string) & linefeed
            end try
        end repeat
    end repeat
    return out
end tell
"""

_ACTION_SCRIPT = """
tell application "System Events"
    repeat with proc in (every process whose background only is false)
        repeat with w in (every window of proc)
            try
                if (id of w as string) is "{window_id}" then
                    {body}
                    return "ok"
                end if
            end try
        end repeat
    end repeat
    return "missing"
end tell
"""

_ACTION_BODIES = {
    "minimize": 'set value of attribute "AXMinimized" of w to true',
    "focus": 'perform action "AXRaise" of w\n                    set frontmost of proc to true',
    "close": "click button 1 of w",
}


class MacOSProvider(HostProvider):
    @property
    def platform(self) -> str:
        return "darwin"

    def capabilities(self) -> set[str]:
        names: set[str] = set()
        if shutil.which("open"):
            names.add(OPEN)
        if shutil.which("osascript"):
            names |= {VOLUME_GET, VOLUME_SET}
            if self._accessibility_granted():
                names |= {
                    WINDOWS_LIST,
                    WINDOWS_MINIMIZE,
                    WINDOWS_FOCUS,
                    WINDOWS_CLOSE,
                }
        return self._validated_capabilities(names)

    def _accessibility_granted(self) -> bool:
        """Probe TCC cheaply -- counting processes fails without the grant."""
        try:
            self._osascript('tell application "System Events" to count processes', timeout=5)
        except Exception:
            return False
        return True

    @staticmethod
    def _osascript(script: str, timeout: int = 15) -> str:
        if not shutil.which("osascript"):
            raise NotSupported("osascript unavailable")
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or "osascript failed"
            # -1719/-25211 are the TCC denials; everything else is a real fault.
            if "-1719" in message or "-25211" in message or "not allowed" in message:
                raise NotSupported(f"Accessibility permission required: {message}")
            raise HostOperationFailed(message)
        return result.stdout.strip()

    # ---- volume ---------------------------------------------------------

    def get_volume(self) -> int:
        return int(self._osascript("output volume of (get volume settings)"))

    def _set_volume(self, level: int) -> None:
        self._osascript(f"set volume output volume {level}")

    # ---- windows --------------------------------------------------------

    def list_windows(self) -> list[Window]:
        raw = self._osascript(_LIST_SCRIPT, timeout=30)
        windows: list[Window] = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            win_id, app, title, minimized = parts
            windows.append(
                Window(
                    id=win_id,
                    title=title,
                    app=app,
                    minimized=minimized.lower() == "true",
                )
            )
        return windows

    def _act(self, window_id: str, action: str) -> None:
        script = _ACTION_SCRIPT.format(window_id=window_id, body=_ACTION_BODIES[action])
        if self._osascript(script, timeout=30) == "missing":
            raise WindowNotFound(f"window {window_id} no longer exists")

    def minimize_window(self, window_id: str) -> None:
        self._act(window_id, "minimize")

    def focus_window(self, window_id: str) -> None:
        self._act(window_id, "focus")

    def close_window(self, window_id: str) -> None:
        self._act(window_id, "close")

    # ---- open -----------------------------------------------------------

    def open_target(self, target: str) -> None:
        if not shutil.which("open"):
            raise NotSupported("the `open` binary is unavailable")
        try:
            subprocess.Popen(
                ["open", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise HostOperationFailed(f"could not open {target!r}: {exc}") from exc
