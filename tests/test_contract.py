"""The contract suite: one set of assertions, run against every provider.

This is the file that makes "three implementations, one behaviour" true. It
runs on any OS, so a Windows-only mistake is caught by Linux CI. Anything
platform-specific belongs in test_native.py instead.
"""

from __future__ import annotations

import inspect

import pytest

from jarvis_host_agent.capabilities import KNOWN_CAPABILITIES
from jarvis_host_agent.providers.base import HostProvider
from jarvis_host_agent.providers.factory import PROVIDERS, create_provider, detect_platform

ALL_PROVIDER_CLASSES = list(PROVIDERS.values())


@pytest.fixture(params=ALL_PROVIDER_CLASSES, ids=lambda c: c.__name__)
def provider_class(request) -> type[HostProvider]:
    return request.param


class TestStructuralConformance:
    """Guards that hold for every provider on every OS."""

    def test_constructible_off_platform(self, provider_class) -> None:
        # If this fails, __init__ is touching the platform -- which also breaks
        # every other cross-platform test below.
        provider_class()

    def test_implements_every_abstract_method(self, provider_class) -> None:
        missing = getattr(provider_class(), "__abstractmethods__", set())
        assert not missing, f"{provider_class.__name__} leaves {missing} abstract"

    def test_platform_name_matches_factory_key(self, provider_class) -> None:
        instance = provider_class()
        assert PROVIDERS[instance.platform] is provider_class

    def test_platform_name_is_platform_system_lower(self, provider_class) -> None:
        # Lines up with the node's command gating, which compares against
        # platform.system().lower() in services/command_store_service.py.
        assert provider_class().platform in {"windows", "darwin", "linux"}

    def test_exposes_no_public_api_beyond_the_abc(self, provider_class) -> None:
        """A provider must not grow public methods of its own.

        A Windows-only public method is exactly how commands start depending on
        one platform, which is the drift this whole design exists to prevent.
        Platform helpers belong behind a leading underscore.
        """
        allowed = {name for name, _ in inspect.getmembers(HostProvider) if not name.startswith("_")}
        actual = {
            name for name, _ in inspect.getmembers(provider_class) if not name.startswith("_")
        }
        assert actual <= allowed, f"extra public API: {sorted(actual - allowed)}"

    def test_does_not_override_clamping(self, provider_class) -> None:
        """set_volume is the single clamp site; providers override _set_volume."""
        assert provider_class.set_volume is HostProvider.set_volume


class TestCapabilityNames:
    def test_reported_capabilities_are_all_known(self, provider_class) -> None:
        # Runs against the real host probes, so on CI this also proves the
        # probes do not explode when their tooling is absent.
        reported = provider_class().capabilities()
        assert reported <= KNOWN_CAPABILITIES


class TestVolumeSemantics:
    """Clamping is defined once in the base class, so test it once."""

    @pytest.mark.parametrize(
        ("requested", "applied"),
        [(0, 0), (50, 50), (100, 100), (101, 100), (150, 100), (-1, 0), (-999, 0)],
    )
    def test_clamps_to_nearest_bound(self, stub, requested, applied) -> None:
        assert stub.set_volume(requested) == applied

    def test_returns_the_level_actually_applied(self, stub) -> None:
        assert stub.set_volume(150) == 100
        assert stub.get_volume() == 100

    def test_provider_receives_already_clamped_values(self, stub) -> None:
        for value in (-40, 250, 60):
            stub.set_volume(value)
        assert stub.received_levels == [0, 100, 60]
        assert all(0 <= level <= 100 for level in stub.received_levels)


class TestFactory:
    def test_override_wins_over_detection(self) -> None:
        assert detect_platform("WINDOWS") == "windows"
        assert isinstance(create_provider("darwin"), PROVIDERS["darwin"])

    def test_unknown_platform_raises_rather_than_defaulting(self) -> None:
        # The node's factory falls back to Linux; here a wrong guess would mean
        # shelling out to the wrong binaries, so it must fail loudly.
        with pytest.raises(RuntimeError, match="unsupported platform"):
            detect_platform("solaris")

    def test_detects_the_running_platform(self) -> None:
        assert detect_platform() in PROVIDERS


class TestLinuxSessionHonesty:
    """A headless host must not advertise capabilities that quietly no-op.

    Found on a real headless Pi: it reported `open` because xdg-open was
    installed, and since open is fire-and-forget a caller would have seen 202
    with nothing happening.
    """

    @pytest.fixture
    def linux(self):
        return PROVIDERS["linux"]()

    def test_headless_does_not_advertise_open(self, linux, monkeypatch) -> None:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert "open" not in linux.capabilities()

    def test_headless_open_raises_not_supported(self, linux, monkeypatch) -> None:
        from jarvis_host_agent.errors import NotSupported

        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(
            "jarvis_host_agent.providers.linux.shutil.which", lambda _: "/usr/bin/xdg-open"
        )
        with pytest.raises(NotSupported, match="no graphical session"):
            linux.open_target("/tmp/whatever")

    def test_wayland_can_open_but_cannot_control_windows(self, linux, monkeypatch) -> None:
        """Wayland forbids cross-app window control but launching apps is fine."""
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        monkeypatch.setattr(
            "jarvis_host_agent.providers.linux.shutil.which", lambda _: "/usr/bin/tool"
        )
        caps = linux.capabilities()
        assert "open" in caps
        assert "windows.list" not in caps


class TestWindowsAudioEndpointHonesty:
    """Windows must not advertise volume when there is no playback device.

    Found on a headless windows-latest runner: pycaw imported fine, so volume
    was advertised, and the call then raised a raw COMError. Probing the library
    is not the same as probing the capability -- the same mistake as the Linux
    xdg-open case above.
    """

    @pytest.fixture
    def windows(self):
        return PROVIDERS["windows"]()

    def test_unreachable_endpoint_means_no_volume_capability(self, windows, monkeypatch) -> None:
        monkeypatch.setattr(
            type(windows), "_endpoint", lambda _self: (_ for _ in ()).throw(OSError("no device"))
        )
        caps = windows.capabilities()
        assert "volume.get" not in caps
        assert "volume.set" not in caps

    def test_reachable_endpoint_means_volume_capability(self, windows, monkeypatch) -> None:
        monkeypatch.setattr(type(windows), "_endpoint", lambda _self: object())
        caps = windows.capabilities()
        assert {"volume.get", "volume.set"} <= caps

    def test_com_error_surfaces_as_not_supported_not_a_500(self, windows, monkeypatch) -> None:
        """A missing device is a 501, never a raw ctypes error escaping as 500."""
        from jarvis_host_agent.errors import NotSupported

        monkeypatch.setattr(
            type(windows),
            "_volume_module",
            staticmethod(
                lambda: (_FakeAudioUtilities, object(), 0, lambda *a: None, lambda *a: None)
            ),
        )
        with pytest.raises(NotSupported, match="no usable audio endpoint"):
            windows.get_volume()


class _FakeAudioUtilities:
    @staticmethod
    def GetSpeakers():  # noqa: N802 - mirrors pycaw's API
        raise OSError("Element not found.")
