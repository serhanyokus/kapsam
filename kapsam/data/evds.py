"""TCMB EVDS istemcisi: TÜFE endeksi ve USD/TRY kuru.

Ücretsiz API anahtarı: https://evds3.tcmb.gov.tr → Profil → API Anahtarı.
Anahtarı EVDS_API_KEY ortam değişkenine koyun. EVDS, anahtarın HTTP başlığında
("key") gönderilmesini ister. 2025'te servis evds3 adresine taşındı; eski evds2 yolu
veri yerine HTML döndürür. Adres EVDS_BASE_URL ile değiştirilebilir.
"""
from __future__ import annotations

import os

import pandas as pd
import requests

BASE_URL = os.getenv("EVDS_BASE_URL", "https://evds3.tcmb.gov.tr/igmevdsms-dis/")
FALLBACK_URLS = ["https://evds2.tcmb.gov.tr/service/evds/"]
SERIES = {
    "cpi": "TP.FG.J0",            # TÜFE (2003=100), aylık
    "usdtry": "TP.DK.USD.A.YTL",  # USD döviz alış kuru, günlük
}


class EVDSClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.getenv("EVDS_API_KEY")
        if not self.api_key:
            raise RuntimeError("EVDS_API_KEY tanımlı değil. evds3.tcmb.gov.tr üzerinden ücretsiz anahtar alın.")
        self.session = session or requests.Session()

    def series(self, code: str, start: str, end: str, frequency: int | None = None) -> pd.Series:
        """start/end: 'GG-AA-YYYY'. frequency: 5=aylık (EVDS kodu)."""
        query = f"series={code}&startDate={start}&endDate={end}&type=json" + (f"&frequency={frequency}" if frequency else "")
        errors = []
        for base in [BASE_URL] + [u for u in FALLBACK_URLS if u != BASE_URL]:
            try:
                r = self.session.get(base + query, headers={"key": self.api_key, "accept": "application/json"}, timeout=30)
                r.raise_for_status()
                payload = r.json()
                break
            except ValueError:
                errors.append(f"{base}: JSON yerine {r.headers.get('content-type', '?')} döndü "
                              f"({r.text[:80].strip()!r}); anahtar geçersiz olabilir veya adres değişmiş olabilir")
            except requests.RequestException as e:
                errors.append(f"{base}: {e}")
        else:
            raise RuntimeError("EVDS verisi alınamadı: " + " | ".join(errors))
        items = payload.get("items", [])
        col = code.replace(".", "_")
        data = {it["Tarih"]: it.get(col) for it in items if it.get(col) not in (None, "")}
        s = pd.Series({_parse_date(k): float(v) for k, v in data.items()}).sort_index()
        s.name = code
        return s

    def quarterly_macro(self, start: str, end: str) -> pd.DataFrame:
        """Çeyrek sonu TÜFE ve USD/TRY kurunu döner (index: pd.Period 'Q')."""
        cpi = self.series(SERIES["cpi"], start, end)   # TÜFE zaten aylık
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
