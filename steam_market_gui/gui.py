import os, io, threading, time, sys, csv
from typing import Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from dotenv import load_dotenv

import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
from PIL import Image, ImageTk
import matplotlib
matplotlib.use("Agg")  # render offscreen, then show as image in Tk
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import ticker

from .steam_api import SteamMarketClient
from .data_logger import PriceLogger
from .utils import market_hash_from_url, slugify, parse_price_to_float

load_dotenv()

APPID = 730
CURRENCY = int(os.getenv("CURRENCY", "1"))
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "300"))

DEFAULT_URL_1 = os.getenv("ITEM_URL_1", "https://steamcommunity.com/market/listings/730/%E2%98%85%20Bayonet%20%7C%20Marble%20Fade%20%28Factory%20New%29")
DEFAULT_URL_2 = os.getenv("ITEM_URL_2", "https://steamcommunity.com/market/listings/730/%E2%98%85%20Falchion%20Knife%20%7C%20Marble%20Fade%20%28Factory%20New%29")

ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))

class TrackerFrame(ttk.Frame):
    def __init__(self, master, title: str, listing_url: str, client: SteamMarketClient, **kwargs):
        super().__init__(master, **kwargs)
        self.client = client
        self.listing_url = listing_url.strip()
        self.market_hash = market_hash_from_url(self.listing_url)
        self.slug = slugify(self.market_hash)
        self.logger = PriceLogger(os.path.join(DATA_DIR, f"{self.slug}.csv"))

        self.configure_padding()
        self.build_ui(title)
        self.fetch_all_async()

    def configure_padding(self):
        for i in range(3):
            self.columnconfigure(i, weight=1)
        self.rowconfigure(3, weight=1)

    def build_ui(self, title: str):
        self.card = ttk.Frame(self, padding=12, style="Card.TFrame")
        self.card.grid(row=0, column=0, columnspan=3, sticky="nsew")
        for i in range(3):
            self.card.columnconfigure(i, weight=1)

        self.title_lbl = ttk.Label(self.card, text=title, font=("Helvetica", 14, "bold"))
        self.title_lbl.grid(row=0, column=0, columnspan=2, sticky="w")

        self.url_lbl = ttk.Label(self.card, text=unquote(self.market_hash), style="secondary.TLabel", wraplength=420)
        self.url_lbl.grid(row=1, column=0, columnspan=2, sticky="w")

        self.image_lbl = ttk.Label(self.card)
        self.image_lbl.grid(row=0, column=2, rowspan=3, sticky="e")

        # Prices
        self.median_var = tk.StringVar(value="Median: —")
        self.lowest_var = tk.StringVar(value="Lowest: —")
        self.volume_var = tk.StringVar(value="Volume: —")
        self.updated_var = tk.StringVar(value="Updated: —")

        self._load_cached_snapshot()

        self.median_lbl = ttk.Label(self.card, textvariable=self.median_var, font=("Helvetica", 12, "bold"))
        self.lowest_lbl = ttk.Label(self.card, textvariable=self.lowest_var)
        self.volume_lbl = ttk.Label(self.card, textvariable=self.volume_var, style="secondary.TLabel")
        self.updated_lbl = ttk.Label(self.card, textvariable=self.updated_var, style="secondary.TLabel")

        self.median_lbl.grid(row=2, column=0, sticky="w", pady=(6,0))
        self.lowest_lbl.grid(row=2, column=1, sticky="w", pady=(6,0))
        self.volume_lbl.grid(row=3, column=0, sticky="w", pady=(2,0))
        self.updated_lbl.grid(row=3, column=1, sticky="w", pady=(2,0))

        # Chart area
        self.chart_lbl = ttk.Label(self)
        self.chart_lbl.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(8,0))

        # Controls
        self.controls = ttk.Frame(self, padding=(0,8,0,0))
        self.controls.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.controls.columnconfigure(3, weight=1)

        ttk.Button(self.controls, text="Refresh Now", command=self.fetch_all_async).grid(row=0, column=0, padx=(0,6))
        ttk.Button(self.controls, text="Open Listing", command=self.open_listing).grid(row=0, column=1, padx=(0,6))
        ttk.Button(self.controls, text="Reload Image", command=self.fetch_image_async).grid(row=0, column=2, padx=(0,6))
        self.interval_lbl = ttk.Label(self.controls, text=f"Auto-refresh: {REFRESH_SECONDS}s")
        self.interval_lbl.grid(row=0, column=3, sticky="e")

        # Start auto refresh
        self.after(REFRESH_SECONDS * 1000, self.fetch_all_async)

    def open_listing(self):
        import webbrowser
        webbrowser.open(self.listing_url)

    def _load_cached_snapshot(self):
        last = self.logger.latest()
        if not last:
            return

        def fmt_price(value: Optional[float]) -> str:
            return "n/a" if value is None else f"{value:.2f}"

        self.median_var.set(f"Median: {fmt_price(last.get('median_price'))} (cached)")
        self.lowest_var.set(f"Lowest: {fmt_price(last.get('lowest_price'))} (cached)")
        vol = last.get("volume") or "n/a"
        self.volume_var.set(f"Volume: {vol} (cached)")

        ts = last.get("timestamp")
        if ts:
            try:
                ts_display = ts.isoformat(timespec="seconds")
            except TypeError:
                ts_display = ts.isoformat()
        else:
            ts_display = last.get("timestamp_iso", "")
        if ts_display:
            self.updated_var.set(f"Updated: {ts_display} (cached)")
        else:
            self.updated_var.set("Updated: —")

    def fetch_all_async(self):
        threading.Thread(target=self._fetch_all, daemon=True).start()

    def fetch_image_async(self):
        threading.Thread(target=self._fetch_image, daemon=True).start()

    def _fetch_all(self):
        try:
            self._fetch_price()
            self._plot_chart()
            self.updated_var.set(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print("Fetch error:", e, file=sys.stderr)
        finally:
            # schedule next refresh
            self.after(REFRESH_SECONDS * 1000, self.fetch_all_async)

    def _fetch_price(self):
        data = self.client.price_overview(self.market_hash)
        print("DEBUG priceoverview:", data)
        if not data:
            self.median_var.set("Median: — (failed)")
            return
        median_str = data.get("median_price")
        lowest_str = data.get("lowest_price")
        volume_str = data.get("volume")

        self.median_var.set(f"Median: {median_str if median_str else 'n/a'}")
        self.lowest_var.set(f"Lowest: {lowest_str if lowest_str else 'n/a'}")
        self.volume_var.set(f"Volume: {volume_str if volume_str else 'n/a'}")

        median = parse_price_to_float(median_str)
        lowest = parse_price_to_float(lowest_str)
        self.logger.append(median, lowest, volume_str)

        # ensure we have an image
        if not getattr(self, "_image_cached", None):
            self._fetch_image()

    def _fetch_image(self):
        img_path = os.path.join(ASSETS_DIR, f"{self.slug}.jpg")
        if os.path.exists(img_path):
            try:
                im = Image.open(img_path).resize((220,220))
                self._set_label_image(im)
                self._image_cached = True
                return
            except Exception:
                pass

        url = self.client.listing_image_url(self.listing_url)
        if not url:
            return
        try:
            r = self.client.session.get(url, timeout=15)
            if r.status_code == 200:
                with open(img_path, "wb") as f:
                    f.write(r.content)
                from PIL import Image
                im = Image.open(io.BytesIO(r.content)).resize((220,220))
                self._set_label_image(im)
                self._image_cached = True
        except Exception as e:
            print("Image fetch failed:", e, file=sys.stderr)

    def _set_label_image(self, pil_img):
        self.tk_img = ImageTk.PhotoImage(pil_img)
        self.image_lbl.configure(image=self.tk_img)

    def _plot_chart(self):
        csv_path = os.path.join(DATA_DIR, f"{self.slug}.csv")
        ts = []
        med = []
        if os.path.exists(csv_path):
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        epoch = float(row["epoch_s"])
                        m = float(row["median_price"]) if row["median_price"] else None
                        if m is not None:
                            ts.append(epoch)
                            med.append(m)
                    except:
                        continue

        if not med:
            # no data yet — clear chart
            self.chart_lbl.configure(image="")
            return

        # Convert epochs to timezone-aware datetimes and sort chronologically
        timestamps = [datetime.fromtimestamp(t, tz=timezone.utc).astimezone() for t in ts]
        paired = sorted(zip(timestamps, med), key=lambda x: x[0])

        now = datetime.now(timezone.utc).astimezone()
        ranges = [
            ("Daily", now - timedelta(days=1)),
            ("Weekly", now - timedelta(days=7)),
            ("Lifetime", None),
        ]

        plt.close("all")
        plt.style.use("seaborn-v0_8-darkgrid")
        fig, axes = plt.subplots(3, 1, figsize=(6.6, 6.6), dpi=135, sharey=True)
        fig.suptitle(unquote(self.market_hash), fontsize=12, fontweight="bold")
        fig.patch.set_facecolor("#0e1117")

        line_color = "#4c72b0"
        fill_color = "#4c72b0"

        for ax in axes:
            ax.set_facecolor("#111827")
            ax.tick_params(colors="#d1d5db", labelsize=8)
            ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
            ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
            ax.ticklabel_format(style="plain", axis="y")
            for spine in ax.spines.values():
                spine.set_color("#1f2937")

        for ax, (label, start) in zip(axes, ranges):
            if start is None:
                filtered = list(paired)
            else:
                filtered = [(t, m) for t, m in paired if t >= start]

            if not filtered:
                ax.text(0.5, 0.5, "Not enough data yet", ha="center", va="center", color="#9ca3af", fontsize=9,
                        transform=ax.transAxes)
                ax.set_title(f"{label} View", color="#f9fafb", fontsize=10)
                continue

            times, prices = zip(*filtered)
            ax.plot(times, prices, color=line_color, linewidth=2.2, marker="o", markersize=3.5, markerfacecolor="#f9fafb")
            if len(prices) > 1:
                ax.fill_between(times, prices, color=fill_color, alpha=0.12)

            ax.set_title(f"{label} View", color="#f9fafb", fontsize=10)
            locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
            formatter = mdates.ConciseDateFormatter(locator)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(formatter)
            ax.xaxis.set_tick_params(rotation=0, labelcolor="#e5e7eb")
            ax.grid(which="major", color="#1f2937", linestyle="-", linewidth=0.8, alpha=0.6)
            if len(times) == 1:
                padding = {
                    "Daily": timedelta(hours=12),
                    "Weekly": timedelta(days=1.5),
                }.get(label, timedelta(days=30))
                ax.set_xlim(times[0] - padding, times[0] + padding)
            else:
                ax.set_xlim(times[0], times[-1])
                ax.margins(x=0.03)
            ax.margins(y=0.1)

        axes[-1].set_xlabel("Date", color="#e5e7eb", fontsize=9)
        axes[1].set_ylabel("Median Price", color="#e5e7eb", fontsize=9)
        fig.tight_layout(rect=[0, 0.01, 1, 0.95], h_pad=1.2)

        buf = io.BytesIO()
        fig.canvas.print_png(buf)
        buf.seek(0)
        from PIL import Image as _Image
        im = _Image.open(buf)
        self.tk_chart = ImageTk.PhotoImage(im)
        self.chart_lbl.configure(image=self.tk_chart)
        plt.close(fig)


class App(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly")  # light & clean; try "cyborg" for dark
        self.title("Steam Market — CS2 Trackers")
        self.geometry("1200x720")

        self.style.theme_use("cyborg")

        client = SteamMarketClient(appid=APPID, currency=CURRENCY)

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        self.tracker1 = TrackerFrame(container, "Tracker 1", os.getenv("ITEM_URL_1", DEFAULT_URL_1), client)
        self.tracker1.grid(row=0, column=0, sticky="nsew", padx=(0,7))

        self.tracker2 = TrackerFrame(container, "Tracker 2", os.getenv("ITEM_URL_2", DEFAULT_URL_2), client)
        self.tracker2.grid(row=0, column=1, sticky="nsew", padx=(7,0))

        # Footer
        footer = ttk.Frame(self, padding=(14,6))
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text=f"Auto refresh every {REFRESH_SECONDS}s | Currency={CURRENCY}").pack(side="left")
        ttk.Button(footer, text="Quit", command=self.destroy).pack(side="right")

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
