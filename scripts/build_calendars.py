import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "events.json").read_text())
OUT = ROOT / "docs"
OUT.mkdir(exist_ok=True)
NAMES = {"socal": "SoCal Arts & Culture", "national": "US Arts & Culture", "international": "World Arts & Culture"}

def esc(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

today = date.today()
# Three calendar months ahead, approximated by a 93-day rolling horizon.
horizon = today + timedelta(days=93)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
for slug, name in NAMES.items():
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Creative Edit//Arts Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:" + name]
    for item in DATA.get(slug, []):
        try:
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item.get("end", item["start"]))
        except (KeyError, ValueError):
            continue
        if end < today or start > horizon or end < start:
            continue
        lines += ["BEGIN:VEVENT", "UID:" + esc(item["id"]) + "@creative-edit", "DTSTAMP:" + stamp, "DTSTART;VALUE=DATE:" + start.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + (end + timedelta(days=1)).strftime("%Y%m%d"), "SUMMARY:" + esc(item["title"]), "DESCRIPTION:" + esc(item.get("description", "")), "TRANSP:TRANSPARENT"]
        if item.get("url"):
            lines.append("URL:" + item["url"])
        if item.get("location"):
            lines.append("LOCATION:" + esc(item["location"]))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    (OUT / (slug + ".ics")).write_text("\r\n".join(lines) + "\r\n")
