"""HTTP layer tests: auth, capability gating, status codes, payload shapes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jarvis_host_agent.app import build_app
from tests.conftest import TEST_TOKEN, StubProvider


class TestAuth:
    def test_health_needs_no_token(self, config, stub) -> None:
        with TestClient(build_app(config=config, provider=stub)) as anon:
            response = anon.get("/health")
        assert response.status_code == 200
        assert response.json()["platform"] == "linux"

    @pytest.mark.parametrize("path", ["/capabilities", "/volume", "/windows"])
    def test_everything_else_requires_a_token(self, config, stub, path) -> None:
        with TestClient(build_app(config=config, provider=stub)) as anon:
            assert anon.get(path).status_code == 401

    def test_wrong_token_is_rejected(self, config, stub) -> None:
        with TestClient(build_app(config=config, provider=stub)) as anon:
            response = anon.get("/capabilities", headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_browser_origin_is_refused_even_with_a_valid_token(self, client) -> None:
        """Closes the localhost-CSRF hole: a page cannot drive the agent."""
        response = client.get("/capabilities", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    def test_cross_site_fetch_is_refused(self, client) -> None:
        response = client.get("/capabilities", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403

    def test_native_caller_without_browser_headers_passes(self, client) -> None:
        assert client.get("/capabilities").status_code == 200


class TestVolume:
    def test_get_returns_current_level(self, client, stub) -> None:
        stub.volume = 37
        assert client.get("/volume").json() == {"volume": 37}

    def test_put_applies_and_echoes(self, client) -> None:
        assert client.put("/volume", json={"volume": 42}).json() == {"volume": 42}

    @pytest.mark.parametrize(("requested", "applied"), [(150, 100), (-20, 0), (0, 0), (100, 100)])
    def test_out_of_range_clamps_rather_than_422(self, client, requested, applied) -> None:
        """The contract says clamp. A pydantic ge/le constraint would 422 here."""
        response = client.put("/volume", json={"volume": requested})
        assert response.status_code == 200
        assert response.json() == {"volume": applied}

    def test_non_integer_is_a_validation_error(self, client) -> None:
        assert client.put("/volume", json={"volume": "loud"}).status_code == 422


class TestWindows:
    def test_list_shape(self, client) -> None:
        windows = client.get("/windows").json()["windows"]
        assert windows == [{"id": "w1", "title": "Steam", "app": "steam.exe", "minimized": False}]

    @pytest.mark.parametrize("action", ["minimize", "focus", "close"])
    def test_actions_dispatch_and_return_204(self, client, stub, action) -> None:
        response = client.post(f"/windows/w1/{action}")
        assert response.status_code == 204
        assert stub.actions == [("w1", action)]

    def test_unknown_action_is_rejected_by_the_enum(self, client) -> None:
        assert client.post("/windows/w1/explode").status_code == 422


class TestOpen:
    def test_open_is_accepted_and_fire_and_forget(self, client, stub) -> None:
        response = client.post("/open", json={"target": "steam://open/bigpicture"})
        # 202, not 200: we do not know whether the app actually started.
        assert response.status_code == 202
        assert stub.opened == ["steam://open/bigpicture"]

    def test_empty_target_is_rejected(self, client) -> None:
        assert client.post("/open", json={"target": ""}).status_code == 422


class TestCapabilityGating:
    """Unsupported operations must be a uniform 501, decided above the provider."""

    @pytest.fixture
    def limited_client(self, config):
        # A headless node: volume works, windows do not.
        provider = StubProvider(capabilities={"volume.get", "volume.set", "open"})
        with TestClient(build_app(config=config, provider=provider)) as test_client:
            test_client.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
            yield test_client

    def test_missing_capability_yields_501(self, limited_client) -> None:
        response = limited_client.get("/windows")
        assert response.status_code == 501
        assert response.json()["error"] == "NotSupported"

    def test_window_action_also_501(self, limited_client) -> None:
        assert limited_client.post("/windows/w1/minimize").status_code == 501

    def test_supported_operations_still_work(self, limited_client) -> None:
        assert limited_client.get("/volume").status_code == 200

    def test_capabilities_lists_only_what_works(self, limited_client) -> None:
        assert limited_client.get("/capabilities").json()["capabilities"] == [
            "open",
            "volume.get",
            "volume.set",
        ]

    def test_gating_never_calls_the_provider(self, config) -> None:
        """A 501 must not have touched the OS."""
        provider = StubProvider(capabilities=set())
        with TestClient(build_app(config=config, provider=provider)) as anon:
            anon.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
            anon.post("/open", json={"target": "/tmp/x"})
        assert provider.opened == []
