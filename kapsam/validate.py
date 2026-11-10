"""Sayısal doğrulama katmanı: yapay zekâ ve ayrıştırıcı çıktılarını muhasebe kimlikleriyle denetler."""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .textutil import parse_tr_number


@dataclass
class Check:
    name: str
    period: str
    passed: bool
    detail: str


def accounting_checks(df: pd.DataFrame, tol: float = 0.005) -> list[Check]:
    """Bilanço denkliği ve brüt kâr kimliği gibi kontrolleri her dönem için çalıştırır."""
    out: list[Check] = []
    for p in df.columns:
        c = df[p]
        if {"total_assets", "total_liabilities_equity"} <= set(c.dropna().index):
            a, l = c["total_assets"], c["total_liabilities_equity"]
            ok = abs(a - l) <= tol * abs(a)
            out.append(Check("bilanço_denkliği", str(p), ok, f"Varlıklar={a:,.0f} Kaynaklar={l:,.0f}"))
        if {"revenue", "cogs", "gross_profit"} <= set(c.dropna().index):
            cogs = c["cogs"]
            expected = c["revenue"] + cogs if cogs < 0 else c["revenue"] - cogs
            ok = abs(expected - c["gross_profit"]) <= tol * max(abs(c["revenue"]), 1)
            out.append(Check("brüt_kâr_kimliği", str(p), ok, f"Beklenen={expected:,.0f} Raporlanan={c['gross_profit']:,.0f}"))
    return out


_NUM_RE = re.compile(r"\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?|\(?-?\d+(?:,\d+)?\)?")


def numbers_in(text: str) -> list[float]:
    vals = []
    for m in _NUM_RE.findall(text):
        try:
            vals.append(parse_tr_number(m))
        except ValueError:
            pass
    return vals


def grounded(claim_numbers: list[float], source_text: str, rel_tol: float = 0.001) -> dict:
    """Bir özette geçen her sayının kaynak belgede (KAP metni) bulunup bulunmadığını kontrol eder.

    Kaynakta bulunmayan sayı 'doğrulanmadı' olarak işaretlenir → halüsinasyon önlemi.
    """
    src = np.array(numbers_in(source_text) or [np.nan])
    result = {}
    for n in claim_numbers:
        hit = np.any(np.isclose(src, n, rtol=rel_tol, atol=0.5))
        result[n] = bool(hit)
    return {"all_grounded": all(result.values()) if result else True, "detail": result}
