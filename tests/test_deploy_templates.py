"""Guards on the three supervisor templates.

Every assertion here encodes the same rule from a different angle: **the agent
must run inside the user's interactive desktop session**. Get it wrong and the
agent still starts, still answers /health, and still sets the volume -- while
`open` launches into a session nobody can see and window enumeration returns
nothing. That failure is invisible until someone asks it to open Steam, which
is exactly why it belongs in tests rather than a README note.

These parse files only, so they run on every OS in the matrix.
"""

from __future__ import annotations

import plistlib
import re
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
PORT = "7724"
LOOPBACK = "127.0.0.1"
TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def read(*parts: str) -> str:
    return (DEPLOY.joinpath(*parts)).read_text()


class TestLaunchAgent:
    @pytest.fixture
    def plist(self) -> dict:
        return plistlib.loads(read("launchd", "io.jarvis.host-agent.plist").encode())

    def test_installs_as_a_user_agent_not_a_daemon(self) -> None:
        installer = read("install-macos.sh")
        assert "Library/LaunchAgents" in installer
        # A LaunchDaemon has no window server and cannot hold a TCC grant.
        assert "LaunchDaemons" not in installer
        assert "gui/$(id -u)" in installer, "must bootstrap into the GUI domain"

    def test_does_not_install_system_wide(self) -> None:
        installer = read("install-macos.sh")
        assert "sudo" not in installer, "a per-user agent needs no privilege"

    def test_starts_at_load_and_stays_up(self, plist) -> None:
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True

    def test_marked_interactive(self, plist) -> None:
        assert plist["ProcessType"] == "Interactive"

    def test_binds_loopback_on_the_agreed_port(self, plist) -> None:
        env = plist["EnvironmentVariables"]
        assert env["JARVIS_HOST_AGENT_BIND"] == LOOPBACK
        assert env["JARVIS_HOST_AGENT_PORT"] == PORT

    def test_binary_placeholder_is_substituted_by_the_installer(self, plist) -> None:
        assert plist["ProgramArguments"] == ["__AGENT_BIN__"]
        assert "__AGENT_BIN__" in read("install-macos.sh")


class TestSystemdUserUnit:
    @pytest.fixture
    def unit(self) -> ConfigParser:
        cp = ConfigParser(strict=False)
        cp.optionxform = str
        cp.read_string(read("systemd", "jarvis-host-agent.service"))
        return cp

    def test_is_a_user_unit_not_a_system_unit(self, unit) -> None:
        # multi-user.target is never reached in a user manager, so a unit
        # wanted by it would install cleanly and then never start.
        assert unit["Install"]["WantedBy"] == "default.target"

    def test_never_runs_as_root(self, unit) -> None:
        assert "User" not in unit["Service"]

    def test_installer_uses_the_user_manager(self) -> None:
        installer = read("install-linux.sh")
        assert "systemctl --user" in installer
        assert "sudo systemctl" not in installer
        assert "systemd/user" in installer

    def test_installer_warns_about_linger(self) -> None:
        # Without linger a headless box kills the unit at logout.
        assert "enable-linger" in read("install-linux.sh")

    def test_restarts_on_failure(self, unit) -> None:
        assert unit["Service"]["Restart"] == "on-failure"

    def test_binds_loopback_on_the_agreed_port(self, unit) -> None:
        env = read("systemd", "jarvis-host-agent.service")
        assert f"JARVIS_HOST_AGENT_BIND={LOOPBACK}" in env
        assert f"JARVIS_HOST_AGENT_PORT={PORT}" in env


class TestWindowsScheduledTask:
    @pytest.fixture
    def task(self) -> ET.Element:
        return ET.fromstring(read("windows", "JarvisHostAgent.xml"))

    def find(self, task: ET.Element, path: str) -> str:
        node = task.find(path, TASK_NS)
        assert node is not None and node.text, f"missing {path}"
        return node.text.strip()

    def test_runs_with_an_interactive_token(self, task) -> None:
        """Session 0 has no desktop. This is the whole ballgame on Windows."""
        assert self.find(task, ".//t:Principal/t:LogonType") == "InteractiveToken"

    def test_runs_least_privilege(self, task) -> None:
        # UIPI blocks an elevated process from sending window messages to
        # non-elevated apps, so "run as admin" breaks window control.
        assert self.find(task, ".//t:Principal/t:RunLevel") == "LeastPrivilege"

    def test_never_runs_as_a_system_account(self, task) -> None:
        """Check the declared identities, not the prose.

        An earlier version of this grepped the whole file for "SYSTEM" and
        matched the comment explaining why SYSTEM is wrong -- a guard that
        passes for the wrong reason and would keep passing if the principal
        were changed.
        """
        banned = {"S-1-5-18", "SYSTEM", "LOCALSERVICE", "NETWORKSERVICE", "NT AUTHORITY\\SYSTEM"}
        user_ids = [
            n.text.strip().upper() for n in task.iter() if n.tag.endswith("}UserId") and n.text
        ]
        assert user_ids, "no UserId declared"
        for uid in user_ids:
            assert uid not in banned, f"{uid} runs in Session 0"
            assert uid == "__USER_ID__", "UserId must stay a placeholder"

    def test_triggered_at_logon(self, task) -> None:
        assert task.find(".//t:Triggers/t:LogonTrigger", TASK_NS) is not None

    def test_has_no_execution_time_limit(self, task) -> None:
        # The default PT72H would kill a long-running agent after three days.
        assert self.find(task, ".//t:Settings/t:ExecutionTimeLimit") == "PT0S"

    def test_installer_registers_rather_than_creating_a_service(self) -> None:
        ps1 = read("windows", "Install-HostAgent.ps1")
        assert "Register-ScheduledTask" in ps1
        assert "New-Service" not in ps1
        assert "sc.exe" not in ps1

    def test_xml_declaration_matches_actual_encoding(self) -> None:
        # A UTF-16 declaration on UTF-8 bytes makes every parser reject it.
        raw = read("windows", "JarvisHostAgent.xml")
        assert 'encoding="UTF-8"' in raw.split("\n")[0]


class TestAllThreeAgree:
    @pytest.mark.parametrize(
        "parts",
        [
            ("launchd", "io.jarvis.host-agent.plist"),
            ("systemd", "jarvis-host-agent.service"),
            ("windows", "JarvisHostAgent.xml"),
        ],
    )
    def test_same_port_everywhere(self, parts) -> None:
        text = read(*parts)
        # Windows takes the port from config defaults rather than env, so only
        # assert that no OTHER port is hardcoded anywhere.
        ports = set(re.findall(r"77\d\d", text))
        assert ports <= {PORT}, f"unexpected port(s) {ports - {PORT}} in {parts[-1]}"

    @pytest.mark.parametrize(
        "parts",
        [
            ("launchd", "io.jarvis.host-agent.plist"),
            ("systemd", "jarvis-host-agent.service"),
            ("windows", "JarvisHostAgent.xml"),
        ],
    )
    def test_binary_path_is_a_placeholder(self, parts) -> None:
        assert "__AGENT_BIN__" in read(*parts)

    def test_every_template_explains_the_session_requirement(self) -> None:
        """The reasoning must survive in the file, not just in a commit message."""
        for parts in (
            ("launchd", "io.jarvis.host-agent.plist"),
            ("systemd", "jarvis-host-agent.service"),
            ("windows", "JarvisHostAgent.xml"),
        ):
            text = read(*parts).lower()
            assert any(k in text for k in ("session", "window server", "graphical")), (
                f"{parts[-1]} does not say why it must be user-scoped"
            )
