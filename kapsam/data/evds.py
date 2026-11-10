"""TCMB EVDS istemcisi: TÜFE endeksi ve USD/TRY kuru.

Ücretsiz API anahtarı: https://evds2.tcmb.gov.tr → Profil → API Anahtarı.
Anahtarı EVDS_API_KEY ortam değişkenine koyun. EVDS, anahtarın HTTP başlığında
("key") gönderilmesini ister.
"""
from __future__ import annotations

import os

import pandas as pd
import requests

BASE_URL = "https://evds2.tcmb.gov.tr/service/evds/"
SERIES = {
    "cpi": "TP.FG.J0",            # TÜFE (2003=100), aylık
    "usdtry": "TP.DK.USD.A.YTL",  # USD döviz alış kuru, günlük
}


class EVDSClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.getenv("EVDS_API_KEY")
        if not self.api_key:
            raise RuntimeError("EVDS_API_KEY tanımlı değil. evds2.tcmb.gov.tr üzerinden ücretsiz anahtar alın.")
        self.session = session or requests.Session()

    def series(self, code: str, start: str, end: str, frequency: int | None = None) -> pd.Series:
        """start/end: 'GG-AA-YYYY'. frequency: 5=aylık (EVDS kodu)."""
        url = f"{BASE_URL}series={code}&startDate={start}&endDate={end}&type=json"
        if frequency:
            url += f"&frequency={frequency}"
        r = self.session.get(url, headers={"key": self.api_key}, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
        col = code.replace(".", "_")
        data = {it["Tarih"]: it.get(col) for it in items if it.get(col) not in (None, "")}
        s = pd.Series({_parse_date(k): float(v) for k, v in data.items()}).sort_index()
        s.name = code
        return s

    def quarterly_macro(self, start: str, end: str) -> pd.DataFrame:
        """Çeyrek sonu TÜFE ve USD/TRY kurunu döner (index: pd.Period 'Q')."""
        cpi = self.series(SERIES["cpi"], start, end, frequency=5)
        fx = self.series(SERIES["usdtry"], start, end)
        return to_quarter_end(cpi, fx)


def to_quarter_end(cpi: pd.Series, usdtry: pd.Series) -> pd.DataFrame:
    """Aylık TÜFE ve günlük kuru, çeyrek sonu değerlerine indirger."""
    cpi_q = cpi.groupby(cpi.index.to_period("Q")).last()
    fx_q = usdtry.groupby(usdtry.index.to_period("Q")).last()
    return pd.DataFrame({"cpi": cpi_q, "usdtry": fx_q}).dropna()


def _parse_date(s: str) -> pd.Timestamp:
    s = s.strip()
    if s.count("-") == 1:  # aylık: '2025-9'
        y, m = s.split("-")
        return pd.Timestamp(year=int(y), month=int(m), day=1) + pd.offsets.MonthEnd(0)
    return pd.to_datetime(s, dayfirst=True)
