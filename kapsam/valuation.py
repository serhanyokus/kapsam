"""Enflasyonla tutarlı değerleme: reel İNA (DCF), ters İNA ve çarpanlar.

Yüksek enflasyonda en sık yapılan değerleme hatası, nominal TL nakit akışlarını reel
iskonto oranıyla (veya tersini) iskonto etmektir. KAPSAM tüm hesabı REEL yapar:

* Nakit akışları: TMS 29 motorunun ürettiği baz-tarih TL'si (reel) serilerden başlar.
* İskonto oranı: Fisher denklemiyle reel AOSM, (1 + nominal) / (1 + beklenen enflasyon) - 1.
* Yeniden yatırım: Damodaran'ın "satış / yatırılan sermaye" yaklaşımı
  (yeniden yatırım = hasılat artışı / satış-sermaye oranı). Böylece büyüme bedava değildir.

Ters İNA, bugünkü piyasa değerinin hangi reel büyümeyi fiyatladığını bulur. Buy-side
analistin asıl sorusu budur: "Piyasa ne bekliyor ve ben neden farklı düşünüyorum?"
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


def real_rate(nominal: float, inflation: float) -> float:
    """Fisher denklemi: nominal orandan reel oran."""
    return (1 + nominal) / (1 + inflation) - 1


def ttm(series: pd.Series) -> float:
    """Son dört çeyreğin toplamı (akış kalemleri için yıllıklandırma)."""
    s = series.dropna()
    if len(s) < 4:
        raise ValueError("TTM için en az 4 çeyrek gerekir")
    return float(s.iloc[-4:].sum())


@dataclass
class DCFInputs:
    revenue0: float            # son 12 ay reel hasılat (baz tarih TL'si)
    growth_high: float         # yüksek büyüme dönemi yıllık reel büyüme
    growth_terminal: float     # sürekli reel büyüme (uzun vadede ~0-2%)
    high_years: int = 5        # yüksek büyüme yılı; sonra lineer geçiş
    fade_years: int = 5
    ebit_margin: float = 0.12  # hedef faaliyet marjı (temel, parasal kazanç hariç)
    margin0: float | None = None  # başlangıç marjı; verilirse hedefe lineer yaklaşır
    tax_rate: float = 0.25
    sales_to_capital: float = 2.0
    real_wacc: float = 0.10
    net_debt: float = 0.0
    shares: float = 1.0
    minority_and_other: float = 0.0


def dcf(inp: DCFInputs) -> dict:
    """Reel FCFF projeksiyonu ve hisse başına değer."""
    n = inp.high_years + inp.fade_years
    if inp.real_wacc <= inp.growth_terminal:
        raise ValueError("Reel AOSM, sürekli büyümeden büyük olmalı")
    growth = [inp.growth_high] * inp.high_years + list(
        np.linspace(inp.growth_high, inp.growth_terminal, inp.fade_years + 1)[1:]
    )
    m0 = inp.ebit_margin if inp.margin0 is None else inp.margin0
    margins = list(np.linspace(m0, inp.ebit_margin, n + 1)[1:])
    rows, rev = [], inp.revenue0
    for t in range(n):
        new_rev = rev * (1 + growth[t])
        ebit = new_rev * margins[t]
        nopat = ebit * (1 - inp.tax_rate)
        reinvest = (new_rev - rev) / inp.sales_to_capital
        fcff = nopat - reinvest
        df = 1 / (1 + inp.real_wacc) ** (t + 1)
        rows.append({"yil": t + 1, "buyume": growth[t], "hasilat": new_rev, "marj": margins[t], "ebit": ebit,
                     "nopat": nopat, "yeniden_yatirim": reinvest, "fcff": fcff, "iskonto": df, "bd_fcff": fcff * df})
        rev = new_rev
    proj = pd.DataFrame(rows).set_index("yil")
    # Sürekli dönem: yeniden yatırım oranı = g / ROIC_terminal; ROIC_terminal = AOSM varsayımı (rekabetçi denge)
    last_nopat = proj["nopat"].iloc[-1] * (1 + inp.growth_terminal)
    reinvest_rate = inp.growth_terminal / inp.real_wacc if inp.growth_terminal > 0 else 0.0
    tv = last_nopat * (1 - reinvest_rate) / (inp.real_wacc - inp.growth_terminal)
    pv_tv = tv * proj["iskonto"].iloc[-1]
    ev = proj["bd_fcff"].sum() + pv_tv
    equity = ev - inp.net_debt - inp.minority_and_other
    return {"projection": proj, "terminal_value": tv, "pv_terminal": pv_tv, "ev": ev, "equity": equity,
            "per_share": equity / inp.shares, "tv_share": pv_tv / ev}


def implied_growth(target_ev: float, inp: DCFInputs, lo: float = -0.10, hi: float = 0.40, tol: float = 1e-6) -> float:
    """Ters İNA: hedef firma değerini veren yüksek-büyüme dönemi reel büyüme oranı (ikiye bölme)."""
    f = lambda g: dcf(replace(inp, growth_high=g))["ev"] - target_ev  # noqa: E731
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < tol * max(1.0, abs(target_ev)):
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def implied(field: str, target_ev: float, inp: DCFInputs, lo: float, hi: float, tol: float = 1e-6) -> float:
    """Genel ters İNA: hedef firma değerini veren girdi değeri (ör. 'ebit_margin', 'growth_high'); yoksa NaN."""
    f = lambda x: dcf(replace(inp, **{field: x}))["ev"] - target_ev  # noqa: E731
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < tol * max(1.0, abs(target_ev)):
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def implied_margin(target_ev: float, inp: DCFInputs) -> float:
    """Piyasanın fiyatladığı kalıcı (hedef) faaliyet marjı; başlangıç marjından buna doğru yaklaşılır."""
    return implied("ebit_margin", target_ev, inp, -0.5, 0.9)


def sensitivity(inp: DCFInputs, waccs: list[float], growths: list[float]) -> pd.DataFrame:
    """Hisse başına değer: satırlar reel AOSM, sütunlar yüksek-büyüme reel oranı."""
    data = {g: [dcf(replace(inp, real_wacc=w, growth_high=g))["per_share"] for w in waccs] for g in growths}
    out = pd.DataFrame(data, index=waccs)
    out.index.name, out.columns.name = "reel_AOSM", "reel_buyume"
    return out


def multiples(real: pd.DataFrame, market_cap: float, net_debt: float, tax_rate: float = 0.0, ttm_fn=None) -> dict:
    """Reel (baz tarih TL'si) TTM rakamlarla çarpanlar; parasal kazançtan arındırılmış F/K dahil.
    ttm_fn(kalem): son 12 ay hesaplayıcı (çeyrekler eksikse kümülatif raporlardan); verilmezse son 4 çeyrek."""
    from .normalize.tms29 import core_earnings
    ev = market_cap + net_debt
    if ttm_fn is None:
        rev, ebit = ttm(real.loc["revenue"]), ttm(real.loc["operating_profit"])
        ni = ttm(real.loc["net_income"])
        core = ttm(core_earnings(real, tax_rate))
    else:
        rev, ebit, ni = ttm_fn("revenue"), ttm_fn("operating_profit"), ttm_fn("net_income")
        try:
            nmg = ttm_fn("net_monetary_gain")
        except (ValueError, KeyError):
            nmg = 0.0
        core = ni - nmg * (1 - tax_rate)
    return {"FD/Satışlar": ev / rev, "FD/FVÖK": ev / ebit, "F/K (raporlanan)": market_cap / ni,
            "F/K (temel)": market_cap / core if core > 0 else float("nan")}
