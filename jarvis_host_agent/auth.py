"""Bearer token plus a browser-origin guard.

The token alone is not enough. The agent listens on loopback, which any page in
the user's browser can also reach, so a malicious site could POST to it --
classic localhost CSRF, and DNS rebinding defeats naive Host checks. Browsers
attach ``Origin``/``Sec-Fetch-Site`` to such requests and a native client does
not, so rejecting browser-shaped requests closes the hole cheaply.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status


def require_auth(request: Request) -> None:
    expected: str = request.app.state.config.token

    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="a valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A native caller sends neither header; a browser always sends at least one.
    fetch_site = request.headers.get("sec-fetch-site")
    if request.headers.get("origin") or (fetch_site and fetch_site != "none"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="browser-originated requests are refused",
        )
