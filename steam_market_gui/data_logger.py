import csv, os, time
from datetime import datetime
from typing import Optional

class PriceLogger:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["timestamp_iso", "epoch_s", "median_price", "lowest_price", "volume"])

    def append(self, median: Optional[float], lowest: Optional[float], volume: Optional[str]):
        ts = time.time()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([datetime.utcfromtimestamp(ts).isoformat(), f"{ts:.0f}", 
                        "" if median is None else median, 
                        "" if lowest is None else lowest, 
                        volume or ""])
