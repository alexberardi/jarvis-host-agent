// Package desktop turns host capabilities into node client tools: one tool per capability,
// offered only while the capability is available, with the open policy applied here (host owns
// mechanism, this package owns what the LLM may ask for).
package desktop

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"strings"

	"github.com/alexberardi/jarvis-host-agent/internal/host"
	"github.com/alexberardi/jarvis-host-agent/internal/node"
)

// Tool names. Function names can't contain dots, so they don't spell the capability names,
// but each maps to exactly one capability.
const (
	ToolOpen      = "desktop_open"
	ToolGetVolume = "desktop_get_volume"
	ToolSetVolume = "desktop_set_volume"
	ToolList      = "desktop_list_windows"
	ToolMinimize  = "desktop_minimize_window"
	ToolFocus     = "desktop_focus_window"
	ToolClose     = "desktop_close_window"
)

// OpenPolicy decides what desktop_open may hand to the OS. The default allows web and mail
// links only: an arbitrary path or app name is program execution driven by an STT transcript.
type OpenPolicy struct {
	AllowAny bool // opt-in escape hatch (config); restores "anything the OS can open"
}

var openSchemes = map[string]bool{"http": true, "https": true, "mailto": true}

// Check returns nil when target may be opened.
func (p OpenPolicy) Check(target string) error {
	if strings.TrimSpace(target) == "" {
		return host.Errorf(host.ErrInvalidTarget, "empty target")
	}
	if p.AllowAny {
		return nil
	}
	u, err := url.Parse(target)
	if err != nil || !openSchemes[strings.ToLower(u.Scheme)] {
		return host.Errorf(host.ErrInvalidTarget, "only http(s) and mailto links may be opened (got %q)", target)
	}
	if (u.Scheme == "http" || u.Scheme == "https") && u.Host == "" {
		return host.Errorf(host.ErrInvalidTarget, "link has no host: %q", target)
	}
	return nil
}

type tool struct {
	spec       node.Spec
	capability string
	call       func(ctx context.Context, args map[string]any) (map[string]any, error)
}

// Tools is the desktop toolset.
type Tools struct {
	Host   *host.Host
	Policy OpenPolicy
	tools  []tool
}

// New builds the toolset over a host.
func New(h *host.Host, policy OpenPolicy) *Tools {
	t := &Tools{Host: h, Policy: policy}
	winID := node.Param{Name: "window_id", Type: "string", Required: true,
		Description: "Opaque window id exactly as returned by desktop_list_windows"}
	t.tools = []tool{
		{node.Spec{Name: ToolOpen, Description: "Open a web link on the user's computer in its default browser. Returns as soon as the computer accepted the request; it does not confirm the page loaded.",
			Params:   []node.Param{{Name: "target", Type: "string", Required: true, Description: "Full http(s) URL, e.g. https://example.com"}},
			Keywords: []string{"open", "browser", "website", "computer", "desktop"},
			Examples: []node.Example{{VoiceCommand: "open youtube on my computer", Params: map[string]any{"target": "https://www.youtube.com"}, Primary: true}}},
			host.CapOpen, t.open},
		{node.Spec{Name: ToolGetVolume, Description: "Get the computer's master volume (0-100).",
			Keywords: []string{"volume", "computer", "desktop"},
			Examples: []node.Example{{VoiceCommand: "what's the volume on my computer", Params: map[string]any{}, Primary: true}}},
			host.CapVolumeGet, t.getVolume},
		{node.Spec{Name: ToolSetVolume, Description: "Set the computer's master volume. Out-of-range values are clamped to 0-100; the result says the level applied.",
			Params:   []node.Param{{Name: "volume", Type: "int", Required: true, Description: "Desired volume, 0-100"}},
			Keywords: []string{"volume", "louder", "quieter", "computer", "desktop"},
			Examples: []node.Example{{VoiceCommand: "set my computer volume to 30", Params: map[string]any{"volume": 30}, Primary: true}}},
			host.CapVolumeSet, t.setVolume},
		{node.Spec{Name: ToolList, Description: "List the open windows on the user's computer: id, title, app, minimized. Use the ids with the other window tools.",
			Keywords: []string{"windows", "apps", "computer", "desktop"},
			Examples: []node.Example{{VoiceCommand: "what windows are open on my computer", Params: map[string]any{}, Primary: true}}},
			host.CapWindowsList, t.list},
		{node.Spec{Name: ToolMinimize, Description: "Minimize one window on the user's computer.", Params: []node.Param{winID},
			Keywords: []string{"minimize", "hide", "window"}},
			host.CapWindowsMinimize, t.windowAction(host.ActionMinimize)},
		{node.Spec{Name: ToolFocus, Description: "Bring one window on the user's computer to the front.", Params: []node.Param{winID},
			Keywords: []string{"focus", "switch to", "window"}},
			host.CapWindowsFocus, t.windowAction(host.ActionFocus)},
		{node.Spec{Name: ToolClose, Description: "Ask one window on the user's computer to close, as if its close button were clicked. The app may prompt to save; it is never force-killed.", Params: []node.Param{winID},
			Keywords: []string{"close", "window"}, Risky: true},
			host.CapWindowsClose, t.windowAction(host.ActionClose)},
	}
	return t
}

// Available offers each tool only while its capability is present, computed now.
func (t *Tools) Available(ctx context.Context) []node.ToolDef {
	caps, err := t.Host.Capabilities(ctx)
	if err != nil {
		return nil
	}
	have := map[string]bool{}
	for _, c := range caps {
		have[c] = true
	}
	var out []node.ToolDef
	for _, tl := range t.tools {
		if have[tl.capability] {
			out = append(out, tl.spec.Render())
		}
	}
	return out
}

// Call runs a tool. Failures are outputs ({"success": false, "error", "error_code"}), so the
// LLM can tell the user what happened.
func (t *Tools) Call(ctx context.Context, name string, args map[string]any, _ node.Request) (map[string]any, bool) {
	for _, tl := range t.tools {
		if tl.spec.Name != name {
			continue
		}
		out, err := tl.call(ctx, args)
		if err != nil {
			o := node.Fail("%v", err)
			o["error_code"] = code(err)
			return o, true
		}
		out["success"] = true
		return out, true
	}
	return nil, false
}

func code(err error) string {
	switch {
	case errors.Is(err, host.ErrNotSupported):
		return "not_supported"
	case errors.Is(err, host.ErrWindowNotFound):
		return "window_not_found"
	case errors.Is(err, host.ErrInvalidTarget), errors.Is(err, errBadArgs):
		return "invalid_argument"
	}
	return "failed"
}

var errBadArgs = errors.New("bad arguments")

func (t *Tools) open(ctx context.Context, args map[string]any) (map[string]any, error) {
	target, _ := args["target"].(string)
	if err := t.Policy.Check(target); err != nil {
		return nil, err
	}
	if err := t.Host.Open(ctx, target); err != nil {
		return nil, err
	}
	return map[string]any{"opened": target, "note": "requested; launch is not confirmed"}, nil
}

func (t *Tools) getVolume(ctx context.Context, _ map[string]any) (map[string]any, error) {
	v, err := t.Host.GetVolume(ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{"volume": v}, nil
}

// intArg accepts a JSON number or a numeric string (small models send "30"). No range check:
// out-of-range clamps in host.SetVolume.
func intArg(args map[string]any, k string) (int, error) {
	switch v := args[k].(type) {
	case float64:
		if math.IsNaN(v) || math.IsInf(v, 0) {
			break
		}
		return int(math.Max(math.Min(math.Round(v), 1e6), -1e6)), nil
	case string:
		if f, err := strconv.ParseFloat(strings.TrimSuffix(strings.TrimSpace(v), "%"), 64); err == nil {
			return intArg(map[string]any{k: f}, k)
		}
	}
	return 0, fmt.Errorf("%w: %s must be a number", errBadArgs, k)
}

func (t *Tools) setVolume(ctx context.Context, args map[string]any) (map[string]any, error) {
	level, err := intArg(args, "volume")
	if err != nil {
		return nil, err
	}
	applied, err := t.Host.SetVolume(ctx, level)
	if err != nil {
		return nil, err
	}
	return map[string]any{"volume": applied, "requested": level}, nil
}

func (t *Tools) list(ctx context.Context, _ map[string]any) (map[string]any, error) {
	ws, err := t.Host.ListWindows(ctx)
	if err != nil {
		return nil, err
	}
	return map[string]any{"windows": ws}, nil
}

func (t *Tools) windowAction(a host.WindowAction) func(context.Context, map[string]any) (map[string]any, error) {
	return func(ctx context.Context, args map[string]any) (map[string]any, error) {
		id, _ := args["window_id"].(string)
		if id == "" {
			return nil, fmt.Errorf("%w: window_id is required", errBadArgs)
		}
		if err := t.Host.WindowDo(ctx, a, id); err != nil {
			return nil, err
		}
		return map[string]any{"window_id": id, "action": string(a)}, nil
	}
}
