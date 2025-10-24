import requests
import os
from bs4 import BeautifulSoup

class SteamMarketClient:
    def __init__(self, appid: int = 730, currency: int = 1, timeout: float = 15.0):
        self.appid = appid
        self.currency = currency
        self.country = os.getenv("COUNTRY", "US")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://steamcommunity.com/market/"
        })

    def price_overview(self, market_hash_name: str):
        'Calls the undocumented priceoverview endpoint and returns JSON.'
        url = "https://steamcommunity.com/market/priceoverview/"
        params = {
            "appid": str(self.appid),
            "currency": str(self.currency),
            "country": self.country,
            "market_hash_name": market_hash_name
        }
        r = self.session.get(url, params=params, timeout=self.timeout)
        if r.status_code == 200:
            try:
                data = r.json()
                if data.get("success"):
                    return data
            except Exception:
                print("JSON parse failed:", r.text[:200])
        else:
            print("HTTP", r.status_code, r.text[:200])
        return None

    def listing_image_url(self, listing_url: str):
        'Scrape the listing page for og:image; returns CDN URL or None.'
        try:
            r = self.session.get(listing_url, timeout=self.timeout)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "html.parser")
            og = soup.find("meta", attrs={"property": "og:image"})
            if og and og.get("content"):
                return og["content"]
        except Exception:
            return None
        return None
