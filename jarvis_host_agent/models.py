"""Wire models. These *are* the contract -- the OpenAPI schema is generated
from them, so a change here is a change every command sees.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WindowAction(str, Enum):
    minimize = "minimize"
    focus = "focus"
    close = "close"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    platform: str


class CapabilitiesResponse(BaseModel):
    platform: str = Field(description="windows | darwin | linux")
    version: str
    capabilities: list[str] = Field(description="Sorted capability names")


class VolumeState(BaseModel):
    volume: int = Field(description="Master volume, 0-100")


class SetVolumeRequest(BaseModel):
    # Deliberately unconstrained: the contract says out-of-range clamps to the
    # nearest bound, so a ge/le constraint here would turn a 150 that must
    # become 100 into a 422. Clamping happens in HostProvider.set_volume.
    volume: int = Field(description="Desired volume; clamped into 0-100")


class WindowModel(BaseModel):
    id: str = Field(description="Opaque platform handle; do not parse")
    title: str
    app: str
    minimized: bool


class WindowListResponse(BaseModel):
    windows: list[WindowModel]


class OpenRequest(BaseModel):
    target: str = Field(min_length=1, description="Filesystem path or URI")


class ErrorResponse(BaseModel):
    error: str
    detail: str
