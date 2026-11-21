"""Risk ve bağımlılık ölçüleri: tüm BIST hisseleri için getiri, oynaklık, beta, korelasyon ve kovaryans.

Girdi: günlük düzeltilmiş kapanış fiyatları (sütunlar hisse kodu, 'XU100' endeks).
Getiriler logaritmik günlük getiridir. Yıllıklaştırma 252 işlem günüyle yapılır.

Kovaryans tahminleri
--------------------
* Örnek kovaryans: çiftler için ortak gözlemlerle (pairwise). Çok sayıda hissede pozitif tanımlı olmayabilir.
* Ledoit–Wolf küçültmesi (2004, ölçeklenmiş birim matris hedefi): yalnızca pencerenin tamamında verisi olan
  hisselerle hesaplanır; her zaman pozitif tanımlıdır, portföy optimizasyonu için uygundur.

Enflasyon: korelasyon nominal ve reel getiride neredeyse aynıdır (aynı TÜFE bölücüsü), ancak getiri ve
Sharpe benzeri oranlar reel (TÜFE) ve USD bazında da verilir.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Günlük log getiriler. Sıfır/negatif fiyatlar ve 1 günde |%60|'ı aşan sıçramalar (veri hatası) NaN yapılır."""
    p = prices.where(prices > 0)
    r = np.log(p / p.shift(1))
    return r.where(r.abs() < np.log(1.6)).iloc[1:]


def window(r: pd.DataFrame, days: int = TRADING_DAYS) -> pd.DataFrame:
    return r.iloc[-days:]


def _max_drawdown(p: pd.Series) -> float:
    p = p.dropna()
    if len(p) < 2:
        return np.nan
    return float((p / p.cummax() - 1).min())


MIN_OBS = 20            # her hisse dahil: en az ~1 ay işlem; 120 günden azında 'güvenilirlik: düşük'
RELIABLE_OBS = 120


def risk_table(prices: pd.DataFrame, market: str = "XU100", days: int = TRADING_DAYS, min_obs: int = MIN_OBS,
               cpi_monthly: pd.Series | None = None, usdtry: pd.Series | None = None,
               corr: pd.DataFrame | None = None) -> pd.DataFrame:
    """Hisse başına risk özeti (son `days` işlem günü)."""
    prices = prices.sort_index()
    r = window(log_returns(prices), days)
    px = prices.loc[r.index[0]:] if len(r) else prices
    m = r[market] if market in r else None
    infl = usd_chg = np.nan
    if cpi_monthly is not None and len(cpi_monthly.dropna()) >= 13:
        c = cpi_monthly.dropna()
        infl = c.iloc[-1] / c.iloc[-13] - 1
    if usdtry is not None and len(r):
        fx = usdtry.dropna().sort_index()
        a, b = fx[fx.index <= r.index[0]], fx[fx.index <= r.index[-1]]
        if len(a) and len(b):
            usd_chg = b.iloc[-1] / a.iloc[-1] - 1
    rows = {}
    for t in r.columns:
        if t == market:
            continue
        x = r[t].dropna()
        if len(x) < min_obs:
            continue
        ann_ret = float(np.exp(x.sum() * TRADING_DAYS / len(x)) - 1)
        vol = float(x.std(ddof=1) * np.sqrt(TRADING_DAYS))
        row = {"gozlem": len(x), "guvenilirlik": "yüksek" if len(x) >= RELIABLE_OBS else "düşük (az veri)",
               "son_fiyat": float(px[t].dropna().iloc[-1]),
               "getiri_yillik": ann_ret,
               "reel_getiri_yillik": (1 + ann_ret) / (1 + infl) - 1 if pd.notna(infl) else np.nan,
               "usd_getiri_yillik": (1 + ann_ret) / (1 + usd_chg) - 1 if pd.notna(usd_chg) else np.nan,
               "oynaklik_yillik": vol,
               "asagi_yon_oynaklik": float(x[x < 0].std(ddof=1) * np.sqrt(TRADING_DAYS)) if (x < 0).sum() > 2 else np.nan,
               "getiri_oynaklik_orani": ann_ret / vol if vol > 0 else np.nan,
               "max_dusus": _max_drawdown(px[t]),
               "var95_gunluk": float(-np.quantile(x, 0.05)),
               "es95_gunluk": float(-x[x <= np.quantile(x, 0.05)].mean()),
               "carpiklik": float(x.skew()), "basiklik": float(x.kurt())}
        if m is not None:
            j = pd.concat([x, m], axis=1, join="inner").dropna()
            if len(j) >= min_obs:
                cov = np.cov(j.iloc[:, 0], j.iloc[:, 1], ddof=1)
                beta = cov[0, 1] / cov[1, 1]
                resid = j.iloc[:, 0] - beta * j.iloc[:, 1]
                row.update({"beta": float(beta), "korelasyon_xu100": float(np.corrcoef(j.iloc[:, 0], j.iloc[:, 1])[0, 1]),
                            "ozgun_oynaklik": float(resid.std(ddof=1) * np.sqrt(TRADING_DAYS)),
                            "sistematik_risk_payi": float(np.corrcoef(j.iloc[:, 0], j.iloc[:, 1])[0, 1] ** 2)})
        rows[t] = row
    out = pd.DataFrame(rows).T
    if corr is not None and len(out):
        c = corr.drop(index=[market], columns=[market], errors="ignore")
        c = c.where(~np.eye(len(c), dtype=bool))
        out["ort_korelasyon"] = c.mean().reindex(out.index)
        tops = {}
        for t in out.index:
            if t in c:
                s = c[t].dropna().sort_values(ascending=False).head(3)
                tops[t] = ", ".join(f"{k} {v:.2f}" for k, v in s.items())
        out["en_yakin_3"] = pd.Series(tops)
    out.attrs.update({"pencere_gun": days, "baslangic": str(r.index[0].date()) if len(r) else "",
                      "bitis": str(r.index[-1].date()) if len(r) else "", "yillik_enflasyon": infl, "usdtry_degisim": usd_chg})
    return out


def cov_corr(r: pd.DataFrame, min_obs: int = MIN_OBS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Yıllıklaştırılmış örnek kovaryans ve korelasyon (çift bazında ortak gözlemlerle)."""
    keep = [c for c in r.columns if r[c].count() >= min_obs]
    x = r[keep]
    return x.cov(min_periods=min_obs) * TRADING_DAYS, x.corr(min_periods=min_obs)


def ledoit_wolf(r: pd.DataFrame, min_coverage: float = 1.0) -> tuple[pd.DataFrame, float]:
    """Ledoit–Wolf (2004) küçültülmüş kovaryans, hedef: ortalama varyans × I. Yıllıklaştırılmış.
    Yalnızca pencerede yeterli (varsayılan: tam) verisi olan hisseler. Dönen: (matris, küçültme katsayısı δ)."""
    cov_ok = r.columns[r.notna().mean() >= min_coverage]
    x = r[cov_ok].dropna()
    n, p = x.shape
    if n < 3 or p < 2:
        return pd.DataFrame(), np.nan
    X = x.values - x.values.mean(axis=0)
    S = X.T @ X / n
    mu = np.trace(S) / p
    F = mu * np.eye(p)
    d2 = np.sum((S - F) ** 2) / p
    b_bar2 = sum(np.sum((np.outer(X[k], X[k]) - S) ** 2) for k in range(n)) / (n ** 2) / p
    b2 = min(b_bar2, d2)
    delta = b2 / d2 if d2 > 0 else 1.0
    sigma = delta * F + (1 - delta) * S
    return pd.DataFrame(sigma * TRADING_DAYS, index=x.columns, columns=x.columns), float(delta)


def ledoit_wolf_all(r: pd.DataFrame, min_obs: int = MIN_OBS) -> tuple[pd.DataFrame, float]:
    """TÜM hisseler için küçültülmüş kovaryans (eksik veri dahil).

    1. Küçültme katsayısı δ, pencerenin tamamında verisi olan hisselerle Ledoit–Wolf (2004) formülünden bulunur.
    2. Çift bazında örnek kovaryans S (ortak gözlem ≥ min_obs; yetersiz çiftlerde korelasyon 0 varsayılır).
    3. Σ = δ·(ort. varyans)·I + (1−δ)·S, ardından en yakın pozitif tanımlı matrise izdüşüm (özdeğer kırpma).
    Dönen matris yıllıklaştırılmıştır ve her zaman pozitif tanımlıdır."""
    keep = [c for c in r.columns if r[c].count() >= min_obs]
    x = r[keep]
    _, delta = ledoit_wolf(x)
    if pd.isna(delta):
        delta = 0.5
    S = x.cov(min_periods=min_obs).values
    d = np.nanmean(np.diag(S))
    S = np.where(np.isnan(S), 0.0, S)
    F = d * np.eye(len(keep))
    sigma = delta * F + (1 - delta) * S
    w, v = np.linalg.eigh((sigma + sigma.T) / 2)
    w = np.clip(w, d * 1e-4, None)
    sigma = (v * w) @ v.T
    return pd.DataFrame(sigma * TRADING_DAYS, index=keep, columns=keep), float(delta)


def sector_corr(corr: pd.DataFrame, sectors: pd.Series) -> pd.DataFrame:
    """Sektörler arası ortalama korelasyon (köşegen: sektör içi ortalama, kendisi hariç)."""
    sec = sectors.reindex(corr.index).fillna("Diğer")
    names = sorted(sec.unique())
    out = pd.DataFrame(index=names, columns=names, dtype=float)
    vals = corr.values.copy()
    np.fill_diagonal(vals, np.nan)
    c = pd.DataFrame(vals, index=corr.index, columns=corr.columns)
    for a in names:
        ia = sec.index[sec == a]
        for b in names:
            ib = sec.index[sec == b]
            v = c.loc[ia, ib].values
            out.loc[a, b] = float(np.nanmean(v)) if np.isfinite(v).any() else np.nan   # tek şirketli sektörün kendi içi: NaN
    return out


def heatmap_png(corr: pd.DataFrame, title: str = "") -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(corr)
    fig, ax = plt.subplots(figsize=(max(5, n * 0.28), max(4.4, n * 0.26)))
    im = ax.imshow(corr.values.astype(float), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n), corr.columns, rotation=90, fontsize=6)
    ax.set_yticks(range(n), corr.index, fontsize=6)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    ax.set_title(title, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def cluster_order(corr: pd.DataFrame) -> list[str]:
    """Isı haritası için hiyerarşik kümeleme sırası (benzer hisseler yan yana)."""
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import squareform
    c = corr.fillna(0).clip(-1, 1)
    d = np.sqrt(np.clip(2 * (1 - c.values), 0, None))
    np.fill_diagonal(d, 0)
    order = leaves_list(linkage(squareform(d, checks=False), "average"))
    return [corr.index[i] for i in order]


# --- depolama: fiyatlar yıllara bölünür (yalnızca içinde bulunulan yılın dosyası her gün değişir) ---------------
def save_prices_by_year(prices: pd.DataFrame, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for y, df in prices.groupby(prices.index.year):
        f = folder / f"{y}.csv"
        new = df.dropna(axis=1, how="all").round(4)
        if f.exists():
            old = pd.read_csv(f, index_col=0, parse_dates=True)
            if old.shape == new.shape and old.round(4).equals(new.reindex(columns=old.columns)):
                continue
        new.to_csv(f, index_label="tarih")
        out.append(f)
    return out


def load_prices(folder: Path) -> pd.DataFrame:
    files = sorted(folder.glob("*.csv"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(f, index_col=0, parse_dates=True) for f in files]).sort_index()
