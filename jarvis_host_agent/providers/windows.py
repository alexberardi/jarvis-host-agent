"""Windows provider: pycaw for volume, Win32 for windows, os.startfile for open.

Everything imports lazily -- see the note in ``base`` about providers being
constructible on any OS so the contract tests can reach them from Linux CI.
"""

from __future__ import annotations

import os

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


class WindowsProvider(HostProvider):
    @property
    def platform(self) -> str:
        return "windows"

    def capabilities(self) -> set[str]:
        names: set[str] = {OPEN}
        # Probe the actual endpoint, not merely whether pycaw imports. A machine
        # with no playback device -- a headless VM, a server, some RDP sessions --
        # has the library and no audio, and reporting volume support there means
        # a caller gets a COMError where it expected a level.
        if self._volume_available():
            names |= {VOLUME_GET, VOLUME_SET}
        if self._win32() is not None:
            names |= {WINDOWS_LIST, WINDOWS_MINIMIZE, WINDOWS_FOCUS, WINDOWS_CLOSE}
        return self._validated_capabilities(names)

    # ---- lazy platform handles -----------------------------------------

    @staticmethod
    def _volume_module():
        try:
            from ctypes import POINTER, cast  # noqa: F401

            from comtypes import CLSCTX_ALL  # noqa: F401
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # noqa: F401
        except Exception:
            return None
        return (AudioUtilities, IAudioEndpointVolume, CLSCTX_ALL, cast, POINTER)

    @staticmethod
    def _win32():
        try:
            import win32con
            import win32gui
        except Exception:
            return None
        return (win32gui, win32con)

    def _volume_available(self) -> bool:
        try:
            self._endpoint()
        except Exception:
            return False
        return True

    def _endpoint(self):
        mod = self._volume_module()
        if mod is None:
            raise NotSupported("pycaw/comtypes unavailable; cannot reach WASAPI")
        AudioUtilities, IAudioEndpointVolume, CLSCTX_ALL, cast, POINTER = mod
        try:
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except OSError as exc:
            # COMError subclasses OSError. "Element not found" means there is no
            # default render endpoint at all -- an absent capability, not a fault.
            raise NotSupported(f"no usable audio endpoint on this host: {exc}") from exc

    # ---- volume ---------------------------------------------------------

    def get_volume(self) -> int:
        endpoint = self._endpoint()
        return round(endpoint.GetMasterVolumeLevelScalar() * 100)

    def _set_volume(self, level: int) -> None:
        self._endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)

    # ---- windows --------------------------------------------------------

    def list_windows(self) -> list[Window]:
        handles = self._win32()
        if handles is None:
            raise NotSupported("pywin32 unavailable; cannot enumerate windows")
        win32gui, _ = handles

        found: list[Window] = []

        def collect(hwnd: int, _ctx: object) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            found.append(
                Window(
                    id=str(hwnd),
                    title=title,
                    app=win32gui.GetClassName(hwnd) or "",
                    minimized=bool(win32gui.IsIconic(hwnd)),
                )
            )

        win32gui.EnumWindows(collect, None)
        return found

    def _hwnd(self, window_id: str) -> int:
        handles = self._win32()
        if handles is None:
            raise NotSupported("pywin32 unavailable; cannot control windows")
        win32gui, _ = handles
        try:
            hwnd = int(window_id)
        except ValueError as exc:
            raise WindowNotFound(f"not a window handle: {window_id!r}") from exc
        if not win32gui.IsWindow(hwnd):
            raise WindowNotFound(f"window {window_id} no longer exists")
        return hwnd

    def minimize_window(self, window_id: str) -> None:
        win32gui, win32con = self._win32()
        win32gui.ShowWindow(self._hwnd(window_id), win32con.SW_MINIMIZE)

    def focus_window(self, window_id: str) -> None:
        win32gui, win32con = self._win32()
        hwnd = self._hwnd(window_id)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)

    def close_window(self, window_id: str) -> None:
        win32gui, win32con = self._win32()
        # WM_CLOSE asks the app to close and lets it prompt to save. Never
        # TerminateProcess -- a voice command must not be able to lose work.
        win32gui.PostMessage(self._hwnd(window_id), win32con.WM_CLOSE, 0, 0)

    # ---- open -----------------------------------------------------------

    def open_target(self, target: str) -> None:
        try:
            os.startfile(target)  # noqa: S606 - the OS handler is the point
        except OSError as exc:
            raise HostOperationFailed(f"could not open {target!r}: {exc}") from exc
