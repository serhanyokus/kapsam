"""Piyasa verisi: BIST hisse fiyatları, endeks (XU100) ve piyasa değeri.

Varsayılan kaynak Yahoo Finance (`yfinance` paketi; BIST sembolleri '.IS' ekiyle, ör. THYAO.IS).
İndirici dışarıdan verilebilir (test için sahte indirici veya başka bir veri sağlayıcı).
Ücretsiz kaynaklar gecikmeli ve zaman zaman eksik olabilir; profesyonel kullanımda lisanslı
veri sağlayıcıyla değiştirilmelidir.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

INDEX_SYMBOL = "XU100.IS"


def yahoo_symbol(ticker: str) -> str:
    return ticker if "." in ticker else f"{ticker}.IS"


def _yf_download(symbols: list[str], start: str) -> pd.DataFrame:
    import yfinance as yf  # isteğe bağlı bağımlılık
    df = yf.download(symbols, start=start, auto_adjust=True, progress=False, threads=False)
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": symbols[0]})
    return close


def _yf_shares(symbol: str) -> float | None:
    import yfinance as yf
    try:
        v = yf.Ticker(symbol).fast_info.get("shares")
        return float(v) if v else None
    except Exception:  # noqa: BLE001  (kaynak geçici olarak yanıt vermeyebilir)
        return None


class Market:
    def __init__(self, downloader: Callable[[list[str], str], pd.DataFrame] | None = None,
                 shares_lookup: Callable[[str], float | None] | None = None):
        self.downloader = downloader or _yf_download
        self.shares_lookup = shares_lookup or _yf_shares

    def prices(self, tickers: list[str], start: str = "2023-01-01", with_index: bool = True) -> pd.DataFrame:
        """Günlük düzeltilmiş kapanış fiyatları; sütunlar hisse kodu (endeks 'XU100')."""
        syms = [yahoo_symbol(t) for t in tickers] + ([INDEX_SYMBOL] if with_index else [])
        close = self.downloader(syms, start)
        rename = {yahoo_symbol(t): t for t in tickers} | {INDEX_SYMBOL: "XU100"}
        close = close.rename(columns=rename)
        close.index = pd.to_datetime(close.index).tz_localize(None) if getattr(close.index, "tz", None) else pd.to_datetime(close.index)
        return close.sort_index().dropna(how="all")

    def shares(self, ticker: str) -> float | None:
        return self.shares_lookup(yahoo_symbol(ticker))


def returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Günlük basit getiriler."""
    return prices.pct_change(fill_method=None).iloc[1:]


def summary(prices: pd.DataFrame, cpi_monthly: pd.Series | None = None) -> pd.DataFrame:
    """Hisse başına son fiyat, 1 ay / 3 ay / 1 yıl nominal getiri; TÜFE verilirse 1 yıl REEL getiri."""
    last = prices.ffill().iloc[-1]
    out = {"son_fiyat": last, "son_tarih": pd.Series(prices.ffill().index[-1], index=prices.columns)}
    for lab, days in [("getiri_1a", 21), ("getiri_3a", 63), ("getiri_1y", 252)]:
        if len(prices) > days:
            out[lab] = last / prices.ffill().iloc[-1 - days] - 1
    df = pd.DataFrame(out)
    if cpi_monthly is not None and "getiri_1y" in df and len(cpi_monthly) >= 13:
        infl = cpi_monthly.iloc[-1] / cpi_monthly.iloc[-13] - 1
        df["reel_getiri_1y"] = (1 + df["getiri_1y"]) / (1 + infl) - 1
        df.attrs["yillik_enflasyon"] = float(infl)
    return df
