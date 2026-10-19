"""Conservative event discovery from configured organizer-owned webpages.

Only accept schema.org Event/ExhibitionEvent/TheaterEvent with explicit, valid
start dates and canonical organizer URLs. Never infer dates from page prose.
Failed sources do not delete existing events. Review discoveries in the audit file.
"""
import json
import re
import hashlib
import ssl
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "sources.json").read_text())
DB = ROOT / "events.json"
AUDIT = ROOT / "discovery-report.json"
HEADERS = {"User-Agent": "CreativeEditCalendarBot/1.0 (+https://github.com/drewransom-dot/calendars)"}
MAX_BYTES = 2_000_000
TODAY = date.today()
LIMIT = TODAY + timedelta(days=93)

class StructuredData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_json = False
        self.blocks = []
        self.current = ""
        self.links = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_json = True
            self.current = ""
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
    def handle_data(self, data):
        if self.in_json:
            self.current += data
    def handle_endtag(self, tag):
        if tag == "script" and self.in_json:
            self.blocks.append(self.current)
            self.in_json = False

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12, context=ssl.create_default_context()) as response:
        if response.status != 200 or "html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("not an HTML response")
        return response.read(MAX_BYTES + 1)[:MAX_BYTES].decode("utf-8", errors="replace")

def objects(node):
    if isinstance(node, list):
        for child in node:
            yield from objects(child)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from objects(node[key])

def event_type(node):
    kinds = node.get("@type", [])
    if isinstance(kinds, str):
        kinds = [kinds]
    return any(str(k).split("/")[-1] in ("Event", "ExhibitionEvent", "TheaterEvent", "VisualArtsEvent", "Festival", "MusicEvent", "DanceEvent", "ScreeningEvent") for k in kinds)

def as_date(value):
    if not isinstance(value, str):
        raise ValueError("missing date")
    return date.fromisoformat(value[:10])

def clean(value):
    return re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()

def parse_event(node, source, slug, page):
    if not event_type(node):
        return None
    title = clean(node.get("name"))
    if len(title) < 5 or len(title) > 180:
        return None
    start = as_date(node.get("startDate"))
    end = as_date(node.get("endDate", node.get("startDate")))
    if end < start or end < TODAY or start > LIMIT or (end - start).days > 550:
        return None
    status = str(node.get("eventStatus", ""))
    if "Cancelled" in status or "Postponed" in status:
        return None
    url = node.get("url") or page
    if isinstance(url, list):
        url = url[0] if url else page
    url = urljoin(page, str(url))
    # Require the detail page to belong to the configured organizer's domain.
    base = urlparse(source["url"]).hostname or ""
    host = urlparse(url).hostname or ""
    if host != base and not host.endswith("." + base):
        return None
    if not url.startswith("https://"):
        return None
    place = node.get("location")
    if isinstance(place, list):
        place = place[0] if place else None
    venue = clean(place.get("name")) if isinstance(place, dict) else ""
    location = venue or source.get("location") or source["name"]
    key = hashlib.sha256((slug + "|" + url + "|" + title.lower() + "|" + start.isoformat()).encode()).hexdigest()[:16]
    return {"id": "auto-" + key, "title": title, "start": start.isoformat(), "end": end.isoformat(), "location": location, "url": url, "description": "Discovered from " + source["name"] + " (organizer structured event data)."}

def scan(source, slug):
    base = source["url"]
    home = urlparse(base).hostname
    queue = [base]
    seen = set()
    found = []
    errors = []
    while queue and len(seen) < 12:
        page = queue.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            html = fetch(page)
            parser = StructuredData()
            parser.feed(html)
            for block in parser.blocks:
                try:
                    for node in objects(json.loads(block)):
                        try:
                            event = parse_event(node, source, slug, page)
                            if event:
                                found.append(event)
                        except (ValueError, TypeError, OverflowError):
                            pass
                except (ValueError, TypeError):
                    pass
            if page == base:
                for href in parser.links:
                    link = urljoin(base, href).split("#")[0]
                    parsed = urlparse(link)
                    if parsed.scheme == "https" and parsed.hostname == home and re.search(r"/(event|exhibition|show|performance|program|calendar)/", parsed.path, re.I):
                        if link not in seen and link not in queue:
                            queue.append(link)
                        if len(queue) >= 20:
                            break
        except Exception as exc:
            errors.append({"page": page, "error": str(exc)[:160]})
    return found, {"source": source["name"], "pages_scanned": len(seen), "found": len(found), "errors": errors}

def main():
    db = json.loads(DB.read_text())
    report = {"generated": datetime.now().isoformat(), "sources": [], "added": [], "possible_duplicates": []}
    changed = False
    for slug, sources in SOURCES.items():
        existing = db.setdefault(slug, [])
        ids = {x["id"] for x in existing}
        fingerprints = {(re.sub(r"[^a-z0-9]", "", x["title"].lower()), x["start"]) for x in existing}
        for source in sources:
            found, summary = scan(source, slug)
            report["sources"].append({"calendar": slug, **summary})
            for event in found:
                fp = (re.sub(r"[^a-z0-9]", "", event["title"].lower()), event["start"])
                if event["id"] in ids or fp in fingerprints:
                    continue
                # Automatic addition requires explicit organizer-supplied structured dates.
                existing.append(event)
                ids.add(event["id"])
                fingerprints.add(fp)
                report["added"].append({"calendar": slug, **event})
                changed = True
    if changed:
        DB.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")
    AUDIT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Scanned {len(report['sources'])} sources; added {len(report['added'])} verified-structure events")
    for source in report["sources"]:
        if source["errors"]:
            print(f"WARNING: {source['source']}: {len(source['errors'])} fetch/parse errors")

if __name__ == "__main__":
    main()
