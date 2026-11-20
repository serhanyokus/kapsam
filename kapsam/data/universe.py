"""BIST hisse evreni: tüm işlem gören şirketlerin kodu, adı, sektörü, kapanış fiyatı ve piyasa değeri.

Kaynak: İş Yatırım "Temel Değerler ve Oranlar" sayfası (tablo HTML'de hazır gelir; tek istekle tüm hisseler).
Evren her çalıştırmada yenilenir; kaynağa ulaşılamazsa son kaydedilen `config/bist_evren.csv` kullanılır.

Sektöre göre tablo türü:
* `banka`   → bankacılık tablo biçimi; TMS 29 uygulanmaz (BDDK), nominal modda analiz
* `sigorta` → sigorta tablo biçimi; TMS 29 uygulanmaz, nominal modda analiz
* `sanayi`  → diğer tüm şirketler (GYO, holding, aracı kurum dahil); TMS 29 satırı varsa düzeltme uygulanır
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Callable

import pandas as pd

from ..textutil import norm, parse_tr_number

URL = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Temel-Degerler-Ve-Oranlar.aspx"
USER_AGENT = "KAPSAM-arastirma/0.9 (+https://github.com/serhanyokus/kapsam)"
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{2,5}$")


def sector_type(sector: str) -> str:
    s = norm(sector or "")
    if "banka" in s:
        return "banka"
    if "sigorta" in s or "emeklilik" in s:
        return "sigorta"
    return "sanayi"


def _num(x) -> float:
    try:
        return parse_tr_number(x)
    except (ValueError, TypeError):
        return float("nan")


def parse(html: str) -> pd.DataFrame:
    """Sayfadaki hisse tablosunu bulur: kod, ad, sektör, kapanış, piyasa değeri (TL), sermaye (mn TL)."""
    tables = pd.read_html(io.StringIO(html), flavor="lxml", thousands=None, decimal=",")
    best = None
    for t in tables:
        cols = [norm(str(c)) for c in t.columns]
        if any(c.startswith("kod") for c in cols) and any("sektor" in c for c in cols):
            if best is None or len(t) > len(best):
                best = t
    if best is None:
        raise ValueError("hisse tablosu bulunamadı")
    cmap = {}
    for c in best.columns:
        n = norm(str(c))
        raw = str(c).lower().replace("ı", "i")
        if n.startswith("kod"):
            cmap[c] = "kod"
        elif "hisse adi" in n or n == "ad":
            cmap[c] = "ad"
        elif "sektor" in n:
            cmap[c] = "sektor"
        elif n.startswith("kapanis"):
            cmap[c] = "kapanis"
        elif "piyasa degeri" in n and "tl" in raw and "$" not in raw and "usd" not in raw:
            cmap[c] = "piyasa_degeri_mn_tl"
        elif n.startswith("sermaye"):
            cmap[c] = "sermaye_mn_tl"
    df = best.rename(columns=cmap)[[v for v in ["kod", "ad", "sektor", "kapanis", "piyasa_degeri_mn_tl", "sermaye_mn_tl"]
                                    if v in cmap.values()]].copy()
    df["kod"] = df["kod"].astype(str).str.strip().str.upper()
    df = df[df["kod"].str.match(_TICKER)].drop_duplicates("kod")
    for c in ("kapanis", "piyasa_degeri_mn_tl", "sermaye_mn_tl"):
        if c in df:
            df[c] = df[c].map(_num)
    df["tur"] = df.get("sektor", pd.Series("", index=df.index)).fillna("").map(sector_type)
    return df.sort_values("kod").reset_index(drop=True)


def fetch(getter: Callable[[str], str] | None = None) -> pd.DataFrame:
    if getter is None:
        import requests

        def getter(u):
            r = requests.get(u, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.text
    return parse(getter(URL))


def load(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "tur" not in df:
        df["tur"] = df["sektor"].fillna("").map(sector_type)
    return df


def market_caps(df: pd.DataFrame) -> dict[str, float]:
    """Kod → piyasa değeri (TL)."""
    if "piyasa_degeri_mn_tl" not in df:
        return {}
    s = df.set_index("kod")["piyasa_degeri_mn_tl"].dropna() * 1e6
    return s.to_dict()
