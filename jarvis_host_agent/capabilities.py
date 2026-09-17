"""The closed set of capability names.

Capability strings are a wire contract: commands gate on them at install time
and CC decides whether to offer a tool based on them. A typo in a provider
would silently disable a feature, so the set is closed and the contract test
suite rejects any name not listed here.
"""

VOLUME_GET = "volume.get"
VOLUME_SET = "volume.set"
WINDOWS_LIST = "windows.list"
WINDOWS_MINIMIZE = "windows.minimize"
WINDOWS_FOCUS = "windows.focus"
WINDOWS_CLOSE = "windows.close"
OPEN = "open"

KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    {
        VOLUME_GET,
        VOLUME_SET,
        WINDOWS_LIST,
        WINDOWS_MINIMIZE,
        WINDOWS_FOCUS,
        WINDOWS_CLOSE,
        OPEN,
    }
)

# Which capability each window action requires, so the HTTP layer can gate
# without knowing platform specifics.
WINDOW_ACTION_CAPABILITY: dict[str, str] = {
    "minimize": WINDOWS_MINIMIZE,
    "focus": WINDOWS_FOCUS,
    "close": WINDOWS_CLOSE,
}
