"""School Lunch Menu plugin for FiestaBoard.

Shows today's (or tomorrow's) school menu from Nutrislice, the menu
platform used by many US school districts. No API key is required.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import logging

import pytz
import requests

from src.devices import BoardContext
from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

API_URL = (
    "https://{district}.api.nutrislice.com/menu/api/weeks/school/{school}"
    "/menu-type/{menu_type}/{year}/{month:02d}/{day:02d}/"
)
USER_AGENT = "FiestaBoard (https://github.com/FiestaBoard/FiestaBoard)"
DEFAULT_TIMEZONE = "America/Los_Angeles"
LOOK_AHEAD_DAYS = 7

# One row is spent on the "LUNCH TUE SEP 16"-style header in the whole-board
# render; every other row is available for menu items. Item count is derived
# from this, never fixed, so a taller board shows more items.
HEADER_ROWS = 1

# Ceiling for single-line text fields (headline, no_school_text, an item's own
# name). Independent of board width above this point: an entree name has no
# reason to grow past a normal food-name length just because the board is
# 120 tiles wide. Below it, still bounded by the board so it never overflows
# a Note or a narrow array unit.
TEXT_FIELD_MAX = 40
SECTION_MAX = 30
ITEMS_TEXT_MAX = 132

# Default and ceiling for the "max_items" setting. The ceiling matches the
# largest board FiestaBoard supports (a 120x24 note array) minus its header
# row, so raising the setting to its maximum always lets a large panel use
# every row it has. The default equals the ceiling too: by default the board
# itself is what limits item count (via _items_capacity), and a user who
# wants fewer items even on a big panel can lower this setting explicitly.
MAX_ITEMS_CEILING = 23


def _validate_slug(value: Any, label: str) -> List[str]:
    """A Nutrislice slug is a single URL path segment (e.g. 'lincoln-elementary')."""
    slug = str(value or "").strip()
    if not slug:
        return [f"{label} slug is required"]
    if any(ch in slug for ch in "./ ") or ":" in slug:
        return [f"{label} slug must be a single URL segment with no dots, slashes or spaces"]
    return []


def _parse_day(day: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a Nutrislice day to its food items and no-school status.

    Section-title entries name the section for the items that follow.
    Items with an empty food name are skipped and duplicates are dropped.
    """
    items: List[Dict[str, str]] = []
    seen = set()
    section = ""
    no_school_text = ""

    for entry in day.get("menu_items") or []:
        if entry.get("is_holiday"):
            no_school_text = (entry.get("no_school_text") or entry.get("text") or "No School").strip()
            continue
        if entry.get("is_section_title"):
            section = (entry.get("text") or "").strip()
            continue
        food = entry.get("food") or {}
        name = " ".join((food.get("name") or "").split())
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        items.append({"name": name, "section": section, "category": entry.get("category") or ""})

    return {"items": items, "no_school": bool(no_school_text), "no_school_text": no_school_text}


class SchoolLunchPlugin(PluginBase):
    """School Lunch Menu plugin.

    Fetches the week's menu from Nutrislice and exposes the next school
    day's items as template variables.
    """

    @property
    def plugin_id(self) -> str:
        return "school_lunch"

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        errors = []
        errors.extend(_validate_slug(config.get("district"), "District"))
        errors.extend(_validate_slug(config.get("school"), "School"))
        errors.extend(_validate_slug(config.get("menu_type", "lunch"), "Menu type"))

        timezone_str = config.get("timezone") or DEFAULT_TIMEZONE
        try:
            pytz.timezone(timezone_str)
        except pytz.exceptions.UnknownTimeZoneError:
            errors.append(f"Invalid timezone: {timezone_str}")

        errors.extend(self._validate_refresh_seconds(config))
        return errors

    def _now(self) -> datetime:
        """Current time in the configured timezone (overridable in tests)."""
        return datetime.now(pytz.timezone(self.config.get("timezone") or DEFAULT_TIMEZONE))

    def _effective_board(self) -> BoardContext:
        """The board to size output for: ``self.board``, or a Flagship default.

        ``self.board`` is ``None`` outside a board-scoped render (unit tests,
        legacy callers); treating that as a Flagship keeps those callers
        working without crashing while still deriving every dimension from a
        real ``BoardContext`` instead of a hardcoded tuple.
        """
        return self.board or BoardContext.from_device_type("flagship")

    def _items_capacity(self, board: BoardContext) -> int:
        """How many item rows fit on *board* once the header row is spent."""
        return max(board.rows - HEADER_ROWS, 1)

    def fetch_data(self) -> PluginResult:
        """Fetch the menu for the next school day with published items."""
        district = self.config.get("district", "")
        menu_type = self.config.get("menu_type") or "lunch"
        try:
            now = self._now()
            picked = self._pick_day(now)
            if picked is None:
                return PluginResult(
                    available=False,
                    error=f"No {menu_type} menu published for the next {LOOK_AHEAD_DAYS} days",
                )
            menu_day, parsed = picked
            data = self._build_data(menu_day, parsed, now.date())
            return PluginResult(available=True, data=data, formatted_lines=self._render_lines(data))

        except requests.ConnectionError:
            return PluginResult(
                available=False,
                error=f"Could not reach {district}.api.nutrislice.com - check the district slug",
            )
        except Exception as e:
            logger.exception("Error fetching school menu")
            return PluginResult(available=False, error=str(e))

    def _pick_day(self, now: datetime) -> Optional[Tuple[date, Dict[str, Any]]]:
        """Return the first weekday from today/tomorrow with items or a no-school notice."""
        start = now.date()
        if now.hour >= int(self.config.get("show_tomorrow_after_hour", 13)):
            start += timedelta(days=1)

        days: Dict[str, Dict[str, Any]] = {}
        for offset in range(LOOK_AHEAD_DAYS):
            candidate = start + timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            key = candidate.isoformat()
            if key not in days:
                days.update(self._fetch_week(candidate))
            parsed = _parse_day(days.get(key, {}))
            if parsed["items"] or parsed["no_school"]:
                return candidate, parsed
        return None

    def _fetch_week(self, day: date) -> Dict[str, Dict[str, Any]]:
        """Fetch the Nutrislice week containing ``day``, keyed by ISO date."""
        district = self.config.get("district", "")
        school = self.config.get("school", "")
        menu_type = self.config.get("menu_type") or "lunch"
        url = API_URL.format(
            district=district, school=school, menu_type=menu_type,
            year=day.year, month=day.month, day=day.day,
        )
        response = requests.get(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=10,
        )
        if response.status_code == 404:
            raise ValueError(
                f"Nutrislice has no menu for district '{district}', school '{school}', "
                f"menu type '{menu_type}' - check the slugs in the plugin settings"
            )
        response.raise_for_status()

        week = response.json()
        return {d["date"]: d for d in week.get("days") or [] if isinstance(d, dict) and d.get("date")}

    def _build_data(self, menu_day: date, parsed: Dict[str, Any], today: date) -> Dict[str, Any]:
        """Build the template variable dict for the chosen day.

        The item count is derived from the board's own row capacity, capped
        by the user's ``max_items`` setting -- never the other way around --
        so a large panel shows more items by default, and a user can only
        ask for *fewer* than the board can hold, never be stuck at a fixed
        number regardless of board size.
        """
        board = self._effective_board()
        capacity = self._items_capacity(board)
        configured_max = int(self.config.get("max_items", MAX_ITEMS_CEILING))
        max_items = min(configured_max, capacity) if configured_max > 0 else capacity

        all_items = parsed["items"]
        entree = next((i for i in all_items if i["category"] == "entree"), None)
        if entree is None and all_items:
            entree = all_items[0]
        items = all_items[:max_items]

        # Single-line text fields reflow with the board (more cols -> more
        # room) but never exceed TEXT_FIELD_MAX/SECTION_MAX -- the manifest's
        # honest ceiling for what these fields can ever emit.
        headline_max = min(board.cols, TEXT_FIELD_MAX)
        no_school_max = min(board.cols, TEXT_FIELD_MAX)

        return {
            "menu_date": f"{menu_day:%b} {menu_day.day}",
            "menu_weekday": f"{menu_day:%A}",
            "is_today": "true" if menu_day == today else "false",
            "headline": entree["name"][:headline_max] if entree else "",
            "items_text": ", ".join(i["name"] for i in items)[:ITEMS_TEXT_MAX],
            "item_count": str(len(items)),
            "no_school": "true" if parsed["no_school"] else "false",
            "no_school_text": parsed["no_school_text"][:no_school_max],
            "items": [
                {"name": i["name"][:TEXT_FIELD_MAX], "section": i["section"][:SECTION_MAX]} for i in items
            ],
        }

    def _render_lines(self, data: Dict[str, Any]) -> List[str]:
        """Render whole-board display lines for *data*, sized to ``self.board``.

        Shared by :meth:`fetch_data` (the live path -- ``PluginResult.formatted_lines``,
        consumed by ``src/displays/service.py``) and :meth:`get_formatted_display`
        (the documented-but-dead hook) so both stay in sync and both are
        board-aware. ``data["items"]`` is already capped to the board's row
        capacity by :meth:`_build_data`, so no content is dropped here.
        """
        board = self._effective_board()
        rows, cols = board.rows, board.cols
        menu_type = self.config.get("menu_type") or "lunch"

        header = f"{menu_type} {data['menu_weekday'][:3]} {data['menu_date']}".upper()
        if len(header) > cols:
            header = f"{data['menu_weekday'][:3]} {data['menu_date']}".upper()

        lines = [header[:cols]]
        if data["no_school"] == "true":
            lines.append("NO SCHOOL")
            if data["no_school_text"]:
                lines.append(data["no_school_text"][:cols])
        else:
            lines.extend(item["name"][:cols] for item in data["items"])

        lines = lines[:rows]
        while len(lines) < rows:
            lines.append("")
        return lines

    def get_formatted_display(self) -> Optional[List[str]]:
        """Default display: 'LUNCH TUE SEP 16' then item names (or NO SCHOOL)."""
        # Forward self.board explicitly: get_data(board=None) would rebind
        # self.board to None for the duration of the nested fetch, which
        # would make _build_data derive item count from a Flagship even when
        # this call is itself running inside a real bound board (see
        # PluginBase._bound_board / get_data's own docstring on binding).
        result = self.get_data(self.board)
        if not result.available or not result.data:
            return None
        return self._render_lines(result.data)


# Export the plugin class
Plugin = SchoolLunchPlugin
