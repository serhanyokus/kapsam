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
    "pretax_profit", "net_income", "net_income_parent", "depreciation", "capex", "operating_cash_flow",
    "interest_income", "interest_expense", "net_interest_income", "net_fee_income", "operating_income", "credit_provisions",
    "gross_premiums", "net_premiums", "technical_result_nonlife", "technical_result",
}


def applies_tms29(reports) -> bool:
    """Raporlardan herhangi birinde net parasal pozisyon satırı varsa şirket TMS 29 uyguluyordur."""
    return any("net_monetary_gain" in r.values.index for r in reports)


def statement_kind(reports) -> str:
    idx = set().union(*[set(r.values.index) for r in reports]) if reports else set()
    if "net_interest_income" in idx or "interest_income" in idx:
        return "banka"
    if "gross_premiums" in idx or "net_premiums" in idx or "technical_result" in idx:
        return "sigorta"
    return "sanayi"


def restate(value: float, from_period: pd.Period, to_period: pd.Period, cpi: pd.Series) -> float:
    """from_period satın alma gücündeki tutarı to_period satın alma gücüne taşır."""
    return value * cpi[to_period] / cpi[from_period]


def quarterly_from_reports(reports: Iterable[Statement], cpi: pd.Series, restate: bool | None = None) -> pd.DataFrame:
    """Kümülatif raporlardan, her çeyreği KENDİ rapor tarihinin TL'siyle ifade eden çeyreklik tablo üretir.

    Q_n = YTD_n  -  restate(YTD_{n-1}, R_{n-1} → R_n)   (aynı mali yıl içinde)
    Stok kalemler (bilanço) olduğu gibi alınır.
    Dönen tablo: index=kalem, columns=çeyrek, ayrıca 'expressed_in' meta bilgisi
    df.attrs['expressed_in'] = {çeyrek: rapor tarihi}.
    """
    reps = sorted(reports, key=lambda r: r.report_date)
    if restate is None:
        restate = applies_tms29(reps)
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
                factor = cpi[p] / cpi[prev_p] if restate else 1.0
                for k in FLOW_ITEMS & set(q.index):
                    q[k] = col[k] - prev_col.get(k, np.nan) * factor
        out[p] = q
        expressed[p] = p
    df = pd.DataFrame(out)
    df.attrs["expressed_in"] = expressed
    df.attrs["restated"] = restate
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
    if "revenue" not in df.index:            # banka: faaliyet geliri = net faiz + net ücret/komisyon; sigorta: brüt prim
        if "net_interest_income" in df.index:
            df = df.copy()
            df.loc["revenue"] = g("net_interest_income").fillna(0) + g("net_fee_income").fillna(0)
        elif "gross_premiums" in df.index:
            df = df.copy()
            df.loc["revenue"] = g("gross_premiums")
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
    if "net_interest_income" in df.index:
        m.loc["fee_share"] = g("net_fee_income") / rev
        m.loc["provision_to_nii"] = -g("credit_provisions") / g("net_interest_income")
        m.loc["roe_annualized"] = g("net_income") * 4 / g("total_equity")
        m.loc["loan_to_deposit"] = g("loans") / g("deposits")
    if "gross_premiums" in df.index:
        m.loc["retention"] = g("net_premiums") / g("gross_premiums")
        m.loc["roe_annualized"] = g("net_income") * 4 / g("total_equity")
    m.loc["revenue_real_qoq"] = rev / rev.shift(1) - 1
    return m.replace([np.inf, -np.inf], np.nan)          # sıfır paydalı oranlar (ör. önceki yıl hasılat 0) tanımsız


POSITIVE_ITEMS = {"revenue", "gross_premiums", "net_premiums", "interest_income", "net_interest_income"}


def naive_vs_correct(reports: Iterable[Statement], cpi: pd.Series, item: str = "revenue") -> pd.DataFrame:
    """Analistlerin sık yaptığı hatayı gösterir: farklı raporlardan rakamları düzeltmeden çıkarmak.

    Dönen tablo: naive (düzeltmesiz 9A-6A), correct (TMS 29 tutarlı), error_pct.
    """
    reps = sorted(reports, key=lambda r: r.report_date)
    by_date = {r.report_date: r for r in reps}
    rows = {}
    q = quarterly_from_reports(reps, cpi)
    if item not in q.index:
        return pd.DataFrame(columns=["naive", "correct", "error_pct"])
    for r in reps:
        p = r.report_date
        if p.quarter == 1 or (p - 1) not in by_date:
            continue
        cur = r.values[p].get(item, np.nan) if p in r.values.columns else np.nan
        prv = by_date[p - 1].values
        prev = prv[p - 1].get(item, np.nan) if (p - 1) in prv.columns else np.nan
        naive, correct = cur - prev, q.at[item, p] if p in q.columns else np.nan
        if pd.isna(naive) or pd.isna(correct) or correct == 0:    # kalem yok ya da sıfır (ör. satışı olmayan holding)
            continue
        if item in POSITIVE_ITEMS and (correct <= 0 or naive <= 0):   # çeyrekte satış yok → oran anlamsız
            continue
        if abs(correct) < 0.02 * abs(cur):                        # çeyrek, yılbaşından beri toplamın %2'sinden küçük: payda ~0
            continue
        rows[p] = {"naive": naive, "correct": correct, "error_pct": naive / correct - 1}
    return pd.DataFrame(rows).T if rows else pd.DataFrame(columns=["naive", "correct", "error_pct"])


def ttm_ytd(reports: Iterable[Statement], item: str, cpi: pd.Series, base: pd.Period | None = None,
            restate: bool | None = None) -> float:
    """Kümülatif (yılbaşından beri) rakamlardan son 12 ay: YB_son + Yıl_önceki − YB_önceki_aynı_dönem.
    Çeyrek ayrıştırması yapılamayan şirketler (6 ayda bir rapor, eksik çeyrek) için. Her terim TMS 29 uygulanıyorsa
    kendi rapor tarihinden `base` tarihinin TL'sine taşınır. Kalem yoksa ValueError."""
    reps = {r.report_date: r for r in reports}
    if restate is None:
        restate = applies_tms29(list(reps.values()))
    have = [p for p, r in reps.items() if p in r.values.columns and pd.notna(r.values[p].get(item, np.nan))]
    if not have:
        raise ValueError(f"TTM: hiçbir raporda {item} yok")
    last = max(have)
    base = base or last
    f = (lambda p: cpi[base] / cpi[p]) if restate else (lambda p: 1.0)

    def v(p):
        r = reps.get(p)
        x = r.values[p].get(item, np.nan) if r is not None and p in r.values.columns else np.nan
        if pd.isna(x):
            raise ValueError(f"TTM: {p} raporunda {item} yok")
        return float(x) * f(p)
    if last.quarter == 4:
        return v(last)
    fy, prev = pd.Period(year=last.year - 1, quarter=4, freq="Q"), pd.Period(year=last.year - 1, quarter=last.quarter, freq="Q")
    return v(last) + v(fy) - v(prev)
