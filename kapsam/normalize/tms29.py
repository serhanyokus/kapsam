"""TMS 29 (IAS 29) Normalizasyon Motoru.

Arka plan
---------
TMS 29 uygulayan bir şirketin her raporu, karşılaştırmalı dönemler dahil TÜM tutarları
raporlama tarihinin satın alma gücüyle (o tarihin TL'si) sunar. Bu yüzden:

1. Farklı raporlardan alınan rakamlar doğrudan karşılaştırılamaz (her biri farklı TL).
2. Gelir tablosu kümülatif yayımlandığı için çeyreklik rakam, basit çıkarma ile
   (9A - 6A) bulunamaz: 6 aylık rakam önce 9 aylık raporun TL'sine taşınmalıdır.
3. Net parasal pozisyon kazancı/kaybı kârı operasyondan bağımsız olarak şişirebilir
   veya düşürebilir; temel (core) kârlılık için ayrıştırılmalıdır.
4. Yüksek enflasyonlu ekonomi para birimindeki tablolar, TMS 21 par. 42 uyarınca
   tüm kalemler için kapanış kuruyla çevrilir; USD analizinde rapor tarihi kuru kullanılır.

Bu modül, yukarıdaki dört işlemi şeffaf ve denetlenebilir biçimde yapar.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ..data.statements import Statement

FLOW_ITEMS = {
    "revenue", "cogs", "gross_profit", "operating_profit", "net_monetary_gain",
    "pretax_profit", "net_income", "net_income_parent", "depreciation",
}


def restate(value: float, from_period: pd.Period, to_period: pd.Period, cpi: pd.Series) -> float:
    """from_period satın alma gücündeki tutarı to_period satın alma gücüne taşır."""
    return value * cpi[to_period] / cpi[from_period]


def quarterly_from_reports(reports: Iterable[Statement], cpi: pd.Series) -> pd.DataFrame:
    """Kümülatif raporlardan, her çeyreği KENDİ rapor tarihinin TL'siyle ifade eden çeyreklik tablo üretir.

    Q_n = YTD_n  -  restate(YTD_{n-1}, R_{n-1} → R_n)   (aynı mali yıl içinde)
    Stok kalemler (bilanço) olduğu gibi alınır.
    Dönen tablo: index=kalem, columns=çeyrek, ayrıca 'expressed_in' meta bilgisi
    df.attrs['expressed_in'] = {çeyrek: rapor tarihi}.
    """
    reps = sorted(reports, key=lambda r: r.report_date)
    by_date = {r.report_date: r for r in reps}
    out, expressed = {}, {}
    for r in reps:
        p = r.report_date
        col = r.values[p] if p in r.values.columns else None
        if col is None:
            continue
        q = col.copy()
        prev_p = p - 1
        if r.cumulative and p.quarter > 1:
            prev = by_date.get(prev_p)
            if prev is None or prev_p not in prev.values.columns:
                # Önceki rapor yoksa bu çeyreğin gelir tablosu kalemleri hesaplanamaz.
                for k in FLOW_ITEMS & set(q.index):
                    q[k] = np.nan
            else:
                prev_col = prev.values[prev_p]
                factor = cpi[p] / cpi[prev_p]
                for k in FLOW_ITEMS & set(q.index):
                    q[k] = col[k] - prev_col.get(k, np.nan) * factor
        out[p] = q
        expressed[p] = p
    df = pd.DataFrame(out)
    df.attrs["expressed_in"] = expressed
    return df


def to_base(quarterly: pd.DataFrame, cpi: pd.Series, base: pd.Period | None = None) -> pd.DataFrame:
    """Tüm çeyrekleri tek bir baz tarihin (varsayılan: en son çeyrek) TL'sine taşır → reel seri."""
    base = base or max(quarterly.columns)
    expressed = quarterly.attrs.get("expressed_in", {c: c for c in quarterly.columns})
    res = quarterly.copy()
    for c in quarterly.columns:
        res[c] = quarterly[c] * cpi[base] / cpi[expressed[c]]
    res.attrs["base"] = base
    return res


def to_usd(quarterly: pd.DataFrame, usdtry: pd.Series) -> pd.DataFrame:
    """Her çeyreği ifade edildiği rapor tarihinin kapanış kuruyla USD'ye çevirir (TMS 21 par. 42)."""
    expressed = quarterly.attrs.get("expressed_in", {c: c for c in quarterly.columns})
    res = quarterly.copy()
    for c in quarterly.columns:
        res[c] = quarterly[c] / usdtry[expressed[c]]
    return res


def core_earnings(df: pd.DataFrame, tax_rate: float = 0.0) -> pd.Series:
    """Net kârdan net parasal pozisyon etkisini arındırır.

    tax_rate: parasal kazancın vergi etkisi için varsayım (0 → brüt arındırma).
    """
    nmg = df.loc["net_monetary_gain"] if "net_monetary_gain" in df.index else 0.0
    return df.loc["net_income"] - nmg * (1 - tax_rate)


def metrics(df: pd.DataFrame, tax_rate: float = 0.0) -> pd.DataFrame:
    """Normalize edilmiş tablodan temel analist KPI'larını hesaplar."""
    g = lambda k: df.loc[k] if k in df.index else pd.Series(np.nan, index=df.columns)  # noqa: E731
    debt = g("short_term_debt").fillna(0) + g("current_portion_lt_debt").fillna(0) + g("long_term_debt").fillna(0)
    core = core_earnings(df, tax_rate)
    m = pd.DataFrame({
        "revenue": g("revenue"),
        "gross_margin": g("gross_profit") / g("revenue"),
        "operating_margin": g("operating_profit") / g("revenue"),
        "net_margin": g("net_income") / g("revenue"),
        "core_net_income": core,
        "core_net_margin": core / g("revenue"),
        "monetary_gain_share": g("net_monetary_gain") / g("net_income"),
        "net_debt": debt - g("cash"),
        "net_debt_to_equity": (debt - g("cash")) / g("total_equity"),
        "core_roe_annualized": core * 4 / g("total_equity"),
    }).T
    rev = g("revenue")
    m.loc["revenue_real_yoy"] = rev / rev.shift(4) - 1
    m.loc["revenue_real_qoq"] = rev / rev.shift(1) - 1
    return m


def naive_vs_correct(reports: Iterable[Statement], cpi: pd.Series, item: str = "revenue") -> pd.DataFrame:
    """Analistlerin sık yaptığı hatayı gösterir: farklı raporlardan rakamları düzeltmeden çıkarmak.

    Dönen tablo: naive (düzeltmesiz 9A-6A), correct (TMS 29 tutarlı), error_pct.
    """
    reps = sorted(reports, key=lambda r: r.report_date)
    by_date = {r.report_date: r for r in reps}
    rows = {}
    q = quarterly_from_reports(reps, cpi)
    for r in reps:
        p = r.report_date
        if p.quarter == 1 or (p - 1) not in by_date:
            continue
        naive = r.values.at[item, p] - by_date[p - 1].values.at[item, p - 1]
        correct = q.at[item, p]
        rows[p] = {"naive": naive, "correct": correct, "error_pct": naive / correct - 1}
    return pd.DataFrame(rows).T
