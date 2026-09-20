# jarvis-host-agent

Native host agent exposing **one uniform HTTP contract** for OS control, with
three platform providers behind it. Runs beside a Jarvis node, on the machine
that node is meant to control.

> **Identity rule:** this service owns *how to do a thing on this OS*. It owns no
> policy, no routing and no voice logic. If you catch yourself deciding *which*
> window the user meant, or *whether* they are allowed to, push it to
> command-center or the command. The agent answers "minimise window 0x1234", never
> "minimise the thing I was just talking about".

## Quick reference

```bash
poetry install
poetry run jarvis-host-agent          # 127.0.0.1:7724

poetry run pytest -q                  # contract + API; runs on ANY OS
poetry run pytest -m native -v        # live host tests; skips what this host lacks
poetry run python openapi_dump.py     # generated schema
poetry run ruff check . && poetry run ruff format --check .
```

## Architecture

```
jarvis_host_agent/
├── app.py                  # THE HTTP layer -- one implementation, all providers
├── auth.py                 # bearer token + browser-origin guard
├── capabilities.py         # the closed set of capability names
├── config.py               # env config + token generation
├── errors.py               # error types and their HTTP status mapping
├── models.py               # wire models == the contract (OpenAPI generated from these)
└── providers/
    ├── base.py             # HostProvider ABC -- read this first
    ├── factory.py          # platform dispatch, JARVIS_HOST_OS override
    ├── windows.py          # pycaw (WASAPI) + Win32
    ├── macos.py            # osascript
    └── linux.py            # pactl/amixer + wmctrl/xdotool
```

## How drift is actually prevented

Three separate mechanisms, because "we all implement the same ABC" is not enough
on its own:

1. **One HTTP layer.** `app.py` is the only caller of any provider, so three
   providers cannot disagree about status codes, payload shapes or gating.
2. **Template methods for shared semantics.** Clamping lives in
   `HostProvider.set_volume`; the abstract hook is `_set_volume`, documented to
   receive an already-valid level. There is one clamp implementation, so there is
   nothing to diverge. A contract test asserts no provider overrides
   `set_volume`.
3. **Capability gating above the providers.** `app.py` checks `capabilities()`
   before dispatching, so an unsupported operation is a uniform `501` rather than
   whatever each platform's tooling happens to raise.

`tests/test_contract.py` runs one set of assertions against **every** provider on
**every** OS. That is what catches a Windows-only mistake on the Linux runner.

## Invariants & gotchas

1. **Providers must be constructible on any OS.** No platform imports, hardware
   probes or subprocess calls in `__init__` — do it lazily in the methods and in
   `capabilities()`. The entire cross-platform contract suite depends on this;
   break it and the Windows provider becomes untestable anywhere but Windows.
2. **`capabilities()` is computed per request, never cached.** The answer really
   does change at runtime: a macOS Accessibility grant can be revoked and a Linux
   box can gain a session.
3. **Never put a range constraint on `SetVolumeRequest.volume`.** The contract
   says out-of-range clamps to the nearest bound. A pydantic `ge=0, le=100` turns
   the 150-becomes-100 case into a 422 and silently breaks the contract. A test
   covers this because it is such an inviting "fix".
4. **A provider must expose no public method beyond the ABC.** A Windows-only
   public method is exactly how commands start depending on one platform.
   Platform helpers get a leading underscore; a contract test enforces it.
5. **Capability names are a closed set** (`capabilities.py`). A typo would
   silently disable a feature, so `_validated_capabilities` rejects unknown names
   and the contract suite checks every provider's output.
6. **`open` is fire-and-forget by contract** and returns `202`. Do not add
   launch confirmation — it is unreliable on all three platforms, and promising
   it would make the contract a lie. This is also why `open` requires a graphical
   session on Linux: `xdg-open` on a headless box exits 0 having done nothing,
   which with fire-and-forget semantics is indistinguishable from success.
7. **`close_window` is a graceful request, never a kill.** `WM_CLOSE` on
   Windows, `wmctrl -c` on Linux. A misheard voice command must not be able to
   lose someone's unsaved work.
8. **Window ids are opaque cookies.** HWND, X11 id, CGWindowID — stringified.
   Valid only until the window closes; never parse or persist them.
9. **`/health` is deliberately unauthenticated**, so admin's registry can probe
   it the way it probes `jarvis-osx-api`, without holding the node's token. It
   discloses only platform and version.
10. **The factory raises on an unknown platform** rather than defaulting to
    Linux the way `jarvis-node-setup`'s `PlatformFactory` does. A wrong audio
    provider degrades; a wrong *host* provider would shell out to binaries that
    do not exist and advertise capabilities it lacks.

11. **The agent runs in the user's interactive session on all three
    platforms** — LaunchAgent, systemd *user* unit, Scheduled Task with
    `InteractiveToken`. Never a LaunchDaemon, system unit, or Windows service:
    Session 0 (and a root system unit, and a daemon) has no window station, so
    `open` launches into nothing and window enumeration comes back empty while
    volume keeps working. `tests/test_deploy_templates.py` fails CI on any of
    those conversions.
12. **`RunLevel` stays `LeastPrivilege` on Windows.** UIPI blocks an elevated
    process from sending window messages to non-elevated apps, so "run as
    admin" breaks the window control it looks like it would help.
13. **Don't grep template prose in a guard.** The SYSTEM-account check parses
    `UserId` elements; an earlier version matched the comment explaining why
    SYSTEM is wrong, and passed for the wrong reason.

## Testing

- `tests/test_contract.py` — one assertion set, every provider, every OS.
  Structural conformance, capability-name validity, volume semantics, factory.
- `tests/test_api.py` — auth (including the browser-origin refusal), capability
  gating → 501, status codes, clamping through HTTP.
- `tests/test_native.py` — marked `native`, deselected by default via `addopts`.
  Exercises the real host and skips whatever this host cannot do.

The suite is mutation-tested. Verified caught: removing the clamp, adding a
pydantic range constraint, no-oping the capability gate, dropping the
browser-origin guard, echoing the requested volume instead of the applied one,
adding a public method to one provider, making the factory default silently, and
typo'ing a capability name.

## Dependencies

Runtime: FastAPI, uvicorn, pydantic. Windows additionally needs `pywin32`,
`pycaw` and `comtypes`, all import-guarded so a missing wheel degrades to absent
capabilities rather than a boot failure. macOS and Linux shell out to system
binaries and need no extra packages — the same approach `jarvis-node-setup`
takes with `afplay` / `aplay`.

All versions are pinned with upper bounds. Four outages in one week came from
unpinned upstreams; do not add a bare requirement here.

## Not in scope

- **Mute.** A toggle whose state is invisible in most UIs is a poor voice
  primitive. If it returns, it should be `set_muted(bool)`, never a toggle.
- **Clipboard and file mutation.** A voice-driven `delete` backed by an STT
  transcript needs allowlisted roots, no recursive delete, and trash-not-unlink
  (`FOF_ALLOWUNDO` / `trashItem` / `gio trash`) before it can ship safely.
- **Choosing which host to act on.** The agent is co-located with its node and
  controls that machine. Multi-machine targeting, if it ever arrives, belongs in
  CC.
