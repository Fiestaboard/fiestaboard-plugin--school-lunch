# School Lunch Menu Setup

Show your school's lunch menu on your board, straight from your district's [Nutrislice](https://www.nutrislice.com/) site.

## Overview

**What it does:**
- Fetches the published menu for the next school day from Nutrislice
- Shows the day's entrées and sides, or a "no school" notice on holidays
- Rolls over to tomorrow's menu in the afternoon, and skips weekends and unpublished days
- No API key required

**Prerequisites:**
- ✅ Your district uses Nutrislice (its menu site looks like `https://yourdistrict.nutrislice.com`)
- ✅ Internet connection
- ✅ No API key needed — the menu API is public

## Finding Your District and School Slugs

Open your school's menu page in a browser. The URL looks like this:

```
https://lwsd.nutrislice.com/menu/cougar-creek-elementary/lunch
         ^^^^              ^^^^^^^^^^^^^^^^^^^^^^^^  ^^^^^
        district                    school          menu type
```

- **District slug** — the subdomain, before `.nutrislice.com`. Here: `lwsd`
- **School slug** — the path segment after `/menu/`. Here: `cougar-creek-elementary`
- **Menu type** — the last path segment. Here: `lunch`

Each is a single URL segment: lowercase letters, digits and dashes, with no dots or slashes. Don't paste the whole URL into any of the three fields.

> **Can't find your district?** Search for "*your district name* Nutrislice", or look for a "Menus" link on your school's website. If the menu site isn't a `*.nutrislice.com` address, your district uses a different provider and this plugin won't work.

### Menu type is not always "lunch"

Districts name their menus differently — `lunch`, `lunch-menu`, `pre-order-lunch-menu`, `breakfast`, and so on. Always copy the last segment from your own menu URL rather than assuming `lunch`.

### Verifying your slugs

You can check the slugs before saving by requesting the API directly (substitute your own values and today's date):

```bash
curl "https://lwsd.api.nutrislice.com/menu/api/weeks/school/cougar-creek-elementary/menu-type/lunch/2026/09/16/"
```

A `404` means one of the three slugs is wrong. A `200` with menu items means you're set.

To list every school in your district:

```bash
curl "https://lwsd.api.nutrislice.com/menu/api/schools/" | grep -o '"slug":"[^"]*"'
```

## Quick Setup

### 1. Enable the Plugin

**Option A: Web UI**
1. Go to **Integrations** and find "School Lunch Menu"
2. Toggle **Enable School Lunch Menu** to on
3. Click **Save Changes**

**Option B: Environment Variable**

Add to your `.env` file:
```bash
SCHOOL_LUNCH_ENABLED=true
```

### 2. Configure

Click **Configure** and fill in:

- **District Slug** — e.g. `lwsd`
- **School Slug** — e.g. `cougar-creek-elementary`
- **Menu Type** — usually `lunch`; copy it from your menu URL
- **Timezone** — your local IANA timezone, e.g. `America/Los_Angeles`
- **Max Items** — how many menu items to expose (1–6; the board fits about 4)
- **Show Tomorrow After Hour** — from this hour onwards the board shows the *next* school day's menu instead of today's. `13` (1pm) is a good default: lunch is over, so show what's coming tomorrow.
- **Refresh Interval** — how often to re-fetch, in seconds (minimum 900; an hour is plenty since menus rarely change mid-day)

### 3. Use in Templates

Available variables:

| Variable | Example |
|----------|---------|
| `{{school_lunch.menu_date}}` | `Sep 16` |
| `{{school_lunch.menu_weekday}}` | `Tuesday` |
| `{{school_lunch.is_today}}` | `true` / `false` |
| `{{school_lunch.headline}}` | `Classic Pepperoni Pizz` |
| `{{school_lunch.items_text}}` | `Cheese Pizza, Seasoned Peas, ...` |
| `{{school_lunch.item_count}}` | `4` |
| `{{school_lunch.no_school}}` | `true` / `false` |
| `{{school_lunch.no_school_text}}` | `Teacher In-Service Day` |
| `{{school_lunch.items.0.name}}` | `Cheese Pizza` |
| `{{school_lunch.items.0.section}}` | `Lunch` |

### 4. Example Template

```
LUNCH {{school_lunch.menu_weekday}} {{school_lunch.menu_date}}
{{school_lunch.items.0.name}}
{{school_lunch.items.1.name}}
{{school_lunch.items.2.name}}
{{school_lunch.items.3.name}}
```

Leave the template empty to use the built-in display instead.

## Configuration Reference

| Setting | Type | Required | Default | Description |
|---------|------|----------|---------|-------------|
| `enabled` | boolean | No | `false` | Enable or disable the plugin |
| `district` | string | **Yes** | — | District subdomain slug |
| `school` | string | **Yes** | — | School slug from the menu URL |
| `menu_type` | string | No | `lunch` | Menu type slug from the menu URL |
| `timezone` | string | No | `America/Los_Angeles` | IANA timezone used to pick the day |
| `max_items` | integer | No | `4` | Menu items to expose (1–6) |
| `show_tomorrow_after_hour` | integer | No | `13` | Hour (0–23) to start showing tomorrow |
| `refresh_seconds` | integer | No | `3600` | Refresh interval (minimum `900`) |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCHOOL_LUNCH_ENABLED` | No | `false` | Enable the school lunch menu feature |

## How the Day Is Chosen

1. Start with today — or tomorrow, if the current hour is at or past **Show Tomorrow After Hour**.
2. Skip Saturdays and Sundays.
3. Skip days with no published menu items and no no-school notice.
4. Look ahead up to 7 days; if nothing is published in that window, the plugin reports "not available".

This means the board naturally rides over long weekends and school breaks without any extra configuration.

## API Information

- **Endpoint:** `GET https://<district>.api.nutrislice.com/menu/api/weeks/school/<school>/menu-type/<menu-type>/<YYYY>/<MM>/<DD>/`
- **Authentication:** None required
- **Rate Limits:** None documented; this plugin fetches a whole week per request and refreshes at most every 15 minutes
- **Format:** JSON

### Sample API Response

```json
{
  "start_date": "2026-09-13",
  "days": [
    {
      "date": "2026-09-14",
      "menu_items": [
        {"is_section_title": true, "text": "Lunch", "food": null},
        {"is_section_title": false, "category": "entree", "food": {"name": "Crispy Chicken Patty Sandwich"}},
        {"is_section_title": false, "category": "fruit", "food": {"name": "Fresh Red Delicious Apple"}}
      ]
    }
  ]
}
```

## Troubleshooting

### "Nutrislice has no menu for district ..."

One of the three slugs is wrong. Re-read them off your menu URL (see above) — the most common mistakes are pasting the full URL into the district field, and assuming the menu type is `lunch` when your district calls it something else.

### "No lunch menu published for the next 7 days"

Nutrislice genuinely has nothing published for that school and menu type — usually a school break, or the district hasn't uploaded the new term's menus yet. Open the menu page in a browser to confirm.

### "Could not reach ... check the district slug"

The district subdomain doesn't resolve. Check spelling, and check that your network allows outbound HTTPS.

### Menu shows the wrong day

Check the **Timezone** setting and **Show Tomorrow After Hour**. If the board flips to tomorrow's menu too early, raise the hour.

### Checking logs

```bash
docker-compose logs | grep -i "school menu"
```

## Restart After Changes

```bash
docker-compose restart
docker-compose logs -f
```

## Summary

- **Find your slugs** in your Nutrislice menu URL: `https://<district>.nutrislice.com/menu/<school>/<menu-type>`
- **Enable**: `SCHOOL_LUNCH_ENABLED=true`
- **Use in pages**: `{{school_lunch.headline}}`, `{{school_lunch.items.0.name}}`, …
- **No API key needed**

🍎
