"""The controller Sunshine makes for the other device's own controls.

Seen on 2026-11-19: with Sunshine's automatic choice (an Xbox Series controller
over Bluetooth HID) Double Dragon Gaiden, run through Proton, took only the
Guide button; as an Xbox 360 controller every button worked. A controller left
by Sunshine also became player 1 ahead of the on-screen controller.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from big_remote_play.host import touch_control  # noqa: E402
from test_ui_task_flows import ui as _ui_fixture  # noqa: E402

ui = _ui_fixture

PHONE_PAD = """I: Bus=0005 Vendor=045e Product=028e Version=0114
N: Name="Sunshine (libvirtualhid) X-Box 360 Controller"
H: Handlers=event31 js2
"""
OTHERS = """I: Bus=0003 Vendor=1209 Product=b1c0 Version=0001
N: Name="Big WM Virtual Gamepad"
H: Handlers=event30 js1

I: Bus=0006 Vendor=0000 Product=0000 Version=0000
N: Name="libvirtualhid Mouse (Absolute)"
H: Handlers=event27 js0 mouse2
"""


def test_xbox_360_is_the_default_and_unknown_values_fall_back_to_it():
    assert touch_control.DEFAULT_GAMEPAD == "x360"
    assert touch_control.gamepad_setting("xseries") == "xseries"
    assert touch_control.gamepad_setting("auto") == "auto"
    for bad in (None, "", "ds9", 3, "x360; rm"):
        assert touch_control.gamepad_setting(bad) == "x360"


def test_only_sunshines_own_controller_counts_as_the_phones():
    assert touch_control.sunshine_gamepad_present(OTHERS + "\n" + PHONE_PAD)
    # The on-screen controller and Sunshine's absolute mouse (it has a js node) are not it.
    assert not touch_control.sunshine_gamepad_present(OTHERS)
    assert not touch_control.sunshine_gamepad_present("")


def test_sharing_writes_the_chosen_controller_type(ui):
    host = ui.host_view
    assert host._build_sunshine_config()["gamepad"] == "x360"
    host.gamepad_row.set_selected(touch_control.GAMEPAD_TYPES.index("xseries"))
    assert host._build_sunshine_config()["gamepad"] == "xseries"
