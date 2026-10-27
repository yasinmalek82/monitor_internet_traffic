from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .analysis import Assessment
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
                warnings: list[str], *, kind=None, demo=False) -> str:
    title = "🟢 ترافیک به محدودهٔ مرجع برگشته" if kind == "recovery" else LABELS[result.status]
    lines = (["⚠️ نمونهٔ آزمایشی؛ داده‌ها ساختگی‌اند."] if demo else []) + [title]
    if result.status == "unknown":
        lines.append(result.reason)
    elif kind == "recovery":
        lines.append("در دو بازهٔ متوالی، ترافیک به دست‌کم ۸۰٪ مرجع رسیده؛ رفع همهٔ محدودیت‌ها ثابت نمی‌شود.")
    else:
        drop = fa(f"{result.drop_percent:.0f}")
        lines.append(f"ترافیک دیده‌شده در Cloudflare در آخرین بازه، حدود {drop}٪ کمتر از مرجع بوده.")
        if result.duration_minutes:
            lines.append(f"افت حداقل ۵۰٪ در {fa(result.duration_minutes)} دقیقهٔ متوالی دیده شده.")
        if result.status == "watch":
            lines.append("هنوز شرط افت شدیدِ پایدار برقرار نشده.")
    if result.latest:
        lines.append(f"پایان آخرین بازه: {local_time(result.latest + timedelta(minutes=15))} به وقت تهران.")
    if result.status != "unknown":
        lines.append("مرجع: میانهٔ همین ساعت و روز در هفته‌های قبل؛ خط‌چین نمودار یعنی این مرجع.")
    lines.append("این داده کل اینترنت ایران نیست و علت افت یا محدودیت عمدی را به‌تنهایی ثابت نمی‌کند.")
    if outages:
        scopes = {"NATIONWIDE": "کشوری", "REGIONAL": "منطقه‌ای", "NETWORK": "اپراتوری", "PLATFORM": "سرویسی"}
        scope = scopes.get((outages[0].get("outage") or {}).get("outageType"), "نامشخص")
        lines.append(f"Radar رخداد مرتبط ثبت کرده؛ دامنهٔ اعلام‌شده: {scope}.")
    if "netblocks" in warnings:
        lines.append("NetBlocks: دریافت گزارش ممکن نشد؛ تأیید مستقل نداریم.")
    elif reports:
        lines.append(f"NetBlocks: گزارش تازهٔ مرتبط با ایران ({local_time(reports[0].published)}):\n{reports[0].url[:180]}")
    else:
        lines.append("NetBlocks: در خوراک سایت، گزارش مرتبطِ ۴۸ ساعت اخیر یافت نشد؛ این به معنی نبود اختلال نیست.")
    if "outages" in warnings:
        lines.append("فهرست رخدادهای Radar در دسترس نبود.")
    lines.append("منبع نمودار: radar.cloudflare.com/traffic/ir")
    return "\n".join(lines)[:1024]
