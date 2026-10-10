# jarvis-host-agent (Go desktop node, POC)

`jarvis-agent` is a **Jarvis node that runs on a desktop**. It enrolls with jarvisd like a Pi
node, holds a node id/key, connects to jarvisd's MQTT, shows up in the app's node list, and
offers OS control as client tools: open a link, get/set volume, list/minimise/focus/close
windows. Status: proof of concept on branch `go-rewrite`, not shipped. Design, decisions and
open questions: **[docs/DESIGN.md](docs/DESIGN.md)**: read it first.

The Python HTTP service that used to live here (port 7724) is gone from this branch; it is in
`main`'s history. Nothing listens on a port any more.

> **Identity rule:** `internal/host` owns *how to do a thing on this OS*. It owns no policy, no
> routing and no voice logic. Deciding *which* window the user meant, or *whether* they may,
> belongs in command-center or the tool layer (`internal/desktop`). The host answers "minimise
> window 0x1234", never "minimise the thing I was just talking about".

## Quick reference

```bash
export GOTOOLCHAIN=local                       # this box: mise exec go@1.27 -- go ...
go test ./...                                  # contract, tools, node, deploy guards (any OS)
CGO_ENABLED=1 go test -race ./...              # what CI runs
JARVIS_HOST_NATIVE=1 go test -v -run Native ./internal/host/   # drive the real host
for os in linux darwin windows; do GOOS=$os go vet ./... || echo FAIL $os; done
CGO_ENABLED=0 go build -o jarvis-agent ./cmd/jarvis-agent

./jarvis-agent status                          # capabilities now + enrollment + reachability
./jarvis-agent try                             # list the tools this host offers now
./jarvis-agent try desktop_set_volume '{"volume": 30}'   # run one tool locally, no jarvisd
./jarvis-agent enroll --server http://10.0.0.122:7700 --email you@example.com
./jarvis-agent run
```

The sidecar test needs a Python that can `import jarvis_command_sdk`
(`JARVIS_SIDECAR_PYTHON`, default `python3`); it skips otherwise. Locally:
`PYTHONPATH=../jarvis-command-sdk go test ./internal/sidecar/`.

Gate on exit codes: never judge a run by output piped through `tail`.

## Layout

```
cmd/jarvis-agent/     CLI: enroll, run, status, try, version
internal/host/        Backend interface + Host (gate, clamp, validate) + linux/darwin/windows backends
                      -- read host.go first
internal/desktop/     the 7 client tools over Host, and the open policy
internal/node/        reusable node core: creds, discovery, CC client, enroll, MQTT runner, dispatch
internal/sidecar/     Python package sidecar spike (JSON lines over stdin/stdout)
deploy/               systemd user unit, LaunchAgent, Scheduled Task (+ Go guard tests)
```

`internal/node` knows nothing about desktops; a Go Pi node would reuse it unchanged and plug
in its own `Toolset`.

## How drift between platforms is prevented

1. **`host.Host` is the only caller of a `Backend`.** Capability gating, the volume clamp and
   capability-name validation live there once, so three backends can't disagree on them.
2. **`Backend.ApplyVolume` receives an already-clamped level.** One clamp (`Host.SetVolume`).
3. **One contract suite, every backend, every OS** (`internal/host/contract_test.go`), with
   fakes for `Sys` (shell-outs) and `Win32`. It was mutation-checked: removing the clamp,
   no-oping the gate, echoing the requested volume, killing instead of closing (each
   platform), typo'ing a capability, skipping the unknown-capability check, splicing an
   unvalidated macOS window id, and advertising minimise without xdotool are all caught.

## Invariants & gotchas

1. **Backends are constructible on any OS.** No probes, subprocesses or syscalls at
   construction. Backend files are deliberately *not* named `*_linux.go` / `*_darwin.go` /
   `*_windows.go`; only `win32_windows.go` / `win32_other.go` are build-constrained, behind
   the `Win32` interface. Break this and the Windows backend becomes untestable off Windows.
2. **Capabilities are computed per call, never cached** (AX grants get revoked, sessions come
   and go). Tools are offered per `report_tools` from the capabilities at that moment.
3. **Volume clamps, never errors.** 150 -> 100, -5 -> 0. Don't add range validation at any
   layer; numeric strings ("30", "45%") are accepted.
4. **A backend exposes exactly the `Backend` methods** (reflect test). Platform helpers stay
   unexported.
5. **Capability names are a closed set** (`KnownCapabilities`); `Host` rejects others.
6. **`open` is fire-and-forget.** No launch confirmation; it is unreliable everywhere. Linux
   refuses without a graphical session (xdg-open on a headless box exits 0 having done nothing).
7. **Close is graceful, never a kill:** `WM_CLOSE`, `wmctrl -c`, the window's AXCloseButton.
8. **Window ids are opaque** (decimal HWND, X11 `0x…`, macOS `pid/index`), but each backend
   validates its own format before an id reaches a subprocess or AppleScript. The Python
   macOS provider spliced ids into AppleScript unvalidated; don't regress that.
9. **The open policy is in `internal/desktop`, not `host`.** Default: http, https, mailto only.
   `--allow-open-any` restores "anything the OS can open" (i.e. program execution).
10. **Runs in the user's interactive session on all three platforms** (systemd *user* unit,
    LaunchAgent in `gui/$UID`, Scheduled Task with `InteractiveToken` + `LeastPrivilege`).
    Never root/system/daemon/Session 0. `deploy/deploy_test.go` fails CI on a conversion.
11. **The node key never reaches a log or stdout.** `Creds` implements `slog.LogValuer` and
    `String()` without it; the creds file is 0600 in a 0700 dir and `LoadCreds` refuses a
    group/world-readable one.
12. **Every `tool_call` is verified** with `POST /commands/{rid}/verify` before running
    (single use). Broker ACLs already confine publishers; this is defence in depth for a node
    that can open things.
13. **Wayland has no window control** (no cross-client API). XWayland's `DISPLAY` does not
    count. Per-compositor backends are an open question.
14. **macOS window control needs Accessibility for the `jarvis-agent` binary** plus an
    Automation grant for System Events, approved on screen. The grant is per code signature,
    so an unsigned rebuild loses it. Probing really lists windows (`accessProbe`); "count
    processes" succeeds without the grant and lied.

## Dependencies

`github.com/eclipse/paho.mqtt.golang`, `golang.org/x/sys` (Windows syscalls),
`golang.org/x/term` (password prompt). `CGO_ENABLED=0` builds everywhere: Windows volume is
WASAPI over raw COM vtables, windows are user32, open is ShellExecuteW.

## Not in scope (unchanged)

- **Mute** (if it returns: `set_muted(bool)`, never a toggle).
- **Clipboard and file mutation** (needs allowlisted roots and trash-not-unlink first).
- **Choosing which machine to act on**: the user picks the node; multi-machine targeting
  belongs in CC.
