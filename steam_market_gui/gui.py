import os, io, threading, time, sys, csv
from typing import Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from dotenv import load_dotenv

import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
from PIL import Image, ImageTk, ImageFilter, ImageOps
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

ACCENT_COLOR = "#7cf9d2"
SECONDARY_ACCENT = "#7a8cff"
CARD_BACKGROUND = "#0b1226"

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
        self.configure(style="TrackerFrame.TFrame")
        self.accent_color = ACCENT_COLOR
        self.secondary_accent = SECONDARY_ACCENT
        self.card_background = CARD_BACKGROUND

        self.configure_padding()
        self.build_ui(title)
        self.fetch_all_async()

    def configure_padding(self):
        for i in range(3):
            self.columnconfigure(i, weight=1)
        self.rowconfigure(1, weight=1)

    def build_ui(self, title: str):
        self.card_border = tk.Frame(
            self,
            bg="#05070f",
            highlightbackground=self.accent_color,
            highlightcolor=self.accent_color,
            highlightthickness=2,
            bd=0,
        )
        self.card_border.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=4, pady=(0, 16))
        self.card_border.columnconfigure(0, weight=1)
        self.card_border.rowconfigure(0, weight=1)

        self.card = ttk.Frame(self.card_border, padding=(18, 16, 18, 16), style="NeonCard.TFrame")
        self.card.grid(row=0, column=0, sticky="nsew")
        for i in range(3):
            self.card.columnconfigure(i, weight=1)

        self.title_lbl = ttk.Label(self.card, text=title, style="NeonPrimary.TLabel")
        self.title_lbl.grid(row=0, column=0, columnspan=2, sticky="w")

        self.url_lbl = ttk.Label(
            self.card,
            text=unquote(self.market_hash),
            style="NeonSecondary.TLabel",
            wraplength=420,
        )
        self.url_lbl.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.image_container = tk.Frame(
            self.card,
            bg=self.card_background,
            highlightbackground=self.secondary_accent,
            highlightcolor=self.secondary_accent,
            highlightthickness=2,
            bd=0,
        )
        self.image_container.grid(row=0, column=2, rowspan=4, sticky="ne", padx=(16, 0))

        self.image_lbl = ttk.Label(self.image_container, style="NeonImage.TLabel", anchor="center")
        self.image_lbl.pack(fill="both", expand=True, padx=6, pady=6)

        # Prices
        self.median_var = tk.StringVar(value="Median: —")
        self.lowest_var = tk.StringVar(value="Lowest: —")
        self.volume_var = tk.StringVar(value="Volume: —")
        self.updated_var = tk.StringVar(value="Updated: —")

        self._load_cached_snapshot()

        self.median_lbl = ttk.Label(self.card, textvariable=self.median_var, style="NeonValue.TLabel")
        self.lowest_lbl = ttk.Label(self.card, textvariable=self.lowest_var, style="NeonValueSecondary.TLabel")
        self.volume_lbl = ttk.Label(self.card, textvariable=self.volume_var, style="NeonInfo.TLabel")
        self.updated_lbl = ttk.Label(self.card, textvariable=self.updated_var, style="NeonInfo.TLabel")

        self.median_lbl.grid(row=2, column=0, sticky="w", pady=(14, 0))
        self.lowest_lbl.grid(row=2, column=1, sticky="w", pady=(14, 0))
        self.volume_lbl.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.updated_lbl.grid(row=3, column=1, sticky="w", pady=(4, 0))

        # Chart area
        self.chart_points = []
        self.timeframe_var = tk.StringVar(value="day")

        self.chart_container = tk.Frame(
            self,
            bg="#05070f",
            highlightbackground="#1f2a4f",
            highlightcolor="#1f2a4f",
            highlightthickness=1,
            bd=0,
        )
        self.chart_container.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=4, pady=(0, 14))
        self.chart_container.columnconfigure(0, weight=1)
        self.chart_container.rowconfigure(0, weight=1)

        self.chart_lbl = ttk.Label(self.chart_container, style="Chart.TLabel", anchor="center")
        self.chart_lbl.grid(row=0, column=0, sticky="nsew", padx=14, pady=12)

        self.timeframe_frame = ttk.Frame(self, padding=(0, 6, 0, 0), style="TrackerFrame.TFrame")
        self.timeframe_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=4)
        self.timeframe_frame.columnconfigure((0,1,2), weight=1)

        self.timeframe_buttons = {}
        for idx, (label, key) in enumerate([("Day", "day"), ("Week", "week"), ("Lifetime", "lifetime")]):
            bootstyle = "success" if key == self.timeframe_var.get() else "dark-outline"
            btn = tb.Button(
                self.timeframe_frame,
                text=label,
                command=lambda k=key: self._set_timeframe(k),
                bootstyle=bootstyle,
                width=14,
            )
            btn.grid(row=0, column=idx, padx=6)
            btn.configure(cursor="hand2")
            self.timeframe_buttons[key] = btn

        # Controls
        self.controls = ttk.Frame(self, padding=(0, 12, 0, 0), style="TrackerFrame.TFrame")
        self.controls.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4)
        self.controls.columnconfigure(3, weight=1)

        tb.Button(self.controls, text="Refresh Now", command=self.fetch_all_async, bootstyle="info-outline").grid(row=0, column=0, padx=(0,6))
        tb.Button(self.controls, text="Open Listing", command=self.open_listing, bootstyle="secondary-outline").grid(row=0, column=1, padx=(0,6))
        tb.Button(self.controls, text="Reload Image", command=self.fetch_image_async, bootstyle="warning-outline").grid(row=0, column=2, padx=(0,6))
        self.interval_lbl = ttk.Label(self.controls, text=f"Auto-refresh: {REFRESH_SECONDS}s", style="NeonInfo.TLabel")
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
        preferred_path = os.path.join(ASSETS_DIR, f"{self.slug}.png")
        legacy_path = os.path.join(ASSETS_DIR, f"{self.slug}.jpg")
        img_path = preferred_path if os.path.exists(preferred_path) else legacy_path

        if os.path.exists(img_path):
            try:
                im = Image.open(img_path).convert("RGBA")
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
                img_bytes = io.BytesIO(r.content)
                try:
                    pil_image = Image.open(img_bytes)
                except Exception as exc:
                    print("Image decode failed:", exc, file=sys.stderr)
                    return

                pil_image = pil_image.convert("RGBA")
                target_path = preferred_path
                try:
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                    pil_image.save(target_path, format="PNG")
                    if os.path.exists(legacy_path) and legacy_path != target_path:
                        try:
                            os.remove(legacy_path)
                        except OSError:
                            pass
                except Exception:
                    target_path = legacy_path
                    with open(target_path, "wb") as f:
                        f.write(r.content)

                self._set_label_image(pil_image)
                self._image_cached = True
        except Exception as e:
            print("Image fetch failed:", e, file=sys.stderr)

    def _set_label_image(self, pil_img):
        styled = self._stylize_item_image(pil_img)
        self.tk_img = ImageTk.PhotoImage(styled)
        self.image_lbl.configure(image=self.tk_img, text="")

    def _stylize_item_image(self, pil_img: Image.Image) -> Image.Image:
        base = ImageOps.contain(pil_img.convert("RGBA"), (220, 220))
        alpha = base.split()[-1]
        rgb = base.convert("RGB")
        rgb = ImageOps.autocontrast(rgb, cutoff=2)
        rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.6, percent=180))
        base = Image.merge("RGBA", (*rgb.split(), alpha))

        mask = alpha
        pad = 36

        primary_rgb = self._dominant_color(base)
        glow_layer = Image.new("RGBA", (base.width + pad * 2, base.height + pad * 2), (0, 0, 0, 0))
        color_layer = Image.new("RGBA", base.size, (*primary_rgb, 255))
        glow_layer.paste(color_layer, (pad, pad), mask)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=32))

        secondary_rgb = self._hex_to_rgb(self.secondary_accent)
        accent_layer = Image.new("RGBA", base.size, (*secondary_rgb, 220))
        accent_glow = Image.new("RGBA", glow_layer.size, (0, 0, 0, 0))
        accent_glow.paste(accent_layer, (pad, pad), mask)
        accent_glow = accent_glow.filter(ImageFilter.GaussianBlur(radius=18))

        composite = Image.new("RGBA", glow_layer.size, (5, 8, 20, 0))
        composite.alpha_composite(glow_layer)
        composite.alpha_composite(accent_glow)
        composite.alpha_composite(base, (pad, pad))

        accent_border_color = tuple(list(secondary_rgb) + [120])
        composite = ImageOps.expand(composite, border=2, fill=accent_border_color)
        composite = ImageOps.expand(composite, border=4, fill=(5, 8, 20, 255))

        return composite

    def _dominant_color(self, image: Image.Image) -> tuple[int, int, int]:
        thumb = image.copy()
        if thumb.mode not in ("RGB", "RGBA"):
            thumb = thumb.convert("RGBA")
        thumb = thumb.resize((1, 1), Image.LANCZOS)
        pixel = thumb.getpixel((0, 0))
        r, g, b = pixel[:3]
        accent_rgb = self._hex_to_rgb(self.accent_color)
        blended = []
        for idx, component in enumerate((r, g, b)):
            mixed = int(component * 0.55 + accent_rgb[idx] * 0.45 + 25)
            blended.append(min(255, mixed))
        brightness = max(blended)
        if brightness < 120:
            boost = 120 - brightness
            blended = [min(255, c + boost) for c in blended]
        return tuple(blended)

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    def _set_timeframe(self, timeframe: str):
        if timeframe == self.timeframe_var.get():
            # still refresh in case data changed
            self._render_chart(timeframe)
            return

        self.timeframe_var.set(timeframe)
        self._update_timeframe_buttons()
        self._render_chart(timeframe)

    def _update_timeframe_buttons(self):
        for key, btn in self.timeframe_buttons.items():
            bootstyle = "success" if key == self.timeframe_var.get() else "dark-outline"
            btn.configure(bootstyle=bootstyle)

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
            self.chart_points = []
            self.chart_lbl.configure(image="", text="No price history yet", anchor="center")
            return

        # Convert epochs to timezone-aware datetimes and sort chronologically
        timestamps = [datetime.fromtimestamp(t, tz=timezone.utc).astimezone() for t in ts]
        self.chart_points = sorted(zip(timestamps, med), key=lambda x: x[0])
        self._render_chart(self.timeframe_var.get())

    def _render_chart(self, timeframe: Optional[str] = None):
        if timeframe is None:
            timeframe = self.timeframe_var.get()

        if not self.chart_points:
            self.chart_lbl.configure(image="", text="No price history yet", anchor="center")
            return

        plt.close("all")
        plt.style.use("dark_background")
        fig, ax = plt.subplots(figsize=(6.8, 3.5), dpi=135)
        fig.patch.set_facecolor("#05070f")
        ax.set_facecolor("#09122a")

        line_color = "#7cf9d2"
        fill_color = "#0f3c46"

        times, prices = zip(*self.chart_points)
        now = datetime.now(timezone.utc).astimezone(times[0].tzinfo)

        span = {
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "lifetime": None,
        }.get(timeframe, None)

        if span is None:
            filtered = list(self.chart_points)
            range_start = times[0]
        else:
            threshold = now - span
            filtered = [(t, p) for t, p in self.chart_points if t >= threshold]
            range_start = threshold

        if not filtered:
            filtered = [self.chart_points[-1]]

        filtered_times, filtered_prices = zip(*filtered)

        if filtered_prices:
            for glow_width, alpha in ((9, 0.08), (6, 0.12), (4, 0.18)):
                ax.plot(
                    filtered_times,
                    filtered_prices,
                    color=line_color,
                    linewidth=glow_width,
                    alpha=alpha,
                    solid_capstyle="round",
                )

        ax.plot(
            filtered_times,
            filtered_prices,
            color=line_color,
            linewidth=2.6,
            marker="o",
            markersize=4,
            markerfacecolor="#05070f",
            markeredgecolor="#7cf9d2",
        )
        if len(filtered_prices) > 1:
            ax.fill_between(filtered_times, filtered_prices, color=fill_color, alpha=0.22)

        ax.set_title(
            f"Median Price — {timeframe.capitalize()} View",
            color="#9aa6ff",
            fontsize=11,
            pad=16,
            fontweight="bold",
        )

        locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(colors="#94a3ff", labelsize=8)
        ax.xaxis.set_tick_params(rotation=0, labelcolor="#b0b9ff")

        dollar_formatter = ticker.FuncFormatter(lambda val, _: f"${val:,.2f}")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
        ax.yaxis.set_major_formatter(dollar_formatter)
        ax.yaxis.label.set_color("#9aa6ff")
        ax.set_ylabel("Median Price", fontsize=9)

        for spine in ax.spines.values():
            spine.set_color("#1c2750")

        ax.grid(which="major", color="#1c2750", linestyle="-", linewidth=0.8, alpha=0.8)

        range_end = now
        if len(filtered_times) == 1:
            padding = {
                "day": timedelta(hours=12),
                "week": timedelta(days=1.5),
            }.get(timeframe, timedelta(days=30))
            range_start = min(range_start, filtered_times[0] - padding)
            range_end = max(range_end, filtered_times[0] + padding)

        ax.set_xlim(range_start, range_end)
        ax.margins(x=0.03)
        ax.margins(y=0.1)

        ax.set_xlabel("Date", color="#e5e7eb", fontsize=9)

        buf = io.BytesIO()
        fig.canvas.print_png(buf)
        buf.seek(0)
        from PIL import Image as _Image
        im = _Image.open(buf)
        self.tk_chart = ImageTk.PhotoImage(im)
        self.chart_lbl.configure(image=self.tk_chart, text="")
        plt.close(fig)


class App(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly")  # light & clean; try "cyborg" for dark
        self.title("Steam Market — CS2 Trackers")
        self.geometry("1200x720")

        self.style.theme_use("cyborg")
        style = self.style

        neon_bg = "#05070f"
        card_bg = CARD_BACKGROUND

        self.configure(background=neon_bg)
        self.option_add("*Font", ("Segoe UI", 10))

        style.configure("TrackerFrame.TFrame", background=neon_bg)
        style.configure("NeonCard.TFrame", background=card_bg, borderwidth=0)
        style.configure("NeonPrimary.TLabel", background=card_bg, foreground="#f4f7ff", font=("Orbitron", 16, "bold"))
        style.configure("NeonSecondary.TLabel", background=card_bg, foreground="#8aa9ff", font=("Segoe UI", 9))
        style.configure("NeonValue.TLabel", background=card_bg, foreground=ACCENT_COLOR, font=("Share Tech Mono", 13, "bold"))
        style.configure("NeonValueSecondary.TLabel", background=card_bg, foreground="#7fd3ff", font=("Share Tech Mono", 12))
        style.configure("NeonInfo.TLabel", background=card_bg, foreground="#7c8ba7", font=("Segoe UI", 9))
        style.configure("NeonImage.TLabel", background=card_bg)
        style.configure("Chart.TLabel", background=neon_bg, foreground="#8aa9ff", font=("Share Tech Mono", 11))
        style.configure("Footer.TFrame", background=neon_bg)
        style.configure("Footer.TLabel", background=neon_bg, foreground="#7c8ba7", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10))

        client = SteamMarketClient(appid=APPID, currency=CURRENCY)

        container = ttk.Frame(self, padding=20, style="TrackerFrame.TFrame")
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)

        self.tracker1 = TrackerFrame(container, "Tracker 1", os.getenv("ITEM_URL_1", DEFAULT_URL_1), client)
        self.tracker1.grid(row=0, column=0, sticky="nsew", padx=(0, 18))

        self.tracker2 = TrackerFrame(container, "Tracker 2", os.getenv("ITEM_URL_2", DEFAULT_URL_2), client)
        self.tracker2.grid(row=0, column=1, sticky="nsew", padx=(18, 0))

        # Footer
        footer = ttk.Frame(self, padding=(18, 10), style="Footer.TFrame")
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, text=f"Auto refresh every {REFRESH_SECONDS}s | Currency={CURRENCY}", style="Footer.TLabel").pack(side="left")
        tb.Button(footer, text="Quit", command=self.destroy, bootstyle="danger-outline").pack(side="right")

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
