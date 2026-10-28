import argparse
import fcntl
import logging
import math
import signal
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .analysis import UTC, analyze, parse_radar
from .config import Config, load_env
from .reporting import diagnostics_text, report_text
from .sources import RadarClient, SourceError, netblocks_reports, radar_error_detail
from .storage import Store
from .telegram import TelegramClient, TelegramError

LOG = logging.getLogger(__name__)


def demo(output: Path):
    from .chart import render_chart
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 15)
    times = [now - timedelta(minutes=15 * (97 - i)) for i in range(96)]
    baseline = [0.65 + 0.2 * math.sin(i / 96 * 2 * math.pi) for i in range(96)]
    values = [v * (1 if i < 79 else 0.3 if i < 88 else 0.16) for i, v in enumerate(baseline)]
    result = {"meta": {"normalization": "MIN0_MAX", "aggInterval": "FIFTEEN_MINUTES",
                       "confidenceInfo": {"level": 5}, "lastUpdated": now.isoformat()},
              "current": {"timestamps": [t.isoformat() for t in times], "values": values}}
    for week in (1, 2, 3):
        result[f"week{week}"] = {"timestamps": [(t - timedelta(weeks=week)).isoformat() for t in times],
                                "values": [v * (0.96 + 0.02 * week) for v in baseline]}
    assessment = analyze(parse_radar({"success": True, "result": result}), now)
    output.mkdir(parents=True, exist_ok=True)
    (output / "demo.png").write_bytes(render_chart(assessment, demo=True))
    (output / "demo-report.txt").write_text(report_text(assessment, now, [], [], [], demo=True), encoding="utf-8")
    print(f"Demo only, no messages sent. Files: {output.resolve()}/demo.png and demo-report.txt")


def verify_telegram(client):
    bot = client.call("getMe")
    if client.call("getWebhookInfo").get("url"):
        raise ValueError("This bot already has a webhook. Use a dedicated bot or remove that webhook yourself before polling.")
    return bot


def check(config: Config):
    client = TelegramClient(config.bot_token, config.chat_id)
    verify_telegram(client)
    client.call("getChat", {"chat_id": config.chat_id})
    print("Telegram token and owner chat: OK (no message sent)")
    radar = RadarClient(config.radar_token)
    now = datetime.now(UTC)
    result = analyze(parse_radar(radar.traffic(now)), now)
    print(f"Radar traffic API: OK; analytical status: {result.status}")
    if result.reason:
        print(result.reason)
    try:
        print(f"Radar current/recent outages: {len(radar.outages(now))}")
    except (SourceError, ValueError, KeyError, TypeError):
        print("WARNING: Radar outage list unavailable")
    try:
        print(f"NetBlocks Iran reports published in last 48 hours: {len(netblocks_reports(now))}")
        print("No recent feed report does not imply healthy connectivity.")
    except (SourceError, ValueError):
        print("WARNING: NetBlocks feed unavailable; monitoring can still use Radar")


def diagnose(config: Config, *, now=None):
    now = now or datetime.now(UTC)
    client = TelegramClient(config.bot_token, config.chat_id)
    try:
        bot = verify_telegram(client)
        chat = client.call("getChat", {"chat_id": config.chat_id})
        print(f"ربات متصل در Telegram: @{bot.get('username', 'unknown')}")
        print(f"شناسهٔ چت مجاز: {config.chat_id} | نوع چت: {chat.get('type', 'unknown')}")
    except (SourceError, TelegramError, ValueError) as exc:
        print(f"بررسی اتصال Telegram ناموفق بود: {exc}")
        return 2
    try:
        payload = RadarClient(config.radar_token).traffic(now)
    except (SourceError, ValueError, KeyError, TypeError) as exc:
        print(diagnostics_text(now, checked_at=now, fetch_error=radar_error_detail(exc)))
        return 2
    print(diagnostics_text(now, payload, checked_at=now, fetched_at=now))
    return 0


def run(config: Config):
    from .app import Monitor
    from .runtime import BackgroundMonitor, process_updates
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (config.data_dir / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A monitor is already using this DATA_DIR") from None
        client = TelegramClient(config.bot_token, config.chat_id)
        verify_telegram(client)
        store = Store(config.data_dir / "state.sqlite3")
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        worker = BackgroundMonitor(config, client)
        monitor = Monitor(config, store, RadarClient(config.radar_token), client, submit=worker.submit)
        backoff = 5
        worker.start()
        LOG.info("Monitoring started; interval=%ss", config.poll_seconds)
        try:
            while not stop.is_set():
                try:
                    process_updates(monitor, store, client.updates(store.get("telegram_offset", 0)), stop=stop)
                    backoff = 5
                except TelegramError as exc:
                    if exc.code in (401, 409):
                        raise
                    LOG.warning("Telegram request failed (code %s); retrying", exc.code)
                    stop.wait(exc.retry_after)
                except SourceError:
                    LOG.warning("Network/delivery failed; retrying in %ss", backoff)
                    stop.wait(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            worker.close()
            store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Iran traffic monitoring with private Persian Telegram reports")
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Path to credentials file")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("demo", help="Generate a clearly marked offline sample without credentials")
    sample.add_argument("--output", type=Path, default=Path("outputs"))
    commands.add_parser("check", help="Read-only check of credentials and live source formats")
    commands.add_parser("diagnose", help="Read fresh Radar timestamps and source health; sends no Telegram messages")
    commands.add_parser("run", help="Monitor and send alerts to the configured owner")
    commands.add_parser("chat-id", help="Print private chat IDs that have messaged your bot; no messages sent")
    commands.add_parser("configure", help="Enter credentials privately and save the --env file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "demo":
            demo(args.output)
            return 0
        if args.command == "configure":
            from .setup import configure
            configure(args.env)
            return 0
        values = load_env(args.env)
        if args.command == "chat-id":
            token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
            if not token:
                raise ValueError("Set TELEGRAM_BOT_TOKEN in .env, then send /start to your bot")
            client = TelegramClient(token, 0)
            verify_telegram(client)
            updates = client.call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
            ids = {u["message"]["chat"]["id"] for u in updates
                   if u.get("message", {}).get("chat", {}).get("type") == "private"}
            print("Private chat IDs (choose your own): " + (", ".join(map(str, sorted(ids))) if ids else "none; send /start first"))
            return 0
        config = Config.from_values(values)
        if args.command == "diagnose":
            return diagnose(config)
        if args.command == "check":
            check(config)
        else:
            run(config)
        return 0
    except (ValueError, SourceError, TelegramError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
