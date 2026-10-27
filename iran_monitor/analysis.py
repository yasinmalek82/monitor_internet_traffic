"""Pure traffic analysis. Missing measurements never mean zero traffic."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median

STEP = timedelta(minutes=15)
UTC = timezone.utc


def timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Source timestamp has no timezone")
    return dt.astimezone(UTC)


def number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RadarData:
    series: dict[str, dict[datetime, float | None]]
    confidence: float | None
    updated: datetime | None
    annotations: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Point:
    time: datetime
    current: float | None
    baseline: float | None

    @property
    def ratio(self) -> float | None:
        if self.current is None or self.baseline is None or self.baseline <= 1e-9:
            return None
        return self.current / self.baseline


@dataclass(frozen=True)
class Assessment:
    status: str
    reason: str
    points: tuple[Point, ...]
    latest: datetime | None = None
    drop_percent: float | None = None
    duration_minutes: int = 0
    recovery_ready: bool = False


def parse_radar(payload: dict) -> RadarData:
    try:
        if payload.get("success") is not True:
            raise ValueError("Radar API did not return success")
        result = payload["result"]
        meta = result["meta"]
        if meta["normalization"] != "MIN0_MAX":
            raise ValueError("Expected jointly normalized MIN0_MAX traffic")
        if meta["aggInterval"] != "FIFTEEN_MINUTES":
            raise ValueError("Expected 15-minute traffic buckets")
        series = {}
        for name in ("current", "week1", "week2", "week3"):
            item = result[name]
            times, values = item["timestamps"], item["values"]
            if len(times) != len(values):
                raise ValueError("Radar timestamp/value length mismatch")
            parsed_times = [timestamp(t) for t in times]
            if len(set(parsed_times)) != len(parsed_times):
                raise ValueError("Duplicate Radar timestamps")
            series[name] = dict(zip(parsed_times, map(number, values)))
        confidence = meta.get("confidenceInfo") or {}
        return RadarData(
            series, number(confidence.get("level")),
            timestamp(meta["lastUpdated"]) if meta.get("lastUpdated") else None,
            tuple(confidence.get("annotations") or []),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Unrecognized Radar response schema") from exc


def comparison_points(data: RadarData) -> tuple[Point, ...]:
    points = []
    for time, value in sorted(data.series["current"].items()):
        refs = [data.series[f"week{w}"].get(time - timedelta(weeks=w)) for w in (1, 2, 3)]
        valid = [v for v in refs if v is not None and v > 1e-9]
        points.append(Point(time, value, median(valid) if len(valid) >= 2 else None))
    return tuple(points)


def analyze(data: RadarData, now: datetime) -> Assessment:
    # Leave one extra bucket to settle, beyond merely being a completed bucket.
    points = tuple(p for p in comparison_points(data) if p.time + STEP <= now - STEP)
    latest = points[-1].time if points else None

    def unknown(reason):
        return Assessment("unknown", reason, points, latest)

    if not points:
        return unknown("دادهٔ کامل برای تحلیل نداریم.")
    if now - (latest + STEP) > timedelta(minutes=60):
        return unknown("آخرین داده بیش از یک ساعت عقب است؛ وضعیت فعلی مشخص نیست.")
    if data.updated is None or now - data.updated > timedelta(minutes=60):
        return unknown("زمان به‌روزرسانی منبع نامشخص یا قدیمی است.")
    if data.confidence is None or data.confidence < 5:
        return unknown("اطمینان Cloudflare به کیفیت داده کافی نیست.")
    for annotation in data.annotations:
        if annotation.get("eventType") not in ("PIPELINE", "PARTIAL_PROJECTION"):
            continue
        try:
            start = timestamp(annotation["startDate"])
            end = timestamp(annotation["endDate"]) if annotation.get("endDate") else now
        except (ValueError, KeyError, TypeError):
            return unknown("منبع دربارهٔ کیفیت داده هشدار دارد.")
        if start < latest + STEP and end > latest - STEP:
            return unknown("منبع دربارهٔ کامل نبودن یا پردازش دادهٔ این بازه هشدار دارد.")
    if len(points) < 2 or points[-1].time - points[-2].time != STEP:
        return unknown("دو بازهٔ متوالی نداریم؛ فاصلهٔ خالی را قطعی حساب نمی‌کنیم.")
    tail = points[-2:]
    if any(p.ratio is None for p in tail):
        return unknown("دادهٔ تازه یا مرجع تاریخی برای مقایسه کافی نیست.")
    ratios = [p.ratio for p in tail]
    drop = max(0, (1 - ratios[-1]) * 100)
    status = "normal"
    if all(r <= 0.2 for r in ratios):
        status = "critical"
    elif all(r <= 0.5 for r in ratios):
        status = "severe"
    elif any(r < 0.75 for r in ratios):
        status = "watch"
    duration = 0
    previous = latest + STEP
    for point in reversed(points):
        if previous - point.time != STEP or point.ratio is None or point.ratio > 0.5:
            break
        duration += 15
        previous = point.time
    return Assessment(status, "", points, latest, drop, duration, all(r >= 0.8 for r in ratios))
