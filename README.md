# jarvis-agent (desktop node, POC)

A Jarvis node for desktops. One Go binary enrolls with jarvisd like a Pi node, connects to
jarvisd's MQTT, and offers OS control as client tools: open a link, get/set volume, and
list/minimise/focus/close windows. It works on Linux, macOS and Windows.

```
mobile chat → jarvisd CC → LLM picks desktop_set_volume → MQTT tool_call → jarvis-agent → OS
```

Proof of concept on branch `go-rewrite`; see [docs/DESIGN.md](docs/DESIGN.md).

## Try it

```bash
CGO_ENABLED=0 go build -o jarvis-agent ./cmd/jarvis-agent
./jarvis-agent status                      # what this host can do right now
./jarvis-agent try desktop_get_volume      # run a tool locally, no server

./jarvis-agent enroll --server http://<jarvisd-host>:7700 --email you@example.com
./jarvis-agent run                         # foreground; Ctrl-C to stop
```

Then, in the app, chat with the new node (named after this computer, room "desktop").

Run it in your desktop session. Use a systemd user unit, a LaunchAgent or a logon Scheduled
Task (templates in `deploy/`). Never use a system service.

macOS window control needs **System Settings → Privacy & Security → Accessibility** enabled for
the `jarvis-agent` binary, plus approval of the "control System Events" prompt.
