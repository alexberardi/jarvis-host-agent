"""The one and only HTTP layer.

Every provider is reached through these handlers, which is the other half of
the anti-drift design: because the routes exist once, three providers cannot
disagree about status codes, payload shapes or capability gating even if their
platform code looks nothing alike.

Capability gating happens *here*, before the provider is called, so an
unsupported operation is a uniform 501 rather than whatever each platform's
tooling happens to raise.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import require_auth
from .capabilities import (
    OPEN,
    VOLUME_GET,
    VOLUME_SET,
    WINDOW_ACTION_CAPABILITY,
    WINDOWS_LIST,
)
from .config import Config
from .errors import HostAgentError, NotSupported
from .models import (
    CapabilitiesResponse,
    HealthResponse,
    OpenRequest,
    SetVolumeRequest,
    VolumeState,
    WindowAction,
    WindowListResponse,
    WindowModel,
)
from .providers.base import HostProvider
from .providers.factory import create_provider
from .version import VERSION

Authed = Annotated[None, Depends(require_auth)]


def _provider(request: Request) -> HostProvider:
    return request.app.state.provider


def _require_capability(provider: HostProvider, name: str) -> None:
    if name not in provider.capabilities():
        raise NotSupported(f"{name} is not available on this host")


def build_app(config: Config | None = None, provider: HostProvider | None = None) -> FastAPI:
    """Construct the app.

    ``config`` and ``provider`` are injectable so tests can drive a stub
    provider without touching the host -- the same pattern jarvis-admin uses
    with ``buildApp(opts)``.
    """
    config = config or Config.from_env()
    app = FastAPI(
        title="Jarvis Host Agent",
        version=VERSION,
        description=(
            "Uniform OS control for the machine a Jarvis node runs on. "
            "One contract, three platform providers."
        ),
    )
    app.state.config = config
    app.state.provider = provider or create_provider(config.platform_override)

    @app.exception_handler(HostAgentError)
    async def _host_error(_request: Request, exc: HostAgentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    # Unauthenticated on purpose: admin's registry health-checks this the same
    # way it probes jarvis-osx-api, without holding the node's token. It leaks
    # only the platform name and version.
    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(version=VERSION, platform=_provider(request).platform)

    @app.get("/capabilities", response_model=CapabilitiesResponse, tags=["meta"])
    async def capabilities(request: Request, _: Authed) -> CapabilitiesResponse:
        provider = _provider(request)
        return CapabilitiesResponse(
            platform=provider.platform,
            version=VERSION,
            capabilities=sorted(provider.capabilities()),
        )

    @app.get("/volume", response_model=VolumeState, tags=["volume"])
    async def get_volume(request: Request, _: Authed) -> VolumeState:
        provider = _provider(request)
        _require_capability(provider, VOLUME_GET)
        return VolumeState(volume=provider.get_volume())

    @app.put("/volume", response_model=VolumeState, tags=["volume"])
    async def set_volume(request: Request, body: SetVolumeRequest, _: Authed) -> VolumeState:
        provider = _provider(request)
        _require_capability(provider, VOLUME_SET)
        # Returns what was applied, which may differ from what was asked.
        return VolumeState(volume=provider.set_volume(body.volume))

    @app.get("/windows", response_model=WindowListResponse, tags=["windows"])
    async def list_windows(request: Request, _: Authed) -> WindowListResponse:
        provider = _provider(request)
        _require_capability(provider, WINDOWS_LIST)
        return WindowListResponse(windows=[WindowModel(**vars(w)) for w in provider.list_windows()])

    @app.post("/windows/{window_id}/{action}", status_code=204, tags=["windows"])
    async def window_action(
        request: Request, window_id: str, action: WindowAction, _: Authed
    ) -> None:
        provider = _provider(request)
        _require_capability(provider, WINDOW_ACTION_CAPABILITY[action.value])
        {
            WindowAction.minimize: provider.minimize_window,
            WindowAction.focus: provider.focus_window,
            WindowAction.close: provider.close_window,
        }[action](window_id)

    @app.post("/open", status_code=202, tags=["open"])
    async def open_target(request: Request, body: OpenRequest, _: Authed) -> dict[str, str]:
        provider = _provider(request)
        _require_capability(provider, OPEN)
        provider.open_target(body.target)
        # 202: fire-and-forget by contract. We do not know, and do not claim,
        # that the application actually came up.
        return {"status": "accepted", "target": body.target}

    return app


def main() -> None:
    import uvicorn

    config = Config.from_env()
    uvicorn.run(build_app(config), host=config.host, port=config.port)
