from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .analysis import Assessment, STEP, parse_radar, timestamp
from .sources import Report

TEHRAN = ZoneInfo("Asia/Tehran")
DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
LABELS = {"normal": "🟢 افت شدید دیده نمی‌شود", "watch": "🟡 افت نیازمند بررسی",
          "severe": "🔴 افت شدید ترافیک", "critical": "🚨 افت بسیار شدید ترافیک",
          "unknown": "⚪ وضعیت فعلی نامشخص"}


def fa(value) -> str:
    return str(value).translate(DIGITS)


def local_time(value: datetime) -> str:
    return fa(value.astimezone(TEHRAN).strftime("%Y/%m/%d %H:%M"))


def report_text(result: Assessment, now: datetime, reports: list[Report], outages: list[dict],
                warnings: list[str], *, kind=None, demo=False, checked_at=None, fetched_at=None) -> str:
    title = "🟢 ترافیک به محدودهٔ مرجع برگشته" if kind == "recovery" else LABELS[result.status]
    if result.status == "unknown" and result.historical_status:
        title = "🕒 گزارش زنده نداریم؛ آخرین وضعیت ثبت‌شده:"
    lines = (["⚠️ نمونهٔ آزمایشی؛ داده‌ها ساختگی‌اند."] if demo else []) + [title]
    if result.status == "unknown":
        lines.append(result.reason)
        if result.historical_status:
            lines.extend(traffic_summary(result, historical=True))
    elif kind == "recovery":
        lines.append("در دو بازهٔ متوالی، ترافیک به دست‌کم ۸۰٪ مرجع رسیده؛ رفع همهٔ محدودیت‌ها ثابت نمی‌شود.")
    else:
        lines.extend(traffic_summary(result))
        if result.status == "watch":
            lines.append("هنوز شرط افت شدیدِ پایدار برقرار نشده.")
    if result.latest:
        end = result.latest + STEP
        age = max(0, int((now - end).total_seconds() // 60))
        lines.append(f"زمان داده: {local_time(end)} تهران — {fa(age)} دقیقه پیش.")
    if result.status == "unknown":
        if fetched_at and checked_at == fetched_at and now - fetched_at <= timedelta(minutes=1):
            lines.append("Radar پاسخ داد، اما پاسخ برای گزارش زنده کافی نبود.")
        elif checked_at:
            lines.append(f"آخرین تلاش برای دریافت: {local_time(checked_at)} تهران.")
        lines.append("برای بررسی علت عقب‌ماندن داده: /diagnostics")
    if result.status != "unknown" or result.historical_status:
        lines.append("مقایسه با همین ساعت و روز در هفته‌های قبل است.")
    if result.status in ("severe", "critical"):
        lines.append("علت افت از این نمودار به‌تنهایی مشخص نمی‌شود.")
    if outages:
        scopes = {"NATIONWIDE": "کشوری", "REGIONAL": "منطقه‌ای", "NETWORK": "اپراتوری", "PLATFORM": "سرویسی"}
        scope = scopes.get((outages[0].get("outage") or {}).get("outageType"), "نامشخص")
        lines.append(f"Radar رخداد مرتبط ثبت کرده؛ دامنهٔ اعلام‌شده: {scope}.")
    if "netblocks" in warnings:
        lines.append("NetBlocks: دریافت گزارش ممکن نشد؛ تأیید مستقل نداریم.")
    elif reports:
        lines.append(f"NetBlocks: گزارش تازهٔ مرتبط با ایران ({local_time(reports[0].published)}):\n{reports[0].url[:180]}")
    elif result.status in ("severe", "critical"):
        lines.append("NetBlocks: گزارش تازه برای مقایسه نداریم.")
    if "outages" in warnings:
        lines.append("فهرست رخدادهای Radar در دسترس نبود.")
    lines.append("منبع: ترافیک دیده‌شده در Cloudflare\nhttps://radar.cloudflare.com/traffic/ir")
    return "\n".join(lines)[:1024]


def traffic_summary(result: Assessment, *, historical=False) -> list[str]:
    prefix = "در آن زمان، " if historical else ""
    if result.drop_percent is not None and result.drop_percent >= 10:
        lines = [f"{prefix}ترافیک حدود {fa(f'{result.drop_percent:.0f}')}٪ کمتر از روال این ساعت بود."]
    else:
        lines = [f"{prefix}افت قابل‌توجهی نسبت به روال این ساعت دیده نشد."]
    if result.duration_minutes:
        lines.append(f"افت حداقل ۵۰٪ در {fa(result.duration_minutes)} دقیقهٔ متوالی ثبت شده بود.")
    return lines


def diagnostics_text(now: datetime, payload=None, *, checked_at=None, fetched_at=None, fetch_error=None) -> str:
    def stamp(value):
        return f"{local_time(value)} تهران | UTC {value.isoformat()}" if value else "ثبت نشده"

    lines = ["بررسی سلامت پایش", f"ساعت سرور: {stamp(now)}",
             f"آخرین تلاش دریافت: {stamp(checked_at)}", f"آخرین دریافت موفق: {stamp(fetched_at)}"]
    if fetch_error:
        lines.append(f"نتیجهٔ دریافت: {fetch_error}")
    if payload:
        try:
            data = parse_radar(payload)
            latest = max(data.series["current"], default=None)
            lines.append(f"آخرین بازهٔ پاسخ Radar: {stamp(latest + STEP if latest else None)}")
            complete = max((t for t in data.series["current"] if t + STEP <= now - STEP), default=None)
            lines.append(f"آخرین بازهٔ کاملِ قابل استفاده: {stamp(complete + STEP if complete else None)}")
            lines.append(f"به‌روزرسانی اعلام‌شدهٔ Radar: {stamp(data.updated)}")
            lines.append(f"کیفیت اعلام‌شده: {data.confidence} از 5")
            lines.append(f"تعداد نقاط پاسخ امروز: {len(data.series['current'])}")
            ranges = payload["result"]["meta"].get("dateRange") or []
            if isinstance(ranges, dict):
                ranges = [ranges]
            if ranges and ranges[0].get("endTime"):
                lines.append(f"پایان بازهٔ درخواست در پاسخ: {stamp(timestamp(ranges[0]['endTime']))}")
        except (ValueError, KeyError, TypeError):
            lines.append("ساختار دادهٔ ذخیره‌شده معتبر نیست.")
    else:
        lines.append("هنوز پاسخی از ترافیک Radar ذخیره نشده است.")
    return "\n".join(lines)
