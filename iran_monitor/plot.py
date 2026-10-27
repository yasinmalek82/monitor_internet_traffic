"""Headless Persian chart. A horizontal 100% line is the historical reference."""

import io
import os
from datetime import timedelta
from pathlib import Path

# Avoid writing Matplotlib's cache outside the project/container's writable data.
os.environ.setdefault("MPLCONFIGDIR", str(Path("data/matplotlib").resolve()))
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from .analysis import Assessment, STEP
from .reporting import LABELS, TEHRAN, fa


def draw_chart(result: Assessment, *, demo=False) -> bytes:
    background, ink = "#101b2c", "#e9f1ff"
    with plt.rc_context({"font.family": "DejaVu Sans", "text.language": "fa", "text.color": ink,
                         "axes.labelcolor": ink, "xtick.color": "#a2b4d0", "ytick.color": "#a2b4d0"}):
        fig, ax = plt.subplots(figsize=(12, 7), dpi=140)
        try:
            fig.set_facecolor(background)
            ax.set_facecolor(background)
            fig.subplots_adjust(left=0.09, right=0.96, top=0.76, bottom=0.23)
            fig.text(0.96, 0.93, "نبض اینترنت ایران", ha="right", fontsize=24, weight="bold")
            label = LABELS[result.status].split(" ", 1)[1]
            fig.text(0.96, 0.86, label, ha="right", fontsize=15, color="#b8c9e4")
            if demo:
                fig.text(0.04, 0.93, "نمونهٔ آزمایشی | دادهٔ ساختگی", ha="left", fontsize=12, color="#ffbf69")
            if result.points:
                indexed = {p.time: p.ratio for p in result.points}
                times, ratios = [], []
                time = result.points[0].time
                while time <= result.points[-1].time:
                    ratio = indexed.get(time)
                    times.append(time)
                    ratios.append(100 * ratio if ratio is not None else float("nan"))
                    time += STEP
                display_status = result.historical_status or result.status
                color = "#ff807b" if display_status in ("severe", "critical") else "#6ad6cf"
                ax.plot(times, ratios, color=color, linewidth=2.8, label="ترافیک نسبت به مرجع")
                ax.fill_between(times, ratios, color=color, alpha=0.1)
                ax.set_xlim(times[0], times[-1] + timedelta(minutes=1))
                ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TEHRAN))
                finite = [r for r in ratios if r == r]
                ceiling = max(120, max(finite, default=100) * 1.1)
                ax.set_ylim(0, ceiling)
            else:
                ax.set_ylim(0, 120)
                ax.set_xticks([])
            ax.axhline(100, color="#98adc9", linestyle=(0, (5, 4)), linewidth=1.5, label="مرجع تاریخی")
            ax.axhline(50, color="#dc6b67", linestyle=":", alpha=0.6)
            ax.axhspan(0, 50, color="#ff6761", alpha=0.05)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: fa(f"{value:.0f}") + "٪"))
            ax.set_ylabel("درصد ترافیک نسبت به مرجع تاریخی", labelpad=12)
            ax.set_xlabel("ساعت به وقت تهران", labelpad=12)
            ax.grid(axis="y", color="#6c83a5", alpha=0.17)
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.legend(loc="upper left", facecolor=background, edgecolor="#2c405d", labelcolor=ink)
            if result.status == "unknown":
                label = "آخرین دادهٔ موجود؛ گزارش زنده نیست" if result.historical_status else "دادهٔ کافی برای نتیجه‌گیری نداریم"
                ax.text(0.5, 0.5, label, transform=ax.transAxes,
                        ha="center", fontsize=17, color="#ffbf69", bbox={"facecolor": background, "alpha": 0.9})
            fig.text(0.96, 0.095, "مرجع: همین ساعت و روز در هفته‌های قبل | عدد ۱۰۰٪ یعنی برابر با مرجع",
                     ha="right", fontsize=11, color="#b8c9e4")
            fig.text(0.96, 0.05, "منبع: داده‌های دیده‌شده در کلادفلر؛ این نمودار سهم کل اینترنت ایران نیست.",
                     ha="right", fontsize=10, color="#8196b3")
            output = io.BytesIO()
            fig.savefig(output, format="png", facecolor=background)
            return output.getvalue()
        finally:
            plt.close(fig)
