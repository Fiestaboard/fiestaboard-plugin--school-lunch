"""Tests for the school_lunch plugin."""

from datetime import datetime
from unittest.mock import patch

import pytest
import pytz
import requests

from plugins.school_lunch import SchoolLunchPlugin


MANIFEST = {
    "id": "school_lunch",
    "name": "School Lunch Menu",
    "version": "1.0.0",
    "min_refresh_seconds": 900,
    "settings_schema": {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "default": False},
            "refresh_seconds": {
                "type": "integer",
                "default": 3600,
                "minimum": 900,
                "maximum": 86400,
            },
        },
    },
}

BASE_CONFIG = {
    "enabled": True,
    "district": "lwsd",
    "school": "cougar-creek-elementary",
    "menu_type": "lunch",
    "timezone": "America/Los_Angeles",
    "max_items": 4,
    "show_tomorrow_after_hour": 13,
}


def food(name, category="entree"):
    """A normal menu item entry."""
    return {
        "is_section_title": False,
        "is_holiday": False,
        "no_school_text": None,
        "text": "",
        "category": category,
        "food": {"name": name},
    }


def section(title):
    """A section-title entry (names the section for the items that follow)."""
    return {
        "is_section_title": True,
        "is_holiday": False,
        "no_school_text": None,
        "text": title,
        "category": "",
        "food": None,
    }


def holiday(text):
    """A no-school entry."""
    return {
        "is_section_title": False,
        "is_holiday": True,
        "no_school_text": text,
        "text": "",
        "category": "",
        "food": None,
    }


def week(days):
    """Build a Nutrislice week payload from {iso_date: [entries]}."""
    return {
        "start_date": min(days),
        "menu_type_id": 1,
        "days": [{"date": d, "has_unpublished_menus": False, "menu_items": items} for d, items in sorted(days.items())],
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


LUNCH_WEEK = week(
    {
        "2026-09-14": [
            section("Lunch"),
            food("Crispy Chicken Patty Sandwich", "entree"),
            food("Fresh Red Delicious Apple", "fruit"),
            food("Sliced Cucumbers", "vegetable"),
            food("Ketchup Packet", "condiment"),
            food("Ranch Dressing", "condiment"),
        ],
        "2026-09-15": [
            section("Lunch"),
            food("Cheese Pizza", "entree"),
            section("Sides"),
            food("Seasoned Peas", "vegetable"),
            food("", "fruit"),  # empty food name -> skipped
            food("Seasoned Peas", "vegetable"),  # duplicate -> skipped
        ],
        "2026-09-16": [holiday("Teacher In-Service Day")],
        "2026-09-17": [],
        "2026-09-18": [],
    }
)


def make_plugin(**overrides):
    plugin = SchoolLunchPlugin(MANIFEST)
    plugin.config = {**BASE_CONFIG, **overrides}
    return plugin


def at(year, month, day, hour, tz="America/Los_Angeles"):
    return pytz.timezone(tz).localize(datetime(year, month, day, hour, 0))


class TestSchoolLunchPlugin:
    def test_plugin_id(self):
        assert make_plugin().plugin_id == "school_lunch"

    def test_fetch_data_returns_all_declared_variables(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.available is True
        data = result.data
        assert set(data) == {
            "menu_date",
            "menu_weekday",
            "is_today",
            "headline",
            "items_text",
            "item_count",
            "no_school",
            "no_school_text",
            "items",
        }
        assert data["menu_date"] == "Sep 14"
        assert data["menu_weekday"] == "Monday"
        assert data["is_today"] == "true"
        assert data["headline"] == "Crispy Chicken Patty S"
        assert data["item_count"] == "4"
        assert data["no_school"] == "false"
        assert data["no_school_text"] == ""
        assert data["items_text"].startswith("Crispy Chicken Patty Sandwich, Fresh Red")
        assert len(data["items"]) == 4

    def test_request_url_and_headers(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ) as mock_get:
            plugin.fetch_data()

        url = mock_get.call_args[0][0]
        assert url == (
            "https://lwsd.api.nutrislice.com/menu/api/weeks/school/cougar-creek-elementary"
            "/menu-type/lunch/2026/09/14/"
        )
        assert mock_get.call_args[1]["timeout"] == 10
        assert "FiestaBoard" in mock_get.call_args[1]["headers"]["User-Agent"]

    def test_section_titles_are_attributed_to_following_items(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 15, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        items = result.data["items"]
        assert items[0] == {"name": "Cheese Pizza", "section": "Lunch"}
        assert items[1] == {"name": "Seasoned Peas", "section": "Sides"}

    def test_empty_names_and_duplicates_are_skipped(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 15, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        names = [i["name"] for i in result.data["items"]]
        assert names == ["Cheese Pizza", "Seasoned Peas"]
        assert result.data["item_count"] == "2"

    def test_no_school_day(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 16, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.available is True
        assert result.data["no_school"] == "true"
        assert result.data["no_school_text"] == "Teacher In-Service Day"
        assert result.data["items"] == []
        assert result.data["headline"] == ""

    def test_after_hour_rolls_over_to_tomorrow(self):
        plugin = make_plugin()
        # 2pm on Monday the 14th -> show Tuesday the 15th
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 14)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.data["menu_date"] == "Sep 15"
        assert result.data["menu_weekday"] == "Tuesday"
        assert result.data["is_today"] == "false"

    def test_before_hour_keeps_today(self):
        plugin = make_plugin(show_tomorrow_after_hour=17)
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 16)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.data["menu_date"] == "Sep 14"
        assert result.data["is_today"] == "true"

    def test_weekend_skips_ahead_to_monday(self):
        plugin = make_plugin()
        # Saturday the 12th -> Sat/Sun skipped without a fetch, lands on Monday
        with patch.object(plugin, "_now", return_value=at(2026, 9, 12, 20)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ) as mock_get:
            result = plugin.fetch_data()

        assert result.data["menu_weekday"] == "Monday"
        assert result.data["menu_date"] == "Sep 14"
        assert mock_get.call_count == 1

    def test_days_without_items_are_skipped(self):
        plugin = make_plugin()
        # Thursday the 17th and Friday the 18th are empty -> nothing in range
        with patch.object(plugin, "_now", return_value=at(2026, 9, 17, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.available is False
        assert "No lunch menu published" in result.error

    def test_http_404_gives_helpful_error(self):
        plugin = make_plugin(school="not-a-real-school")
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse({}, status_code=404)
        ):
            result = plugin.fetch_data()

        assert result.available is False
        assert "not-a-real-school" in result.error
        assert "check the slugs" in result.error

    def test_connection_error_mentions_district(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", side_effect=requests.ConnectionError("boom")
        ):
            result = plugin.fetch_data()

        assert result.available is False
        assert "lwsd.api.nutrislice.com" in result.error

    def test_http_500_is_not_available(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse({}, status_code=500)
        ):
            result = plugin.fetch_data()

        assert result.available is False
        assert result.error

    def test_malformed_response_is_not_available(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse({"days": "nope"})
        ):
            result = plugin.fetch_data()

        assert result.available is False

    def test_empty_week_is_not_available(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse({"days": []})
        ):
            result = plugin.fetch_data()

        assert result.available is False

    def test_max_items_is_respected(self):
        plugin = make_plugin(max_items=2)
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ):
            result = plugin.fetch_data()

        assert result.data["item_count"] == "2"
        assert len(result.data["items"]) == 2

    def test_headline_falls_back_to_first_item_without_an_entree(self):
        payload = week({"2026-09-14": [section("Lunch"), food("Garden Salad", "vegetable")]})
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(payload)
        ):
            result = plugin.fetch_data()

        assert result.data["headline"] == "Garden Salad"

    def test_now_uses_configured_timezone(self):
        plugin = make_plugin(timezone="America/New_York")
        assert str(plugin._now().tzinfo) == "America/New_York"


class TestValidateConfig:
    def test_valid_config_has_no_errors(self):
        assert make_plugin().validate_config(BASE_CONFIG) == []

    @pytest.mark.parametrize("field", ["district", "school"])
    def test_empty_slug_is_rejected(self, field):
        errors = make_plugin().validate_config({**BASE_CONFIG, field: ""})
        assert any("required" in e for e in errors)

    @pytest.mark.parametrize(
        "value",
        ["lwsd.nutrislice.com", "a/b", "has space", "https://x"],
    )
    def test_slug_with_dots_slashes_or_spaces_is_rejected(self, value):
        errors = make_plugin().validate_config({**BASE_CONFIG, "district": value})
        assert any("single URL segment" in e for e in errors)

    def test_bad_menu_type_is_rejected(self):
        errors = make_plugin().validate_config({**BASE_CONFIG, "menu_type": "lunch/extra"})
        assert any("Menu type" in e for e in errors)

    def test_invalid_timezone_is_rejected(self):
        errors = make_plugin().validate_config({**BASE_CONFIG, "timezone": "Mars/Olympus"})
        assert any("Invalid timezone" in e for e in errors)

    def test_refresh_below_minimum_is_rejected(self):
        errors = make_plugin().validate_config({**BASE_CONFIG, "refresh_seconds": 60})
        assert any("at least" in e for e in errors)


class TestFormattedDisplay:
    def _display(self, plugin):
        with patch("plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)):
            return plugin.get_formatted_display()

    def test_display_shape_and_header(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)):
            lines = self._display(plugin)

        assert len(lines) == 6
        assert all(len(line) <= 22 for line in lines)
        assert lines[0] == "LUNCH MON SEP 14"
        assert lines[1] == "Crispy Chicken Patty S"

    def test_display_on_a_no_school_day(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 16, 8)):
            lines = self._display(plugin)

        assert lines[0] == "LUNCH WED SEP 16"
        assert lines[1] == "NO SCHOOL"
        assert lines[2] == "Teacher In-Service Day"

    def test_display_returns_none_when_unavailable(self):
        plugin = make_plugin()
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse({}, status_code=404)
        ):
            assert plugin.get_formatted_display() is None

    def test_display_fits_a_note_board(self):
        from src.devices import BoardContext

        plugin = make_plugin()
        note = BoardContext(device_type="note", rows=3, cols=15)
        with patch.object(plugin, "_now", return_value=at(2026, 9, 14, 8)), patch(
            "plugins.school_lunch.requests.get", return_value=FakeResponse(LUNCH_WEEK)
        ), plugin._bound_board(note):
            lines = plugin.get_formatted_display()

        assert len(lines) == 3
        assert all(len(line) <= 15 for line in lines)
        # "LUNCH MON SEP 14" is 16 tiles, so the menu type is dropped
        assert lines[0] == "MON SEP 14"
