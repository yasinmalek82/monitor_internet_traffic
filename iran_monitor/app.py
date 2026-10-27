import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from .analysis import Assessment, UTC, analyze, parse_radar, timestamp
from .chart import render_chart
from .config import Config
from .reporting import local_time, report_text
from .sources import Report, SourceError, netblocks_reports, parse_outages
from .storage import Store, alert_kind
from .telegram import authorized_command

LOG = logging.getLogger(__name__)
HELP = ("نبض اینترنت ایران\n\n/status — وضعیت و توضیح ساده\n/chart — نمودار ۲۴ ساعت اخیر\n"
        "/history — هشدارهای ارسال‌شده\n/sources — وضعیت منابع\n/help — راهنما\n\n"
        "بررسی پیش‌فرض هر ۵ دقیقه است؛ داده‌ها ۱۵ دقیقه‌ای‌اند و تأخیر دارند. "
        "افت حداقل ۵۰٪ برای ۳۰ دقیقه هشدار می‌دهد؛ افت حداقل ۸۰٪ هشدار بسیار شدید است. "
        "پس از بازگشت به دست‌کم ۸۰٪ مرجع برای ۳۰ دقیقه، پیام بهبود می‌آید. "
        "تحلیل فارسی از اعداد تولید می‌شود و به سرویس هوش مصنوعی خارجی نیاز ندارد.")


class Monitor:
    def __init__(self, config: Config, store: Store, radar, telegram,
                 netblocks=netblocks_reports, chart=render_chart):
        self.config, self.store, self.radar, self.telegram = config, store, radar, telegram
        self.netblocks, self.chart = netblocks, chart

    def refresh(self, now: datetime):
        try:
            payload = self.radar.traffic(now)
            self.store.set("snapshot", payload)
            self.store.set("traffic_error", False)
        except (SourceError, ValueError, KeyError, TypeError):
            self.store.set("traffic_error", True)
            LOG.warning("Radar traffic fetch failed; current status is unknown")
        context_checked = self.store.get("context_checked")
        if not context_checked or now - timestamp(context_checked) >= timedelta(minutes=30):
            warnings = []
            try:
                self.store.set("outages", self.radar.outages(now))
            except (SourceError, ValueError, KeyError, TypeError):
                self.store.set("outages", [])
                warnings.append("outages")
            try:
                reports = self.netblocks(now)
                self.store.set("reports", [{**asdict(r), "published": r.published.isoformat()} for r in reports])
            except (SourceError, ValueError, KeyError, TypeError):
                self.store.set("reports", [])
                warnings.append("netblocks")
            self.store.set("warnings", warnings)
            self.store.set("context_checked", now.isoformat())
        result, reports, outages, warnings = self.current(now)
        if result.status == "unknown":
            failures = self.store.get("unknown_count", 0) + 1
            self.store.set("unknown_count", failures)
            if failures >= 3 and not self.store.get("health_alerted", False):
                self.telegram.message("⚪ پایش در سه بررسی متوالی وضعیت را نامشخص دیده است.\n" + result.reason +
                                      "\nاین پیام به معنی قطع اینترنت ایران نیست.")
                self.store.set("health_alerted", True)
            return
        self.store.set("unknown_count", 0)
        if self.store.get("health_alerted", False):
            self.telegram.message("دادهٔ قابل تحلیل دوباره در دسترس است. برای وضعیت تازه /status را بزن.")
            self.store.set("health_alerted", False)
        kind = alert_kind(result, self.store.get("incident", "none"))
        if kind:
            caption = report_text(result, now, reports, outages, warnings, kind=kind)
            self.send_chart(result, caption)
            # Advance incident state only after Telegram acknowledges delivery.
            self.store.set("incident", "none" if kind == "recovery" else kind)
            history = self.store.get("history", [])
            history.append({"kind": kind, "time": now.isoformat(), "drop": result.drop_percent})
            self.store.set("history", history[-100:])
            LOG.info("Delivered %s alert", kind)

    def current(self, now: datetime):
        payload = self.store.get("snapshot")
        if self.store.get("traffic_error", False):
            result = Assessment("unknown", "دریافت تازهٔ داده از Radar ممکن نشد.", ())
        elif payload:
            result = analyze(parse_radar(payload), now)
        else:
            result = Assessment("unknown", "هنوز داده‌ای از Radar دریافت نشده.", ())
        reports = [Report(r["title"], r["url"], timestamp(r["published"])) for r in self.store.get("reports", [])
                   if now - timedelta(hours=48) <= timestamp(r["published"]) <= now]
        outages = parse_outages({"success": True, "result": {"annotations": self.store.get("outages", [])}}, now)
        return result, reports, outages, self.store.get("warnings", [])

    def send_chart(self, result, text):
        try:
            png = self.chart(result)
        except SourceError:
            LOG.warning("Chart worker failed; delivering the report as text")
            self.telegram.message(text + "\nنمودار فعلاً قابل تولید نیست؛ برای تلاش دوباره /chart را بزن.")
            return
        self.telegram.photo(png, text)

    def handle(self, update: dict, now: datetime):
        command = authorized_command(update, self.config.chat_id)
        if command is None:
            return
        if command in ("start", "help"):
            self.telegram.message(HELP)
        elif command in ("status", "chart"):
            result, reports, outages, warnings = self.current(now)
            text = report_text(result, now, reports, outages, warnings)
            if command == "chart":
                self.send_chart(result, text)
            else:
                self.telegram.message(text)
        elif command == "history":
            names = {"severe": "افت شدید", "critical": "افت بسیار شدید", "recovery": "بهبود"}
            items = self.store.get("history", [])[-5:]
            text = "\n".join(f"{local_time(timestamp(e['time']))}: {names[e['kind']]}" for e in items)
            self.telegram.message(text or "هنوز هشداری ارسال نشده است.")
        elif command == "sources":
            checked = self.store.get("context_checked")
            text = "آخرین بررسی منابع مکمل: " + (local_time(timestamp(checked)) if checked else "هنوز انجام نشده")
            text += ("\nCloudflare Radar: دادهٔ عددی و رخدادها\nhttps://radar.cloudflare.com/traffic/ir\n"
                     "NetBlocks: خوراک گزارش‌های سایت؛ انتشار ممکن است با تأخیر یا متوقف باشد.\nhttps://netblocks.org/feed/\n"
                     "نبود گزارش NetBlocks به معنی سالم بودن اینترنت نیست.")
            if self.store.get("warnings"):
                text += "\nدریافت بخشی از منابع مکمل در آخرین بررسی ناموفق بود."
            self.telegram.message(text)
        else:
            self.telegram.message("دستور شناخته نشد؛ /help را بزن.")
