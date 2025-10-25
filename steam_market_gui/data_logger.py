import csv, os, time
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class PriceLogger:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["timestamp_iso", "epoch_s", "median_price", "lowest_price", "volume"])

    def append(self, median: Optional[float], lowest: Optional[float], volume: Optional[str]):
        """Persist a single price snapshot to disk with an accurate timestamp."""
        ts = time.time()
        ts_local = datetime.now(timezone.utc).astimezone()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                ts_local.isoformat(timespec="seconds"),
                f"{ts:.0f}",
                "" if median is None else median,
                "" if lowest is None else lowest,
                volume or "",
            ])

    def latest(self) -> Optional[Dict[str, Any]]:
        """Return the most recent logged row as a dictionary or None if empty."""
        if not os.path.exists(self.path):
            return None

        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = deque(reader, maxlen=1)

        if not rows:
            return None

        row = rows[0]
        # Normalise numeric fields and timestamp for easier reuse
        def _to_float(value: str) -> Optional[float]:
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        def _parse_ts(value: str) -> Optional[datetime]:
            if not value:
                return None
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None

        return {
            "timestamp_iso": row.get("timestamp_iso", ""),
            "timestamp": _parse_ts(row.get("timestamp_iso", "")),
            "epoch_s": _to_float(row.get("epoch_s", "")),
            "median_price": _to_float(row.get("median_price", "")),
            "lowest_price": _to_float(row.get("lowest_price", "")),
            "volume": row.get("volume", ""),
        }
