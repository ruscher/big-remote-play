"""Support → Check this computer: plain-language results from real facts.

GTK-free. :func:`gather_facts` reads this computer (worker thread, read-only:
no package, firewall, keyring write or network change). :func:`checks` turns
those facts into the rows Support shows, each with a state in words and,
when one exists, a safe action the interface offers (never run by itself).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import shutil

from big_remote_play.utils.i18n import _, pgettext

OK = "ok"
WARNING = "warning"
PROBLEM = "problem"
INFO = "info"

# Actions the interface knows how to offer (see ui/support_center.py).
ACTION_START = "start_sharing"
ACTION_ALLOW_FIREWALL = "allow_firewall"
ACTION_FIX_POINTER = "fix_pointer"
ACTION_SAVE_KEYRING = "save_keyring"
ACTION_RETRY_KEYRING = "retry_keyring"
ACTION_ENTER_PASSWORD = "enter_password"
ACTION_INSTALL = "install"  # Sunshine
ACTION_INSTALL_RECEIVER = "install_receiver"  # Moonlight
ACTION_TEST_AUDIO = "test_audio"
ACTION_OPEN_LOG = "open_log"
ACTION_PAIR = "pair"


@dataclass(frozen=True)
class Check:
    """One row of Check this computer.

    ``title``/``detail`` are the short state on the row; ``explanation`` says
    what is happening and why it matters, ``steps`` what to do about it (in
    order). Every row has both, so opening any row answers "what now?".
    """

    key: str
    state: str
    title: str
    detail: str
    action: str = ""
    action_label: str = ""
    explanation: str = ""
    steps: tuple[str, ...] = ()

    @property
    def needs_attention(self) -> bool:
        """A warning or a problem: something to solve before sharing works well."""
        return self.state in (WARNING, PROBLEM)


@dataclass(frozen=True)
class Facts:
    sunshine_installed: bool = False
    sunshine_running: bool = False
    moonlight_installed: bool = False
    session: str = ""
    desktop: str = ""
    unusable_devices: tuple[str, ...] = ()
    keyring: str = "unknown"  # sunshine_credentials.KEYRING_*
    password_known: bool = False
    password_persisted: bool = False
    password_rejected: bool = False
    password_location: str = ""  # sunshine_credentials.LOCATION_* when persisted
    cursor_problem: str = ""
    cursor_fix: str = ""  # capture value that shows the pointer
    cursor_backend: str = ""
    firewall_blocked_ports: tuple[str, ...] | None = None  # None: not checked
    firewall_tool: str = ""
    encoders: tuple[str, ...] = field(default_factory=tuple)


def moonlight_installed(which: Callable[[str], str | None] = shutil.which, home: Path | None = None) -> bool:
    """Installed in a way Big Remote Play can start (a Flatpak needs flatpak itself)."""
    from big_remote_play.guest.moonlight_client import moonlight_command

    return moonlight_command(which, home) is not None


def gather_facts(*, sunshine, credentials_status, configured_capture: str = "", encoders: tuple[str, ...] = (), check_firewall: bool = True, environ: Mapping[str, str] | None = None) -> Facts:
    """Read the facts (worker thread). Each probe is bounded and read-only."""
    from big_remote_play.host.controllers import unusable_devices
    from big_remote_play.host.cursor_check import cursor_report, desktop_session
    from big_remote_play.host.sunshine_manager import sunshine_executable

    running = bool(sunshine.is_running())
    session, desktop = desktop_session(environ)
    cursor = cursor_report(sunshine.config_dir / "sunshine.log", configured=configured_capture, environ=environ) if running else None
    blocked: tuple[str, ...] | None = None
    tool = ""
    if running and check_firewall:
        from big_remote_play.host.firewall_check import check_firewall as firewall

        try:
            report = firewall(int(sunshine.api_port) - 1)
        except Exception:  # a check that cannot run claims nothing
            report = None
        if report is not None:
            blocked = tuple(report.blocked_ports) if report.blocks else ()
            tool = report.tool
    status = credentials_status
    return Facts(
        sunshine_installed=bool(sunshine_executable()),
        sunshine_running=running,
        moonlight_installed=moonlight_installed(),
        session=session,
        desktop=desktop,
        unusable_devices=tuple(unusable_devices()),
        keyring=status.keyring,
        password_known=status.known,
        password_persisted=status.persisted,
        password_rejected=status.rejected,
        password_location=status.location,
        cursor_problem=cursor.problem if cursor else "",
        cursor_fix=cursor.recommended if cursor else "",
        cursor_backend=cursor.backend if cursor else "",
        firewall_blocked_ports=blocked,
        firewall_tool=tool,
        encoders=encoders,
    )


def _session_name(facts: Facts) -> str:
    desktop = {"kde": "KDE Plasma", "gnome": "GNOME"}.get(facts.desktop, facts.desktop.capitalize() or _("an unknown desktop"))
    session = {"wayland": "Wayland", "x11": "X11"}.get(facts.session, _("an unknown session type"))
    # TRANSLATORS: {desktop} is a desktop name such as KDE Plasma; {session} is Wayland or X11.
    return _("{desktop} on {session}").format(desktop=desktop, session=session)


def _check_again() -> str:
    return _("Press Check again to confirm.")


def _keyring_check(facts: Facts) -> Check:
    from big_remote_play.utils.sunshine_credentials import LOCATION_FILE

    approve = _("Sunshine asks for its password whenever a new device is approved with a PIN. Big Remote Play keeps that password so you never have to type it.")
    if facts.password_rejected:
        return Check(
            "keyring",
            PROBLEM,
            _("Sunshine rejected the saved password"),
            _("Devices cannot be approved until the current password is entered."),
            ACTION_ENTER_PASSWORD,
            _("Enter password"),
            _(
                "The password Big Remote Play kept no longer matches Sunshine's. This happens when it was changed in Sunshine's own web page or Sunshine was reinstalled. Until it matches, typing a device's PIN does nothing."
            ),
            (
                _("Press Enter password and type Sunshine's current user name and password."),
                _("If you do not know it, use Change Sunshine password in Preferences → Security and access."),
                _check_again(),
            ),
        )
    if facts.keyring == "unresponsive":
        return Check(
            "keyring",
            WARNING,
            _("The system keyring did not answer"),
            _("It may be locked. Unlock it, then try again. Sharing still works."),
            ACTION_RETRY_KEYRING,
            _("Try again"),
            _(
                "The system keyring (KWallet or GNOME Keyring) is where Big Remote Play keeps Sunshine's password. It did not answer in time, usually because it is locked or a window of its own is waiting for you."
            ),
            (
                _("Look for a KWallet or keyring window, possibly behind this one, and unlock it with your login password."),
                _("Press Try again."),
                _("If no window appears, log out and log in again: the keyring opens with your session."),
            ),
        )
    if facts.password_known and not facts.password_persisted:
        return Check(
            "keyring",
            WARNING,
            _("Password kept only for this session"),
            _("The system keyring did not save it. It works until you close Big Remote Play."),
            ACTION_SAVE_KEYRING,
            _("Save"),
            _("Sunshine's password is in memory only. After Big Remote Play closes, approving a device will ask for it again."),
            (
                _("Unlock the system keyring if it asks, then press Save."),
                _("If Save keeps failing, install a keyring: KWallet on KDE Plasma, GNOME Keyring on other desktops. Then log out and log in again."),
            ),
        )
    if facts.password_persisted and facts.password_location == LOCATION_FILE:
        return Check(
            "keyring",
            OK,
            _("Password saved in a private file"),
            _("No system keyring is available, so a file only your user can read keeps it. Devices are approved with their PIN alone."),
            explanation=approve + "\n\n" + _("Without a system keyring it lives in a file that only your user can open. It works the same; a keyring adds encryption at rest."),
            steps=(
                _("Nothing to do: approving devices works."),
                _("Optional: install KWallet (KDE Plasma) or GNOME Keyring (other desktops), log out and log in again. Big Remote Play then moves the password into the keyring by itself."),
            ),
        )
    if facts.keyring == "unavailable":
        return Check(
            "keyring",
            INFO,
            _("No system keyring"),
            _("Sunshine's password will be kept in a file only your user can read."),
            explanation=approve
            + "\n\n"
            + _("This computer has no system keyring running (KWallet or GNOME Keyring), so the password goes to a private file the first time sharing starts. Sharing works either way."),
            steps=(
                _("Nothing is required: start sharing as usual."),
                _("Recommended: install a keyring with your package manager — on KDE Plasma the packages kwallet and kwalletmanager, on other desktops gnome-keyring."),
                _("Log out and log in again so the keyring starts with your session, then press Check again."),
            ),
        )
    if facts.password_persisted:
        return Check(
            "keyring",
            OK,
            _("Password saved in the system keyring"),
            _("Devices can be approved with their PIN alone."),
            explanation=approve + "\n\n" + _("It is stored encrypted in the system keyring and unlocked with your session."),
            steps=(_("Nothing to do."),),
        )
    return Check(
        "keyring",
        INFO,
        _("System keyring"),
        _("Big Remote Play creates and saves Sunshine's password the first time sharing starts."),
        explanation=approve,
        steps=(_("Start sharing once: the password is created and saved by itself."),),
    )


def checks(facts: Facts) -> list[Check]:
    rows: list[Check] = []
    if not facts.sunshine_installed:
        rows.append(
            Check(
                "sharing",
                PROBLEM,
                _("Sharing program is missing"),
                _("Sunshine shares this computer. Install it to share games and the desktop."),
                ACTION_INSTALL,
                _("Install"),
                _("Sunshine is the program that sends this computer's picture and sound to the other device and receives its mouse, keyboard and controllers. Without it, nothing can be shared."),
                (
                    _("Press Install. Big Remote Play installs Sunshine and asks for your password once."),
                    _("When it finishes, press Check again."),
                ),
            )
        )
    elif facts.sunshine_running:
        rows.append(
            Check(
                "sharing",
                OK,
                _("Sharing is on"),
                _("Sunshine is running and other devices can connect."),
                explanation=_("Sunshine is waiting for devices. Another computer or phone with Moonlight can find this one and connect."),
                steps=(_("Nothing to do. On the other device, open Moonlight and choose this computer."),),
            )
        )
    else:
        rows.append(
            Check(
                "sharing",
                INFO,
                _("Sharing is off"),
                _("Sunshine is installed. Start sharing to let another device connect."),
                ACTION_START,
                _("Start sharing"),
                _("Sunshine is installed but not running, so other devices cannot see this computer yet. Some checks below (mouse pointer, firewall) can only be done while sharing."),
                (_("Press Start sharing."), _("Then press Check again to complete the checks that need sharing.")),
            )
        )

    if facts.moonlight_installed:
        rows.append(
            Check(
                "receiving",
                OK,
                _("Ready to play on other computers"),
                _("Moonlight is installed, so this computer can also connect to another one."),
                explanation=_("Moonlight is the program that receives a shared computer. Sharing this computer does not use it."),
                steps=(_("Nothing to do."),),
            )
        )
    else:
        rows.append(
            Check(
                "receiving",
                INFO,
                _("Moonlight is not installed"),
                _("Needed only to play another computer's games here. Sharing this computer does not need it."),
                ACTION_INSTALL_RECEIVER,
                _("Install"),
                _("Moonlight receives another computer's games. It is optional here: this computer shares with Sunshine."),
                (_("Nothing is required to share this computer."), _("To also play from other computers here, press Install.")),
            )
        )

    session_detail = _("Sunshine chooses how to capture the screen when sharing starts.")
    if facts.cursor_backend:
        session_detail = _("Sunshine captures the screen with {method}.").format(method=facts.cursor_backend.upper() if facts.cursor_backend in ("kms", "x11") else facts.cursor_backend)
    rows.append(
        Check(
            "session",
            INFO,
            _session_name(facts),
            session_detail,
            explanation=_("The desktop and session type decide how Sunshine can capture the screen and draw the mouse pointer. Both Wayland and X11 work."),
            steps=(
                _("Nothing to do."),
                _("If there is no picture, set Capture Method to Automatic in Preferences → Image and capture, then start sharing again."),
            ),
        )
    )

    if facts.unusable_devices:
        rows.append(
            Check(
                "input",
                PROBLEM,
                _("Remote mouse, keyboard and controllers cannot work"),
                _("Sunshine cannot open {devices}, so the other device's input does not reach this computer. Restart this computer once after installing or updating Sunshine.").format(
                    devices=", ".join(facts.unusable_devices)
                ),
                explanation=_(
                    "Sunshine creates a virtual mouse, keyboard and controller through {devices}. Your user is not allowed to open it yet: the permission Sunshine's package installs is applied only when the computer starts."
                ).format(devices=", ".join(facts.unusable_devices)),
                steps=(
                    _("Save your work and restart this computer."),
                    _("Open Support again: this row should say the remote mouse, keyboard and controllers can work."),
                    _("If it still fails, reinstall or update Sunshine, then restart once more."),
                ),
            )
        )
    else:
        rows.append(
            Check(
                "input",
                OK,
                _("Remote mouse, keyboard and controllers can work"),
                _("Sunshine can create its virtual input devices."),
                explanation=_("The other device's mouse, keyboard, touch and controllers reach this computer through virtual devices Sunshine creates."),
                steps=(_("Nothing to do."),),
            )
        )

    if not facts.sunshine_running:
        rows.append(
            Check(
                "pointer",
                INFO,
                _("Mouse pointer"),
                _("Checked while sharing: Sunshine reports whether it can draw the pointer into the picture."),
                explanation=_("Whether the pointer appears in the picture depends on the screen capture Sunshine uses, which is known only while sharing."),
                steps=(_("Start sharing, then press Check again."),),
            )
        )
    elif facts.cursor_problem and facts.cursor_fix:
        rows.append(
            Check(
                "pointer",
                WARNING,
                _("The other device may not see the mouse pointer"),
                _("Sunshine's screen capture cannot draw the pointer on this computer. Another capture method can."),
                ACTION_FIX_POINTER,
                _("Fix"),
                _("The screen capture Sunshine chose cannot draw the pointer here, so the other device sees things move without seeing the pointer."),
                (
                    _("Press Fix and confirm: sharing restarts with a capture method that draws the pointer. Devices playing now reconnect by themselves."),
                    _check_again(),
                ),
            )
        )
    elif facts.cursor_problem:
        rows.append(
            Check(
                "pointer",
                WARNING,
                _("The other device may not see the mouse pointer"),
                _("Sunshine reports that it cannot capture the pointer. In Moonlight, Ctrl+Alt+Shift+N asks Sunshine to draw it again."),
                explanation=_("Sunshine reports that it cannot capture the pointer, and no other capture method on this computer is known to draw it."),
                steps=(
                    _("In Moonlight on the other computer, press Ctrl+Alt+Shift+N."),
                    _("In Preferences → Image and capture, choose another Capture Method, then start sharing again."),
                    _("With Moonlight's “Optimize mouse for remote desktop”, Ctrl+Alt+Shift+C shows the other device's own pointer."),
                ),
            )
        )
    else:
        rows.append(
            Check(
                "pointer",
                OK,
                _("Mouse pointer"),
                _("Sunshine reports no problem drawing the pointer."),
                explanation=_("The pointer is drawn into the picture the other device receives."),
                steps=(_("Nothing to do. If it disappears in Moonlight, Ctrl+Alt+Shift+N shows it again."),),
            )
        )

    rows.append(_keyring_check(facts))

    if facts.firewall_blocked_ports is None:
        rows.append(
            Check(
                "firewall",
                INFO,
                _("Firewall"),
                _("Checked while sharing."),
                explanation=_("The firewall decides whether other computers can reach Sunshine. Its rules are compared with Sunshine's ports only while sharing."),
                steps=(_("Start sharing, then press Check again."),),
            )
        )
    elif facts.firewall_blocked_ports:
        rows.append(
            Check(
                "firewall",
                PROBLEM,
                _("The firewall blocks other computers"),
                _("{tool} does not allow Sunshine's ports ({ports}).").format(tool=facts.firewall_tool or _("The firewall"), ports=", ".join(facts.firewall_blocked_ports)),
                ACTION_ALLOW_FIREWALL,
                _("Allow"),
                _("Other computers reach Sunshine through these ports: {ports}. The firewall refuses them, so the other device may not find this computer or may fail to connect.").format(
                    ports=", ".join(facts.firewall_blocked_ports)
                ),
                (
                    _("Press Allow and confirm. Only Sunshine's streaming and discovery ports are opened; its administration page stays closed. Your password is asked once."),
                    _check_again(),
                ),
            )
        )
    else:
        rows.append(
            Check(
                "firewall",
                OK,
                _("The firewall lets other computers in"),
                _("Sunshine's ports are reachable from the local and private networks."),
                explanation=_("Other computers on the local network or the private network can reach Sunshine."),
                steps=(_("Nothing to do."),),
            )
        )

    hardware = [name for name in facts.encoders if name]
    if hardware:
        rows.append(
            Check(
                "picture",
                OK,
                _("Video encoding"),
                _("Available: {encoders}").format(encoders=", ".join(hardware)),
                explanation=_("The graphics card compresses the picture, which keeps the stream smooth and the processor free for the game."),
                steps=(_("Nothing to do."),),
            )
        )
    else:
        rows.append(
            Check(
                "picture",
                INFO,
                _("Video encoding"),
                _("Sunshine chooses the graphics card when sharing starts. Without one, video uses the processor and the picture may be slower."),
                explanation=_("No graphics card encoder was listed for this computer. Sunshine still looks for one when sharing starts."),
                steps=(
                    _("Nothing is required."),
                    _("If the picture is slow, check that the graphics driver is installed (VA-API for AMD and Intel, the proprietary driver for NVIDIA), then restart Big Remote Play."),
                ),
            )
        )
    return rows


def attention(rows: list[Check]) -> list[Check]:
    """The rows that still need something done: warnings and problems."""
    return [row for row in rows if row.needs_attention]


def state_label(state: str) -> str:
    """The state in words: color and icon only repeat it."""
    # TRANSLATORS: status badges of Support → Check this computer, shown next to
    # each result. "Check" is the warning state ("worth a look"), a noun or
    # adjective, never the verb: use the word your desktop shows for a warning.
    return {
        OK: pgettext("check state", "OK"),
        WARNING: pgettext("check state", "Check"),
        PROBLEM: pgettext("check state", "Problem"),
        INFO: pgettext("check state", "Info"),
    }.get(state, state)


def facts_without_secrets(facts: Facts) -> dict[str, object]:
    """For a support report: states only, never a password, token or address."""
    return {
        "sunshine_installed": facts.sunshine_installed,
        "sunshine_running": facts.sunshine_running,
        "moonlight_installed": facts.moonlight_installed,
        "session": facts.session,
        "desktop": facts.desktop,
        "virtual_input_unusable": list(facts.unusable_devices),
        "keyring": facts.keyring,
        "password_saved": facts.password_persisted,
        "password_location": facts.password_location,
        "cursor_capture": facts.cursor_backend,
        "cursor_problem": facts.cursor_problem,
        "firewall_blocks": bool(facts.firewall_blocked_ports),
    }


__all__ = ["Check", "Facts", "attention", "checks", "facts_without_secrets", "gather_facts", "moonlight_installed", "state_label"]
