"""Board-geometry conformance for school_lunch.

Renders the plugin across every board shape FiestaBoard supports (Flagship,
Note, and note arrays from 15x3 up to 120x24 -- also what a FiestaPanel is)
and asserts it never overflows a board, never crashes unbound, and grows its
item list on a taller board rather than staying capped at a fixed number.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from src.plugins.geometry_conformance import assert_board_conformance

from plugins.school_lunch import SchoolLunchPlugin
from tests.test_plugin import BASE_CONFIG, FakeResponse, food, section, week

_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "manifest.json"
MANIFEST = json.loads(_MANIFEST_PATH.read_text())

_MAX_ITEMS_CEILING = MANIFEST["settings_schema"]["properties"]["max_items"]["maximum"]

# More items than even the largest board (a 120x24 note array, 23 rows of
# item capacity once the header row is spent) can show. The growth check is
# only meaningful if a shorter board runs out of *room* before the plugin
# runs out of menu items -- otherwise a flat item count across boards could
# just mean the menu was small that day, not that the board was ignored.
_BIG_DAY = week(
    {
        "2026-09-14": [
            section("Lunch"),
            *(food(f"Menu Item {i:02d}") for i in range(_MAX_ITEMS_CEILING + 5)),
        ],
    }
)


@pytest.fixture(autouse=True)
def _stub_network(monkeypatch):
    """Network is stubbed for every test in this module, not per-call.

    The conformance suite renders the returned plugin many times across many
    board geometries and must never touch the network itself.
    """
    monkeypatch.setattr(
        "plugins.school_lunch.requests.get",
        lambda *args, **kwargs: FakeResponse(_BIG_DAY),
    )


def make_plugin() -> SchoolLunchPlugin:
    """Fresh, ready-to-render plugin: configured, with network already stubbed."""
    plugin = SchoolLunchPlugin(MANIFEST)
    plugin.config = {**BASE_CONFIG, "max_items": _MAX_ITEMS_CEILING}
    fixed_now = pytz.timezone("America/Los_Angeles").localize(datetime(2026, 9, 14, 8, 0))
    plugin._now = lambda: fixed_now
    return plugin


def test_renders_on_every_board_shape():
    assert_board_conformance(
        make_plugin,
        manifest=MANIFEST,
        strict_growth=True,
        require_note_array_preview=True,
    )
