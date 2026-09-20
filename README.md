# jarvis-host-agent

Uniform OS control for the machine a Jarvis node runs on — one HTTP contract,
three platform providers (Windows, macOS, Linux).

A Jarvis node captures voice and executes tool calls, but it cannot reach the
desktop it sits on: a containerised node has no Win32 API or window station,
and even a native node would need per-OS branches scattered through every
command. This agent puts that behind one contract, so a command written once
works on all three platforms.

```
voice → node → CC returns tool_calls → node executes → jarvis-host-agent → OS
                                                       (same machine)
```

## Quick reference

```bash
poetry install
poetry run jarvis-host-agent            # binds 127.0.0.1:7724

poetry run pytest -q                    # contract + API suites (any OS)
poetry run pytest -m native -v          # live tests against this host
poetry run python openapi_dump.py       # generated OpenAPI schema
poetry run ruff check .
```

## API

Every route except `/health` needs `Authorization: Bearer <token>`.

| Route | | Notes |
|---|---|---|
| `GET /health` | | Unauthenticated, for the admin registry probe |
| `GET /capabilities` | | What works on *this* host, right now |
| `GET /volume` | | `{"volume": 0-100}` |
| `PUT /volume` | | Out-of-range **clamps** to the nearest bound; returns what was applied |
| `GET /windows` | | Opaque `id` per window — a cookie, never parse it |
| `POST /windows/{id}/{minimize,focus,close}` | | `204`; `close` is a graceful request, never a kill |
| `POST /open` | | Path or URI. `202`: fire-and-forget by contract |

Unsupported operations return **`501`**, not `400` — the request was fine, the
platform simply has no implementation. Callers should read `/capabilities` and
degrade rather than relying on the error.

### Capabilities are not uniform, and that is the point

| | Windows | macOS | Linux |
|---|---|---|---|
| volume | WASAPI via pycaw | `osascript` | `pactl` / `amixer` |
| windows | Win32 | `osascript` + **Accessibility grant** | X11 + `wmctrl`; **never Wayland** |
| open | `os.startfile` | `open` | `xdg-open` + a graphical session |

Three real absences to expect: **Wayland** forbids cross-app window control by
design (not a missing library — there is no privileged client); **macOS**
window control needs a TCC Accessibility grant for whichever process hosts the
agent, and silently fails without it; a **headless node** has no windows and
cannot meaningfully `open` anything.

## Install

The agent runs **natively, in the user's desktop session** — never as a daemon,
system unit, or Windows service. That is not a style preference: outside an
interactive session there is no window server, so window control and `open`
stop working while volume keeps succeeding, which looks like a half-broken
agent rather than a misinstall.

```bash
# macOS — per-user LaunchAgent
./deploy/install-macos.sh

# Linux — systemd user unit
./deploy/install-linux.sh
```

```powershell
# Windows — Scheduled Task, triggered at logon, interactive token
.\deploy\windows\Install-HostAgent.ps1
```

Each installer substitutes the agent binary path and registers the supervisor;
none of them need `sudo` or an elevated prompt. Platform notes:

| | note |
|---|---|
| macOS | Grant **Accessibility** to the agent binary or window control reports itself unavailable |
| Linux | `sudo loginctl enable-linger $USER` on a headless box, or the unit dies at logout |
| Windows | Runs at logon only — there is no desktop to control while signed out |

`tests/test_deploy_templates.py` enforces the session rules on all three, so a
well-meaning change to a daemon/system unit/SYSTEM task fails CI rather than
shipping a silently crippled install.

## Configuration

| Variable | Default | |
|---|---|---|
| `JARVIS_HOST_AGENT_BIND` | `127.0.0.1` | Loopback by default. Widening exposes volume and window control to the LAN. |
| `JARVIS_HOST_AGENT_PORT` | `7724` | |
| `JARVIS_HOST_AGENT_TOKEN` | *(generated)* | Else read/created at `~/.jarvis/host-agent.token`, chmod 600 |
| `JARVIS_HOST_OS` | *(detected)* | Force a provider, mirroring the node's `JARVIS_NODE_OS` |

### Security

The token is not sufficient on its own. The agent listens on loopback, which
any page in the user's browser can also reach — classic localhost CSRF, and DNS
rebinding defeats naive `Host` checks. Browsers attach `Origin` /
`Sec-Fetch-Site` and native clients do not, so browser-shaped requests are
refused outright.

Known gap: `chmod 600` on the token file is a no-op on Windows. An ACL is the
equivalent and is not yet implemented.

## Status

v0.1.0 scaffold. Volume, windows and `open` only. Deliberately **not** here yet:
mute (a toggle whose state is invisible in most UIs is a bad voice primitive),
clipboard, and any file mutation — a voice-driven `delete` backed by an STT
transcript wants allowlisted roots and trash-not-unlink before it ships.
