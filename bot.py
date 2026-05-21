import os
import csv
import io
import requests
from datetime import datetime
from pathlib import Path
import pytz

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, required on headless servers
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TW_TZ = pytz.timezone("Asia/Taipei")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

FOCUS_STOCKS = {"2330": "台積電", "0050": "元大台灣50"}

# Taiwan convention: red = up, green = down
COLOR_UP = "#D0021B"
COLOR_DOWN = "#00A651"
CHART_PATH = "chart.png"


def parse_number(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return 0.0


def roc_to_gregorian(roc_date: str) -> str:
    """Convert '115/05/21' (ROC calendar) to '2026/05/21'."""
    parts = roc_date.split("/")
    return f"{int(parts[0]) + 1911}/{parts[1]}/{parts[2]}"


def is_weekly_summary() -> bool:
    """Return True on Fridays — triggers weekly chart generation."""
    return datetime.now(TW_TZ).weekday() == 4  # 0=Mon … 4=Fri


def _setup_cjk_font() -> None:
    """
    Try to configure matplotlib to use a CJK font.
    Checks known Linux paths first (GitHub Actions), then font names (Windows/Mac).
    """
    linux_font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for path in linux_font_paths:
        if Path(path).exists():
            fm.fontManager.addfont(path)
            plt.rcParams["font.family"] = fm.FontProperties(fname=path).get_name()
            return

    available = {f.name for f in fm.fontManager.ttflist}
    for name in ["Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", "WenQuanYi Micro Hei"]:
        if name in available:
            plt.rcParams["font.family"] = name
            return


# ── Data fetching ──────────────────────────────────────────────────────────────

def get_market_data() -> dict | None:
    """Fetch today's TAIEX index from TWSE FMTQIK (most recent row)."""
    url = "https://www.twse.com.tw/exchangeReport/FMTQIK?response=json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    if not rows:
        return None
    r = rows[-1]
    # columns: 日期, 成交股數, 成交金額, 成交筆數, 發行量加權股價指數, 漲跌點數
    index_val = parse_number(r[4])
    change_val = parse_number(r[5])
    prev = index_val - change_val
    return {
        "date": roc_to_gregorian(r[0]),
        "index": index_val,
        "change": change_val,
        "pct": (change_val / prev * 100) if prev else 0.0,
        "amount": parse_number(r[2]),
    }


def get_weekly_taiex(n: int = 5) -> list[dict]:
    """Return the last n trading-day rows from FMTQIK for the weekly chart."""
    url = "https://www.twse.com.tw/exchangeReport/FMTQIK?response=json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    result = []
    for r in rows[-n:]:
        result.append({
            "date": roc_to_gregorian(r[0]),
            "index": parse_number(r[4]),
            "change": parse_number(r[5]),
        })
    return result


def get_all_stocks() -> dict[str, dict]:
    """Fetch STOCK_DAY_ALL CSV; returns dict keyed by stock code."""
    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return {
        row.get("證券代號", "").strip(): row
        for row in reader
        if row.get("證券代號", "").strip()
    }


# ── Message formatting ─────────────────────────────────────────────────────────

def format_change(change: float, pct: float) -> str:
    arrow = "📈" if change >= 0 else "📉"
    sign = "+" if change >= 0 else ""
    return f"{arrow} `{sign}{change:,.2f}` ({sign}{pct:.2f}%)"


def build_message(market: dict, stocks_data: dict[str, dict]) -> str:
    amount_yi = market["amount"] / 1e8
    lines = [
        f"📊 *台股盤後焦點*  {datetime.now(TW_TZ).strftime('%Y/%m/%d')}",
        "",
        "🏦 *加權指數*",
        f"指數：`{market['index']:,.2f}`  {format_change(market['change'], market['pct'])}",
        f"成交金額：`{amount_yi:,.0f}` 億元",
        "",
        "─────────────────",
        "📌 *焦點個股*",
    ]
    for code, name in FOCUS_STOCKS.items():
        row = stocks_data.get(code)
        if row is None:
            lines.append(f"\n🔷 *{name}* ({code})\n  ⚠️ 今日無資料")
            continue
        close = parse_number(row.get("收盤價", "0"))
        change = parse_number(row.get("漲跌價差", "0"))
        prev = close - change
        pct = (change / prev * 100) if prev else 0.0
        lines.append(f"\n🔷 *{name}* ({code})")
        lines.append(f"收盤：`{close:,.2f}`  {format_change(change, pct)}")
    return "\n".join(lines)


# ── Chart ──────────────────────────────────────────────────────────────────────

def draw_weekly_chart(weekly: list[dict], output_path: str = CHART_PATH) -> None:
    _setup_cjk_font()

    dates = [d["date"] for d in weekly]
    indices = [d["index"] for d in weekly]
    changes = [d["change"] for d in weekly]
    xs = list(range(len(weekly)))

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#F8F9FA")
    ax.set_facecolor("#F8F9FA")

    # Colored line segments: each segment's color = direction of that day's change
    for i in range(1, len(weekly)):
        color = COLOR_UP if changes[i] >= 0 else COLOR_DOWN
        ax.plot(
            [xs[i - 1], xs[i]], [indices[i - 1], indices[i]],
            color=color, linewidth=2.5, solid_capstyle="round",
        )

    # Dots + value annotations
    for i, (idx, chg) in enumerate(zip(indices, changes)):
        color = COLOR_UP if chg >= 0 else COLOR_DOWN
        ax.scatter(xs[i], idx, color=color, s=72, zorder=5,
                   edgecolors="white", linewidths=1.2)
        y_offset = 12 if chg >= 0 else -18
        ax.annotate(
            f"{idx:,.0f}",
            (xs[i], idx),
            textcoords="offset points",
            xytext=(0, y_offset),
            ha="center",
            fontsize=8.5,
            color=color,
            fontweight="bold",
        )

    # Axes
    ax.set_xticks(xs)
    ax.set_xticklabels([d[-5:] for d in dates], fontsize=10)  # "MM/DD"
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("加權指數", fontsize=11)
    ax.set_title("本週大盤走勢", fontsize=14, fontweight="bold", pad=14)

    # Date-range subtitle
    if len(dates) >= 2:
        ax.text(
            0.5, 1.01,
            f"{dates[0]}  ～  {dates[-1]}",
            transform=ax.transAxes,
            ha="center", fontsize=9, color="#888888",
        )

    ax.grid(axis="y", linestyle="--", alpha=0.4, color="#CCCCCC")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(-0.5, len(weekly) - 0.5)

    # Y-axis padding so annotations never clip
    ymin, ymax = min(indices), max(indices)
    margin = max((ymax - ymin) * 0.25, 50)
    ax.set_ylim(ymin - margin, ymax + margin)

    up_patch = mpatches.Patch(color=COLOR_UP, label="上漲")
    down_patch = mpatches.Patch(color=COLOR_DOWN, label="下跌")
    ax.legend(handles=[up_patch, down_patch], loc="upper left",
              fontsize=9, framealpha=0.7)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Chart saved → {output_path}")


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()
    print("Telegram message sent.")


def send_telegram_photo(caption: str, photo_path: str) -> None:
    """Send a photo with the text summary as caption (≤ 1024 chars)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"},
            files={"photo": photo},
            timeout=30,
        )
    resp.raise_for_status()
    print("Telegram photo sent.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    print("Fetching market data...")
    market = get_market_data()
    if market is None:
        print("No market data (market may be closed today).")
        return

    print(f"TAIEX: {market['index']:,.2f}  change: {market['change']:+.2f}")
    print("Fetching stock data...")
    all_stocks = get_all_stocks()

    message = build_message(market, all_stocks)

    if is_weekly_summary():
        print("Friday — generating weekly chart...")
        weekly = get_weekly_taiex(5)
        draw_weekly_chart(weekly)
        send_telegram_photo(message, CHART_PATH)
    else:
        send_telegram(message)


if __name__ == "__main__":
    main()
