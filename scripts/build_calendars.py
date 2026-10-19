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
        if end < start:
            continue
        if start == end:
            markers = [(start, item["title"], "One-day event")]
        else:
            markers = [(start, "Opens: " + item["title"], "Opening day"), (end, "Last day: " + item["title"], "Closing day")]
        for day, title, label in markers:
            # Retain recent opening markers to help clients reconcile changes.
            if day < today - timedelta(days=120) or day > horizon:
                continue
            details = f"{label}. Full run: {start.isoformat()} through {end.isoformat()}."
            if item.get("description"):
                details += "\n" + item["description"]
            lines += ["BEGIN:VEVENT",
                "UID:" + esc(item["id"] + "-" + day.isoformat()) + "@creative-edit",
                "DTSTAMP:" + stamp,
                "DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"),
                "DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d"),
                "SUMMARY:" + esc(title),
                "DESCRIPTION:" + esc(details),
                "TRANSP:TRANSPARENT"]
            if item.get("url"):
                lines.append("URL:" + item["url"])
            if item.get("location"):
                lines.append("LOCATION:" + esc(item["location"]))
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    (OUT / (slug + ".ics")).write_text("\r\n".join(lines) + "\r\n")
