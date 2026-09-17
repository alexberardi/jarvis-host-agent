"""Agent error types and their HTTP mappings.

The mapping lives here, once, so all three providers produce identical
status codes for identical conditions. A provider that invents its own
HTTPException is a drift bug -- raise one of these instead.
"""


class HostAgentError(Exception):
    """Base for every error the agent raises deliberately."""

    status_code = 500


class NotSupported(HostAgentError):
    """This host cannot do this, and no amount of retrying will change that.

    501, not 400: the request was well-formed, the platform just has no
    implementation. Wayland forbids cross-app window control; macOS needs an
    Accessibility grant that may be absent; a headless Linux box has no
    compositor at all. Commands are expected to degrade gracefully on this.
    """

    status_code = 501


class WindowNotFound(HostAgentError):
    """The window id is unknown -- usually because it closed mid-request."""

    status_code = 404


class HostOperationFailed(HostAgentError):
    """The platform call was attempted and failed for an unexpected reason."""

    status_code = 502
