"""Live tests against the real host, one OS at a time.

Marked ``native`` and skipped unless the running platform matches, so the CI
matrix exercises each provider on its own runner while the contract suite runs
everywhere. Volume tests restore the original level.
"""

from __future__ import annotations

import platform

import pytest

from jarvis_host_agent.capabilities import KNOWN_CAPABILITIES, VOLUME_GET, VOLUME_SET
from jarvis_host_agent.providers.factory import create_provider

pytestmark = pytest.mark.native

CURRENT = platform.system().lower()


@pytest.fixture
def provider():
    if CURRENT not in {"windows", "darwin", "linux"}:
        pytest.skip(f"unsupported platform: {CURRENT}")
    return create_provider()


def test_capabilities_are_valid_on_the_real_host(provider) -> None:
    assert provider.capabilities() <= KNOWN_CAPABILITIES


def test_platform_matches_the_running_os(provider) -> None:
    assert provider.platform == CURRENT


def test_volume_round_trips(provider) -> None:
    caps = provider.capabilities()
    if not {VOLUME_GET, VOLUME_SET} <= caps:
        pytest.skip("this host has no usable mixer")

    original = provider.get_volume()
    assert 0 <= original <= 100
    try:
        applied = provider.set_volume(35)
        assert applied == 35
        # Some mixers quantise, so allow a small delta rather than demanding 35.
        assert abs(provider.get_volume() - 35) <= 3
    finally:
        provider.set_volume(original)


def test_clamping_holds_against_a_real_mixer(provider) -> None:
    caps = provider.capabilities()
    if not {VOLUME_GET, VOLUME_SET} <= caps:
        pytest.skip("this host has no usable mixer")
    original = provider.get_volume()
    try:
        assert provider.set_volume(500) == 100
    finally:
        provider.set_volume(original)


def test_window_listing_is_well_formed_when_supported(provider) -> None:
    if "windows.list" not in provider.capabilities():
        pytest.skip("no window control on this host (headless, Wayland, or no TCC)")
    for window in provider.list_windows():
        assert window.id
        assert isinstance(window.minimized, bool)
