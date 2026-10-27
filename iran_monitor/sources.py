"""Official sources only; NetBlocks publications are contextual evidence, not a metric."""

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .analysis import UTC, timestamp, parse_radar

RADAR_URL = "https://api.cloudflare.com/client/v4/radar"
NETBLOCKS_FEED = "https://netblocks.org/feed/"
MAX_RESPONSE = 4 * 1024 * 1024


class SourceError(RuntimeError):
    """Safe to log: never includes request URLs, tokens, or remote error bodies."""

    def __init__(self, message, *, status=None, retry_after=10):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def fetch(url: str, *, headers=None, data=None, timeout=25) -> bytes:
    request = Request(url, data=data, headers={"User-Agent": "IranInternetMonitor/0.1", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise SourceError("Remote response exceeds size limit")
        return body
    except HTTPError as exc:
        retry_after = 10
        try:
            with exc:
                error = json.loads(exc.read(4096))
            retry_after = int((error.get("parameters") or {}).get("retry_after", 10))
        except (ValueError, TypeError, AttributeError, OSError):
            pass
        raise SourceError(f"Remote HTTP error {exc.code}", status=exc.code, retry_after=retry_after) from None
    except (URLError, TimeoutError, OSError):
        raise SourceError("Remote network request failed") from None


def fetch_json(url: str, **kwargs):
    try:
        return json.loads(fetch(url, **kwargs))
    except (ValueError, UnicodeError):
        raise SourceError("Remote response is not valid JSON") from None


@dataclass(frozen=True)
class Report:
    title: str
    url: str
    published: datetime


class RadarClient:
    def __init__(self, token: str, request=fetch_json):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.request = request

    def traffic(self, now: datetime) -> dict:
        # All historical windows MUST share a request to have comparable scaling.
        end = now.astimezone(UTC).replace(second=0, microsecond=0)
        end -= timedelta(minutes=end.minute % 15 + 15)
        params = [("format", "json"), ("aggInterval", "15m"), ("normalization", "MIN0_MAX")]
        for week, name in enumerate(("current", "week1", "week2", "week3")):
            shifted = end - timedelta(weeks=week)
            params += [("name", name), ("location", "IR"), ("product", "ALL"),
                       ("dateStart", (shifted-timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")),
                       ("dateEnd", shifted.strftime("%Y-%m-%dT%H:%M:%SZ"))]
        payload = self.request(f"{RADAR_URL}/netflows/timeseries?{urlencode(params)}", headers=self.headers)
        parse_radar(payload)  # Validate before caching it as a successful fetch.
        return payload

    def outages(self, now: datetime) -> list[dict]:
        query = urlencode({"location": "IR", "dateRange": "7d", "limit": 100, "format": "json"})
        return parse_outages(self.request(f"{RADAR_URL}/annotations/outages?{query}", headers=self.headers), now)


def parse_outages(payload: dict, now: datetime) -> list[dict]:
    if payload.get("success") is not True:
        raise ValueError("Radar outages API did not return success")
    items = payload["result"]["annotations"]
    result = []
    for item in items:
        if "IR" not in item.get("locations", []) or item.get("eventType") != "OUTAGE":
            continue
        start = timestamp(item["startDate"])
        end = timestamp(item["endDate"]) if item.get("endDate") else now
        if start <= now and end >= now - timedelta(hours=1):
            result.append(item)
    return result


def plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value)).split())


def parse_netblocks(body: bytes, now: datetime) -> list[Report]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Feed contains unsupported XML declarations")
    root = ET.fromstring(body.lstrip())
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected a NetBlocks RSS channel")
    reports = []
    for item in root.findall("./channel/item"):
        title = plain_text(item.findtext("title", ""))
        description = plain_text(item.findtext("description", ""))
        if not re.search(r"\biran\b|ایران", title + " " + description, re.IGNORECASE):
            continue
        url = item.findtext("link", "").strip()
        parts = urlparse(url)
        if parts.scheme != "https" or parts.hostname not in ("netblocks.org", "www.netblocks.org"):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                continue
            published = published.astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if now - timedelta(hours=48) <= published <= now:
            reports.append(Report(title[:160], url, published))
    return sorted(reports, key=lambda r: r.published, reverse=True)[:3]


def netblocks_reports(now: datetime) -> list[Report]:
    try:
        return parse_netblocks(fetch(NETBLOCKS_FEED), now)
    except (ValueError, ET.ParseError):
        raise SourceError("NetBlocks RSS is unavailable or unrecognized") from None
