import os, io, threading, time, sys, csv
from typing import Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from dotenv import load_dotenv

import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
from PIL import Image, ImageTk, ImageFilter, ImageOps, ImageChops
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

ACCENT_COLOR = "#58b4ff"
SECONDARY_ACCENT = "#5e7cff"
CARD_BACKGROUND = "#0b162f"
BASE_BACKGROUND = "#050b18"

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
            bg=BASE_BACKGROUND,
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
            bg=BASE_BACKGROUND,
            highlightbackground="#1b2b4d",
            highlightcolor="#1b2b4d",
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
            style_name = "Timeframe.Selected.TButton" if key == self.timeframe_var.get() else "Timeframe.Unselected.TButton"
            btn = tb.Button(
                self.timeframe_frame,
                text=label,
                command=lambda k=key: self._set_timeframe(k),
                style=style_name,
            )
            btn.grid(row=0, column=idx, padx=6)
            btn.configure(cursor="hand2")
            self.timeframe_buttons[key] = btn

        # Controls
        self.controls = ttk.Frame(self, padding=(0, 12, 0, 0), style="TrackerFrame.TFrame")
        self.controls.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4)
        self.controls.columnconfigure(3, weight=1)

        tb.Button(
            self.controls,
            text="Refresh Now",
            command=self.fetch_all_async,
            style="Command.Primary.TButton",
        ).grid(row=0, column=0, padx=(0, 6))
        tb.Button(
            self.controls,
            text="Open Listing",
            command=self.open_listing,
            style="Command.Secondary.TButton",
        ).grid(row=0, column=1, padx=(0, 6))
        tb.Button(
            self.controls,
            text="Reload Image",
            command=self.fetch_image_async,
            style="Command.Warning.TButton",
        ).grid(row=0, column=2, padx=(0, 6))
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

        pad = 48
        canvas_size = (base.width + pad * 2, base.height + pad * 2)

        mask_canvas = Image.new("L", canvas_size, 0)
        mask_canvas.paste(alpha, (pad, pad))

        glow_mask = mask_canvas.filter(ImageFilter.GaussianBlur(radius=36))
        glow_mask = ImageOps.autocontrast(glow_mask, cutoff=12)

        highlight_mask = mask_canvas.filter(ImageFilter.GaussianBlur(radius=12))
        highlight_mask = ImageOps.autocontrast(highlight_mask, cutoff=20)

        shadow_mask = ImageChops.offset(mask_canvas, 0, 16)
        shadow_mask = ImageOps.autocontrast(shadow_mask, cutoff=6)
        shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(radius=24))

        background = self._create_background_gradient(canvas_size)
        composite = background.convert("RGBA")

        accent_rgb = self._hex_to_rgb(self.secondary_accent)
        primary_rgb = self._dominant_color(base)

        glow_layer = Image.new("RGBA", canvas_size, (*primary_rgb, 0))
        glow_layer.putalpha(glow_mask)

        highlight_color = self._mix_colors(primary_rgb, accent_rgb, 0.35)
        highlight_layer = Image.new("RGBA", canvas_size, (*highlight_color, 0))
        highlight_layer.putalpha(highlight_mask)

        shadow_layer = Image.new("RGBA", canvas_size, (10, 14, 28, 0))
        shadow_layer.putalpha(shadow_mask)

        composite.alpha_composite(shadow_layer)
        composite.alpha_composite(glow_layer)
        composite.alpha_composite(highlight_layer)
        composite.alpha_composite(base, (pad, pad))

        border_accent = tuple(list(accent_rgb) + [120])
        composite = ImageOps.expand(composite, border=2, fill=border_accent)
        composite = ImageOps.expand(
            composite,
            border=4,
            fill=(*self._hex_to_rgb(BASE_BACKGROUND), 255),
        )

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

    def _create_background_gradient(self, size: tuple[int, int]) -> Image.Image:
        width, height = size
        gradient = Image.linear_gradient("L").rotate(90, expand=True)
        gradient = gradient.resize((width, height), Image.BICUBIC)

        base_rgb = self._hex_to_rgb(BASE_BACKGROUND)
        accent_rgb = self._hex_to_rgb(self.secondary_accent)
        deep_tone = self._mix_colors(base_rgb, accent_rgb, 0.15)
        light_tone = self._mix_colors(base_rgb, (240, 240, 255), 0.18)

        colored = ImageOps.colorize(
            gradient,
            black=self._rgb_to_hex(deep_tone),
            white=self._rgb_to_hex(light_tone),
        )
        vignette = Image.linear_gradient("L")
        vignette = vignette.resize((width, height), Image.BICUBIC)
        vignette = ImageOps.invert(vignette)
        vignette = vignette.filter(ImageFilter.GaussianBlur(radius=24))

        vignette_layer = Image.new("RGBA", (width, height), (*base_rgb, 0))
        vignette_layer.putalpha(vignette)

        background = colored.convert("RGBA")
        background.alpha_composite(vignette_layer)
        return background

    def _mix_colors(
        self, rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int], ratio: float
    ) -> tuple[int, int, int]:
        ratio = max(0.0, min(1.0, ratio))
        mixed = []
        for a, b in zip(rgb_a, rgb_b):
            mixed.append(int(a * (1 - ratio) + b * ratio))
        return tuple(mixed)

    def _rgb_to_hex(self, rgb: tuple[int, int, int]) -> str:
        return "#" + "".join(f"{component:02x}" for component in rgb)

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
            style_name = "Timeframe.Selected.TButton" if key == self.timeframe_var.get() else "Timeframe.Unselected.TButton"
            btn.configure(style=style_name)

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
        fig.patch.set_facecolor(BASE_BACKGROUND)
        ax.set_facecolor("#0b1a34")

        line_color = ACCENT_COLOR
        fill_color = "#0f2f5c"

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
            markerfacecolor=BASE_BACKGROUND,
            markeredgecolor=ACCENT_COLOR,
        )
        if len(filtered_prices) > 1:
            ax.fill_between(filtered_times, filtered_prices, color=fill_color, alpha=0.22)

        ax.set_title(
            f"Median Price — {timeframe.capitalize()} View",
            color="#94b7ff",
            fontsize=11,
            pad=16,
            fontweight="bold",
        )

        locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(colors="#7f9bff", labelsize=8)
        ax.xaxis.set_tick_params(rotation=0, labelcolor="#a9c2ff")

        dollar_formatter = ticker.FuncFormatter(lambda val, _: f"${val:,.2f}")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6))
        ax.yaxis.set_major_formatter(dollar_formatter)
        ax.yaxis.label.set_color("#94b7ff")
        ax.set_ylabel("Median Price", fontsize=9)

        for spine in ax.spines.values():
            spine.set_color("#1b2b4d")

        ax.grid(which="major", color="#1b2b4d", linestyle="-", linewidth=0.8, alpha=0.8)

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

        ax.set_xlabel("Date", color="#d4defc", fontsize=9)

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

        neon_bg = BASE_BACKGROUND
        card_bg = CARD_BACKGROUND

        self.configure(background=neon_bg)
        self.option_add("*Font", ("Segoe UI", 10))

        style.configure("TrackerFrame.TFrame", background=neon_bg)
        style.configure("NeonCard.TFrame", background=card_bg, borderwidth=0)
        style.configure("NeonPrimary.TLabel", background=card_bg, foreground="#f3f7ff", font=("Orbitron", 16, "bold"))
        style.configure("NeonSecondary.TLabel", background=card_bg, foreground="#9ab5ff", font=("Segoe UI", 9))
        style.configure("NeonValue.TLabel", background=card_bg, foreground=ACCENT_COLOR, font=("Share Tech Mono", 13, "bold"))
        style.configure("NeonValueSecondary.TLabel", background=card_bg, foreground="#8ec7ff", font=("Share Tech Mono", 12))
        style.configure("NeonInfo.TLabel", background=card_bg, foreground="#738ab4", font=("Segoe UI", 9))
        style.configure("NeonImage.TLabel", background=card_bg)
        style.configure("Chart.TLabel", background=neon_bg, foreground="#9ab5ff", font=("Share Tech Mono", 11))
        style.configure("Footer.TFrame", background=neon_bg)
        style.configure("Footer.TLabel", background=neon_bg, foreground="#6f82a8", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10))

        # Modern button styling
        style.configure(
            "Command.Primary.TButton",
            background=ACCENT_COLOR,
            foreground="#061428",
            borderwidth=0,
            focusthickness=1,
            focuscolor=ACCENT_COLOR,
            padding=(20, 10),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Command.Primary.TButton",
            background=[("active", "#6bc5ff"), ("pressed", "#3a94ff"), ("disabled", "#244063")],
            foreground=[("disabled", "#1b2d4a")],
        )

        style.configure(
            "Command.Secondary.TButton",
            background="#101c36",
            foreground="#a9c7ff",
            borderwidth=1,
            focusthickness=1,
            focuscolor="#2d4c7c",
            padding=(20, 10),
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "Command.Secondary.TButton",
            background=[("active", "#15274a"), ("pressed", "#0f1d35")],
            foreground=[("active", "#d5e4ff"), ("pressed", "#d5e4ff"), ("disabled", "#4d5f80")],
        )

        style.configure(
            "Command.Warning.TButton",
            background="#ffb347",
            foreground="#231200",
            borderwidth=0,
            focusthickness=1,
            focuscolor="#ffb347",
            padding=(20, 10),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Command.Warning.TButton",
            background=[("active", "#ffc46d"), ("pressed", "#f79a2d"), ("disabled", "#5c4730")],
            foreground=[("disabled", "#47361f")],
        )

        style.configure(
            "Command.Danger.TButton",
            background="#ff6f91",
            foreground="#24030a",
            borderwidth=0,
            focusthickness=1,
            focuscolor="#ff6f91",
            padding=(18, 9),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Command.Danger.TButton",
            background=[("active", "#ff85a4"), ("pressed", "#f05578"), ("disabled", "#5d3440")],
            foreground=[("disabled", "#3b1d25")],
        )

        style.configure(
            "Timeframe.Selected.TButton",
            background=ACCENT_COLOR,
            foreground="#061428",
            borderwidth=0,
            focusthickness=0,
            padding=(18, 9),
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Timeframe.Selected.TButton",
            background=[("active", "#6bc5ff"), ("pressed", "#3a94ff")],
            foreground=[("active", "#041021"), ("pressed", "#041021")],
        )

        style.configure(
            "Timeframe.Unselected.TButton",
            background="#101c36",
            foreground="#8ba4d9",
            borderwidth=0,
            focusthickness=0,
            padding=(18, 9),
            relief="flat",
            font=("Segoe UI", 10),
        )
        style.map(
            "Timeframe.Unselected.TButton",
            background=[("active", "#15284a"), ("pressed", "#0f1d34")],
            foreground=[("active", "#c5d8ff"), ("pressed", "#c5d8ff")],
        )

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
        tb.Button(footer, text="Quit", command=self.destroy, style="Command.Danger.TButton").pack(side="right")

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
