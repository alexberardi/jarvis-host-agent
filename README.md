# jarvis-agent (desktop node, POC)

> [!WARNING]
> **Retired: no longer maintained, and this repository will be archived.** This proof of concept became the Jarvis Automation Agent, which lives in [jarvis-server](https://github.com/alexberardi/jarvis-server) (`cmd/jarvis-agent`). The old multi-container stack is replaced by jarvisd ([jarvis-server](https://github.com/alexberardi/jarvis-server)). New installs: [installer.jarvisautomation.io](https://installer.jarvisautomation.io). Moving an existing install: [Migrating from the Docker install](https://docs.jarvisautomation.dev/install/migrating-from-docker/).

A Jarvis node for desktops. One Go binary enrolls with jarvisd like a Pi node, connects to
jarvisd's MQTT, and offers OS control as client tools: open a link or launch an installed app
by name, get/set volume, and list/minimise/focus/close windows. It works on Linux, macOS and
Windows.

```
mobile chat → jarvisd CC → LLM picks desktop_set_volume → MQTT tool_call → jarvis-agent → OS
```

Proof of concept on branch `go-rewrite`; see [docs/DESIGN.md](docs/DESIGN.md).

## Try it (Linux or macOS)

```bash
scripts/dev-run.sh --server http://<jarvisd-host>:7700 --email you@example.com  # first time
scripts/dev-run.sh                 # afterwards: build and run in the foreground; Ctrl-C stops
scripts/dev-run.sh --install       # or start at login (systemd user unit / LaunchAgent)
scripts/dev-run.sh --status        # what the agent can do right now
```

The script builds the agent, enrolls only if this machine isn't enrolled yet (it prompts for
your password and never prints it), and runs it. Then, in the app, chat with the new node (named
after this computer, room "desktop"), e.g. "open Steam on my computer".

**macOS:** the build is `~/Applications/Jarvis Agent.app`, signed with your Developer ID when
the keychain has one. Run the script from a local Terminal; over SSH the keychain can't sign. On
first run macOS asks to grant Accessibility: open System Settings → Privacy & Security →
Accessibility and turn on **Jarvis Agent**, then allow "Jarvis Agent wants to control System
Events". `scripts/dev-run.sh --status` shows `windows.*` once both are granted.

## What it may open

Links (http, https, mailto) and any installed app, by name: `/Applications`,
`/System/Applications` and `~/Applications` on macOS; `.desktop` entries in the XDG application
dirs on Linux (NoDisplay/Hidden honoured); Start Menu shortcuts on Windows. Never a path or
arguments from the model. `jarvis-agent apps` lists them, and `jarvis-agent apps NAME` shows
what a name resolves to.

Adjust with `apps.json` in the agent's config dir (`~/.config/jarvis-agent/`,
`~/Library/Application Support/jarvis-agent/`, `%AppData%\jarvis-agent\`). It is re-read on
every call:

```json
{
  "allow": ["~/Games/**/*.app", "/opt/tools/*.desktop"],
  "deny":  ["Terminal", "*Activity Monitor*", "**/Utilities/**"]
}
```

`allow` adds glob patterns of app paths (`.app` bundles, `.desktop` files or `.lnk` shortcuts,
per platform). `deny` removes apps whose name or path matches. Matching is case-insensitive,
`**` spans directories, and `~/` is your home. Uninstallers (`*uninstall*`) are always denied.

Run it in your desktop session. Use a systemd user unit, a LaunchAgent or a logon Scheduled
Task (templates in `deploy/`). Never use a system service.
