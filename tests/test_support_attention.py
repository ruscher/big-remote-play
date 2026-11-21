"""Share → Support → Check this computer: pending items are visible outside
Support (its tab and Share in the sidebar), and every row opens what is
happening and what to do."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from big_remote_play.host import health_checks as hc  # noqa: E402
from big_remote_play.ui.support_center import ATTENTION_ICON, SupportCenter  # noqa: E402
from test_ui_task_flows import ui as _ui_fixture, drain  # noqa: E402

ui = _ui_fixture

HEALTHY = hc.Facts(
    sunshine_installed=True,
    sunshine_running=True,
    moonlight_installed=True,
    keyring="available",
    password_known=True,
    password_persisted=True,
    firewall_blocked_ports=(),
    encoders=("AMD (VAAPI)",),
)
PENDING = hc.Facts(
    sunshine_installed=True,
    sunshine_running=True,
    moonlight_installed=True,
    keyring="available",
    password_known=True,
    password_persisted=True,
    firewall_blocked_ports=("47989/tcp",),
    firewall_tool="ufw",
)


def _labels(widget):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            found.append(child.get_label())
        if isinstance(child, Adw.PreferencesRow):
            found.append(child.get_title())
        found.extend(_labels(child))
        child = child.get_next_sibling()
    return found


def _buttons(widget):
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button) and child.get_label():
            found.append(child)
        found.extend(_buttons(child))
        child = child.get_next_sibling()
    return found


def _quiet(host):
    """No real check may land after the simulated ones below."""
    host.support_center.cancel()


def test_pending_checks_mark_the_support_tab_and_share_in_the_sidebar(ui):
    host = ui.host_view
    _quiet(host)
    host.support_center._show(PENDING)
    drain()
    page = host.view_stack.get_page(host.support_page)
    assert page.get_needs_attention() and page.get_icon_name() == ATTENTION_ICON
    assert page.get_badge_number() == 1
    assert ui._nav_attention_icon.get_visible()
    assert "1" in ui._nav_attention_icon.get_tooltip_text()

    host.support_center._show(HEALTHY)
    drain()
    assert not page.get_needs_attention() and page.get_icon_name() == "brp-support-symbolic"
    assert page.get_badge_number() == 0
    assert not ui._nav_attention_icon.get_visible()


def test_the_sidebar_mark_survives_a_rebuilt_navigation_list(ui):
    _quiet(ui.host_view)
    ui.host_view.support_center._show(PENDING)
    drain()
    ui._refresh_nav_list()
    drain()
    assert ui._nav_attention_icon.get_visible()


def test_every_row_opens_what_is_happening_and_what_to_do(ui):
    center = ui.host_view.support_center
    _quiet(ui.host_view)
    center._show(PENDING)
    drain()
    for row, key in list(center._check_rows):
        check = next(item for item in hc.checks(PENDING) if item.key == key)
        assert row.get_activatable()
        row.emit("activated")
        drain()
        dialog = center._detail_dialog
        assert dialog is not None and dialog.get_title() == check.title
        texts = _labels(dialog)
        assert check.explanation in texts
        assert all(step in texts for step in check.steps)
        dialog.close()
        drain()


def test_the_sheet_runs_the_offered_action_after_closing(ui):
    calls = []
    center = SupportCenter(gather=lambda: lambda: PENDING, actions={hc.ACTION_ALLOW_FIREWALL: lambda: calls.append("allow")})
    ui.host_view.support_page.append(center)
    center._show(PENDING)
    firewall = next(check for check in hc.checks(PENDING) if check.key == "firewall")
    dialog = center.open_check(firewall)
    drain()
    actions = [button for button in _buttons(dialog) if button.get_label() == firewall.action_label]
    assert len(actions) == 1  # offered once, at the bottom
    action = actions[0]
    action.emit("clicked")
    drain()
    assert calls == ["allow"]
    assert center._detail_dialog is None
    center.close()


def test_a_sheet_without_an_action_still_offers_check_again(ui):
    center = ui.host_view.support_center
    center._show(HEALTHY)
    session = next(check for check in hc.checks(HEALTHY) if check.key == "session")
    dialog = center.open_check(session)
    drain()
    labels = [button.get_label() for button in _buttons(dialog)]
    assert labels == ["Check again"]
    dialog.close()
    drain()


def test_facts_are_read_on_the_gtk_thread_and_gathered_on_a_worker(ui, monkeypatch):
    """The capture choice is read from its widget before the worker starts."""
    import threading

    host = ui.host_view
    seen = {}

    def fake_gather(**kwargs):
        seen["thread"] = threading.current_thread() is threading.main_thread()
        seen["capture"] = kwargs["configured_capture"]
        return HEALTHY

    monkeypatch.setattr(hc, "gather_facts", fake_gather)
    job = host._support_facts_job()
    assert callable(job)
    thread = threading.Thread(target=job)
    thread.start()
    thread.join(5)
    assert seen["thread"] is False and isinstance(seen["capture"], str)


def test_starting_or_stopping_sharing_checks_again(ui, monkeypatch):
    host = ui.host_view
    scheduled = []
    monkeypatch.setattr(host, "_schedule_support_check", lambda seconds=0: scheduled.append(seconds))
    host._support_checked_hosting = False
    host.is_hosting = True
    host.sync_ui_state()
    assert scheduled == [8]  # after Sunshine opened its capture
    host.is_hosting = False
    host.sync_ui_state()
    assert scheduled == [8, 0]
    host.sync_ui_state()
    assert scheduled == [8, 0]  # nothing changed: no new check


def test_a_missing_sharing_program_installs_in_place(ui, monkeypatch):
    import big_remote_play.ui.dependency_installer as installer

    opened = []

    class FakeDialog:
        def __init__(self, ids, **kwargs):
            opened.append(tuple(ids))

        def present(self, _parent):
            pass

    monkeypatch.setattr(installer, "InstallDialog", FakeDialog)
    ui.host_view.support_center._actions[hc.ACTION_INSTALL]()
    ui.host_view.support_center._actions[hc.ACTION_INSTALL_RECEIVER]()
    assert opened == [("sunshine",), ("moonlight",)]
