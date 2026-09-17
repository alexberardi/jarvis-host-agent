from __future__ import annotations

import pytest

from jarvis_host_agent.capabilities import KNOWN_CAPABILITIES
from jarvis_host_agent.config import Config
from jarvis_host_agent.providers.base import HostProvider, Window

TEST_TOKEN = "test-token-not-a-real-secret"


class StubProvider(HostProvider):
    """A provider with no OS underneath it.

    Records what the base class handed down, which is how the clamping tests
    prove the provider received an already-valid level rather than doing its
    own clamping.
    """

    def __init__(self, capabilities: set[str] | None = None) -> None:
        self._capabilities = capabilities if capabilities is not None else set(KNOWN_CAPABILITIES)
        self.received_levels: list[int] = []
        self.opened: list[str] = []
        self.actions: list[tuple[str, str]] = []
        self.volume = 50
        self.windows = [Window(id="w1", title="Steam", app="steam.exe", minimized=False)]

    @property
    def platform(self) -> str:
        return "linux"

    def capabilities(self) -> set[str]:
        return self._validated_capabilities(set(self._capabilities))

    def get_volume(self) -> int:
        return self.volume

    def _set_volume(self, level: int) -> None:
        self.received_levels.append(level)
        self.volume = level

    def list_windows(self) -> list[Window]:
        return list(self.windows)

    def minimize_window(self, window_id: str) -> None:
        self.actions.append((window_id, "minimize"))

    def focus_window(self, window_id: str) -> None:
        self.actions.append((window_id, "focus"))

    def close_window(self, window_id: str) -> None:
        self.actions.append((window_id, "close"))

    def open_target(self, target: str) -> None:
        self.opened.append(target)


@pytest.fixture
def stub() -> StubProvider:
    return StubProvider()


@pytest.fixture
def config() -> Config:
    return Config(host="127.0.0.1", port=7724, token=TEST_TOKEN, platform_override=None)


@pytest.fixture
def client(config: Config, stub: StubProvider):
    from fastapi.testclient import TestClient

    from jarvis_host_agent.app import build_app

    with TestClient(build_app(config=config, provider=stub)) as test_client:
        test_client.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
        yield test_client
