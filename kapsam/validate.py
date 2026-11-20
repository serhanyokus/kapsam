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


def reported_quarter_checks(quarterly: pd.DataFrame, statements, tol: float = 0.005) -> list[Check]:
    """KAPSAM'ın kümülatiften hesapladığı çeyreklik akışları, KAP raporundaki '3 aylık' sütunlarla karşılaştırır.

    Aynı rapordaki 3 aylık rakam, cari rapor tarihinin TL'siyle ifade edildiği için doğrudan karşılaştırılabilir.
    Sapma, ya ayrıştırma hatasına ya da şirketin farklı bir yeniden ifade yöntemine işaret eder.
    """
    out: list[Check] = []
    for st in statements:
        qr = getattr(st, "quarterly_reported", None)
        p = st.report_date
        if qr is None or qr.empty or p not in qr.columns or p not in quarterly.columns:
            continue
        for code in ("revenue", "gross_profit", "operating_profit", "net_income"):
            if code in qr.index and code in quarterly.index and not np.isnan(qr.at[code, p]):
                ours, theirs = quarterly.at[code, p], qr.at[code, p]
                ok = abs(ours - theirs) <= tol * max(abs(theirs), 1)
                out.append(Check(f"3_aylık_{code}", str(p), bool(ok), f"KAPSAM={ours:,.0f} KAP={theirs:,.0f}"))
    return out
