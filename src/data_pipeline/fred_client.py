"""
FRED Data Client for International Macro Indicators.
Pulls US Fed Funds Rate (FEDFUNDS), USD/INR (DEXINUS), and Brent Crude (DCOILBRENTEU)
directly from the St. Louis Fed FRED data service without requiring external API keys.
Incorporates defensive caching, timeout resilience, and robust interpolation.
"""

import io
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
import pandas as pd

from src.infra.exceptions import DataPipelineError

logger = logging.getLogger("rbi_mpc.fred")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

FRED_SERIES = {
    "us_fed_funds": "FEDFUNDS",
    "usd_inr": "DEXINUS",
    "brent_crude": "DCOILBRENTEU",
}


class FREDClient:
    """Defensive FRED CSV downloader and aligner."""

    def __init__(self, cache_dir: Optional[Path] = None, timeout_sec: int = 15):
        self.cache_dir = cache_dir or (PROJECT_ROOT / "data" / "raw" / "fred")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_sec = timeout_sec

    def fetch_series(self, series_id: str, force_refresh: bool = False) -> pd.DataFrame:
        """
        Fetches a series from FRED or local cache.
        Returns a DataFrame indexed by date with the series value as float.
        """
        cache_file = self.cache_dir / f"{series_id}.csv"
        if cache_file.exists() and not force_refresh:
            try:
                df = pd.read_csv(cache_file)
                df["date"] = pd.to_datetime(df["observation_date"])
                df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
                df = df.dropna().sort_values("date").reset_index(drop=True)
                return df
            except Exception as e:
                logger.warning("Cache read failed for %s (%s). Re-fetching from FRED.", series_id, e)

        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = resp.read()
            # Atomically save cache
            temp_cache = self.cache_dir / f".{series_id}.csv.tmp"
            with open(temp_cache, "wb") as f:
                f.write(data)
            temp_cache.replace(cache_file)

            df = pd.read_csv(io.BytesIO(data))
            df["date"] = pd.to_datetime(df["observation_date"])
            df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
            df = df.dropna().sort_values("date").reset_index(drop=True)
            return df
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            if cache_file.exists():
                logger.warning("Network fetch failed for %s (%s). Falling back to existing cache.", series_id, e)
                df = pd.read_csv(cache_file)
                df["date"] = pd.to_datetime(df["observation_date"])
                df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
                return df.dropna().sort_values("date").reset_index(drop=True)
            raise DataPipelineError(f"Failed to fetch FRED series {series_id}: {e}")

    def get_indicators_for_date(self, meeting_date_str: str) -> dict[str, float]:
        """
        Retrieves the latest available indicator values as of the given meeting date
        using forward-fill / as-of alignment.
        """
        target_date = pd.to_datetime(meeting_date_str)
        results = {}

        for var_name, series_id in FRED_SERIES.items():
            df = self.fetch_series(series_id)
            # Find the latest available observation on or prior to target_date
            prior_obs = df[df["date"] <= target_date]
            if not prior_obs.empty:
                val = float(prior_obs.iloc[-1][series_id])
                results[var_name] = val
            else:
                # Fallback to earliest observation
                val = float(df.iloc[0][series_id])
                results[var_name] = val
                logger.warning("No prior observation for %s as of %s; using earliest %s", series_id, meeting_date_str, val)

        return results


if __name__ == "__main__":
    client = FREDClient()
    indicators = client.get_indicators_for_date("2023-08-10")
    print("[FRED Client Test] Indicators for 2023-08-10:", indicators)
