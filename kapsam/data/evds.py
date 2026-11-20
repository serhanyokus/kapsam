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

    def _meta(self, path: str) -> list[dict]:
        """EVDS üst veri uçları (veri grupları / seri listesi). Hata olursa boş liste."""
        for base in [BASE_URL] + [u for u in FALLBACK_URLS if u != BASE_URL]:
            try:
                r = self.session.get(base + path, headers={"key": self.api_key, "accept": "application/json"}, timeout=30)
                r.raise_for_status()
                js = r.json()
                return js if isinstance(js, list) else js.get("items", [])
            except Exception:  # noqa: BLE001
                continue
        return []

    def find_cpi_2025(self) -> str | None:
        """TÜİK 2026'da TÜFE'yi 2025=100 bazına taşıdı; eski TP.FG.J0 Ocak 2026'da durdu.
        Yeni genel endeksin kodunu EVDS üst verisinden bulur (veri grubu adında 'Tüketici Fiyat' ve '2025')."""
        groups = self._meta("datagroups/mode=0&type=json")
        cands = [g for g in groups
                 if "2025" in str(g.get("DATAGROUP_NAME", "")) and "tüketici fiyat" in str(g.get("DATAGROUP_NAME", "")).lower()]
        for g in cands:
            series = self._meta(f"serieList/type=json&code={g.get('DATAGROUP_CODE')}")
            for s_ in series:
                name = str(s_.get("SERIE_NAME", "")).lower()
                if ("genel" in name or "tüfe" in name) and "(2025=100)" in name.replace(" ", "") or "genel" in name:
                    return s_.get("SERIE_CODE")
            if series:
                return series[0].get("SERIE_CODE")
        return None

    def quarterly_macro(self, start: str, end: str) -> pd.DataFrame:
        """Çeyrek sonu TÜFE ve USD/TRY kurunu döner (index: pd.Period 'Q')."""
        cpi = self.series(SERIES["cpi"], start, end)   # TÜFE zaten aylık
        fx = self.series(SERIES["usdtry"], start, end)
        return to_quarter_end(cpi, fx)


def merge_cpi(existing: pd.Series | None, official_old: pd.Series, new_base: pd.Series | None = None) -> tuple[pd.Series, str]:
    """Aylık TÜFE serisini KISALTMADAN birleştirir.

    * official_old (TP.FG.J0, 2003=100): örtüşen aylarda resmi değer esas alınır.
    * existing: kayıtlı seri; resmi verinin bittiği aydan sonraki aylar korunur (ör. elle zincirlenmiş 2026 ayları).
    * new_base (2025=100): resmi eski serinin son ayından sonrası, yeni serinin aylık değişimleriyle zincirlenir.
    Dönen: (seri, açıklama)
    """
    out = existing.copy() if existing is not None else pd.Series(dtype=float)
    official_old = official_old.dropna()
    out = official_old.combine_first(out) if len(out) else official_old.copy()
    out.loc[official_old.index] = official_old
    note = f"resmi 2003=100 son: {official_old.index[-1]:%Y-%m}" if len(official_old) else "resmi seri yok"
    if new_base is not None and len(new_base.dropna()) > 1:
        nb = new_base.dropna().sort_index()
        anchor = official_old.index[-1] if len(official_old) else out.index[-1]
        level = out[anchor]
        prev = nb[nb.index <= anchor]
        prev_val = prev.iloc[-1] if len(prev) else None
        for d, v in nb[nb.index > anchor].items():
            if prev_val is not None:
                level = level * v / prev_val
                out.loc[d] = level
            prev_val = v
        note += f"; 2025=100 serisiyle zincirlendi, son: {nb.index[-1]:%Y-%m}"
    elif len(out) and len(official_old) and out.index[-1] > official_old.index[-1]:
        note += f"; sonrası kayıtlı seriden korundu (son: {out.index[-1]:%Y-%m})"
    return out.sort_index(), note


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
