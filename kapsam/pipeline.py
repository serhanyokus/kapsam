"""Uçtan uca analiz hattı: dosyalardan şirket yükleme, makro veri, normalizasyon, KPI, doğrulama."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .data.statements import Statement, load_file
from .normalize import tms29
from .validate import Check, accounting_checks, reported_quarter_checks

_FILE_RE = re.compile(r"^(?P<ticker>[A-Z0-9]+)_(?P<year>\d{4})_(?P<month>\d{1,2})$")


def discover(folder: str | Path) -> dict[str, list[Path]]:
    """Klasördeki 'HISSE_YYYY_A.csv|xlsx' dosyalarını hisse koduna göre gruplar."""
    out: dict[str, list[Path]] = {}
    for f in sorted(Path(folder).iterdir()):
        if f.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
            continue
        m = _FILE_RE.match(f.stem)
        if m:
            out.setdefault(m["ticker"], []).append(f)
    return out


def load_company(folder: str | Path, ticker: str) -> list[Statement]:
    files = discover(folder).get(ticker, [])
    if not files:
        raise FileNotFoundError(f"{folder} içinde {ticker}_YYYY_A.csv/xlsx dosyası yok")
    reps = []
    for f in files:
        m = _FILE_RE.match(f.stem)
        reps.append(load_file(f, ticker, f"{m['year']}/{m['month']}"))
    return reps


def load_macro_csv(path: str | Path) -> tuple[pd.Series, pd.Series]:
    """period,cpi,usdtry sütunlu CSV (period: 2025Q3)."""
    df = pd.read_csv(path)
    df.index = pd.PeriodIndex(df["period"], freq="Q")
    return df["cpi"], df["usdtry"]


def load_macro_evds(start: str, end: str) -> tuple[pd.Series, pd.Series]:
    from .data.evds import EVDSClient
    m = EVDSClient().quarterly_macro(start, end)
    return m["cpi"], m["usdtry"]


@dataclass
class Analysis:
    ticker: str
    reports: list[Statement]
    quarterly: pd.DataFrame       # her çeyrek kendi rapor tarihinin TL'siyle
    real: pd.DataFrame            # baz tarih TL'si
    usd: pd.DataFrame
    metrics: pd.DataFrame
    naive: pd.DataFrame
    checks: list[Check] = field(default_factory=list)
    cpi: pd.Series | None = None

    def ttm(self, item: str) -> float:
        """Son 12 ay (baz tarih TL'si). Önce son 4 çeyreğin toplamı; çeyrekler eksikse kümülatif raporlardan."""
        if item in self.real.index and self.real.loc[item].dropna().shape[0] >= 4 and self.real.loc[item].iloc[-4:].notna().all():
            return float(self.real.loc[item].iloc[-4:].sum())
        if self.cpi is None:
            raise ValueError("TTM için en az 4 çeyrek gerekir")
        return tms29.ttm_ytd(self.reports, item, self.cpi, base=self.base)

    @property
    def base(self) -> pd.Period:
        return self.real.attrs["base"]

    @property
    def last(self) -> pd.Period:
        return max(self.real.columns)


def analyze(ticker: str, reports: list[Statement], cpi: pd.Series, fx: pd.Series, tax_rate: float = 0.0) -> Analysis:
    q = tms29.quarterly_from_reports(reports, cpi)
    real = tms29.to_base(q, cpi)
    usd = tms29.to_usd(q, fx)
    return Analysis(ticker, reports, q, real, usd, tms29.metrics(real, tax_rate),
                    tms29.naive_vs_correct(reports, cpi), accounting_checks(q) + reported_quarter_checks(q, reports), cpi=cpi)


def compare(analyses: list[Analysis]) -> pd.DataFrame:
    """Şirketler arası karşılaştırma tablosu (son çeyrek, reel ve parasal-kazançtan arındırılmış)."""
    rows = {}
    for a in analyses:
        m, p = a.metrics, a.last
        rows[a.ticker] = {
            "Son çeyrek": str(p),
            "Reel hasılat büyümesi (yıllık)": m.at["revenue_real_yoy", p],
            "Brüt marj": m.at["gross_margin", p],
            "Faaliyet marjı": m.at["operating_margin", p],
            "Raporlanan net marj": m.at["net_margin", p],
            "Temel net marj": m.at["core_net_margin", p],
            "Parasal kazanç / net kâr": m.at["monetary_gain_share", p],
            "Net borç / özkaynak": m.at["net_debt_to_equity", p],
            "Temel ÖK kârlılığı (yıllık)": m.at["core_roe_annualized", p],
            "Düzeltmesiz yöntem ort. hatası": a.naive["error_pct"].abs().mean() if len(a.naive) else float("nan"),
        }
    return pd.DataFrame(rows)


def screen(folder: str | Path, cpi: pd.Series, fx: pd.Series, prices: dict[str, float] | None = None,
           shares: dict[str, float] | None = None, tickers: list[str] | None = None,
           market_caps: dict[str, float] | None = None, meta: pd.DataFrame | None = None) -> pd.DataFrame:
    """Klasördeki tüm şirketler için tarama.

    Sanayi (TMS 29 uygulayan): düzeltmesiz çeyrek hatası, parasal kazanç payı, temel marj, fiyatlanan faaliyet marjı.
    Banka / sigorta ve TMS 29 uygulamayanlar: nominal modda çeyrekler, sektör oranları, F/K ve PD/DD.
    market_caps (TL) verilirse fiyat × hisse sayısı yerine doğrudan kullanılır. meta: evren tablosu (ad, sektör).
    Her şirket ayrı değerlendirilir; biri hata verirse satırına nedeni yazılır, diğerleri etkilenmez.
    """
    from . import report as _report
    from . import valuation as _val
    prices, shares, market_caps = prices or {}, shares or {}, market_caps or {}
    info = meta.set_index("kod") if meta is not None and "kod" in meta else None
    rows = {}
    for t in tickers or sorted(discover(folder)):
        base = {}
        if info is not None and t in info.index:
            base = {"ad": info.at[t, "ad"] if "ad" in info else "", "sektor": info.at[t, "sektor"] if "sektor" in info else ""}
        try:
            reps = load_company(folder, t)
            kind, restated = tms29.statement_kind(reps), tms29.applies_tms29(reps)
            a = analyze(t, reps, cpi, fx)
            m, p = a.metrics, a.last
            ytd = [r for r in reps if r.report_date == p][0].values[p]
            g = lambda k: m.at[k, p] if k in m.index else float("nan")  # noqa: E731
            row = {
                **base, "tur": kind, "tms29": restated, "son_ceyrek": str(p), "rapor_sayisi": len(reps),
                "brut_marj": g("gross_margin"), "faaliyet_marji": g("operating_margin"),
                "raporlanan_net_marj": g("net_margin"), "temel_net_marj": g("core_net_margin"),
                "parasal_kazanc_net_kar_ytd": float("nan"), "parasal_kazanc_olmadan_zarar": False,
                "reel_hasilat_yillik": g("revenue_real_yoy"),
                "duz_fark_hatasi_hasilat": a.naive["error_pct"].get(p, float("nan")) if len(a.naive) else float("nan"),
                "duz_fark_hatasi_net_kar": float("nan"),
                "piyasa_degeri_mn_tl": float("nan"), "fk_ttm": float("nan"), "pd_dd": float("nan"),
                "ozkaynak_karliligi_yillik": g("roe_annualized") if kind != "sanayi" else g("core_roe_annualized"),
                "ucret_payi": g("fee_share"), "karsilik_nfg": g("provision_to_nii"), "kredi_mevduat": g("loan_to_deposit"),
                "fiyatlanan_faaliyet_marji": float("nan"), "not": "",
            }
            notes = []
            ni, nmg = ytd.get("net_income", float("nan")), ytd.get("net_monetary_gain", float("nan"))
            if pd.notna(ni) and pd.notna(nmg):
                if ni > 0:
                    row["parasal_kazanc_net_kar_ytd"] = nmg / ni
                if nmg > 0 and ni - nmg < 0:
                    row["parasal_kazanc_olmadan_zarar"] = True
                    notes.append("parasal kazanç olmasa yılbaşından beri zarar" if ni > 0 else "zararda; parasal kazanç zararı küçültüyor")
                elif nmg < 0:
                    notes.append("net parasal varlık: enflasyondan kayıp yazıyor")
            item = "net_income_parent" if "net_income_parent" in a.quarterly.index else "net_income"
            nk = tms29.naive_vs_correct(reps, cpi, item)
            if len(nk):
                row["duz_fark_hatasi_net_kar"] = nk["error_pct"].get(p, float("nan"))
            if kind != "sanayi":
                notes.append(f"{kind}: TMS 29 uygulanmaz, nominal mod")
            elif not restated:
                notes.append("parasal pozisyon satırı yok (TMS 29 uygulanmıyor olabilir), nominal mod")
            # piyasa değeri ve çarpanlar
            mcap = market_caps.get(t) or (prices[t] * float(shares[t]) if t in prices and shares.get(t) else None)
            if mcap:
                row["piyasa_degeri_mn_tl"] = mcap / 1e6
                try:
                    ni_ttm = a.ttm(item)
                    row["fk_ttm"] = mcap / ni_ttm if ni_ttm > 0 else float("nan")
                except (ValueError, KeyError):
                    pass
                eq = a.quarterly.loc["total_equity"].dropna() if "total_equity" in a.quarterly.index else pd.Series(dtype=float)
                if len(eq):
                    row["pd_dd"] = mcap / eq.iloc[-1]
                if kind == "sanayi" and "operating_profit" in a.real.index:
                    try:
                        inp = _report.inputs_from_analysis(a, shares=1.0)
                        nd = 0.0 if pd.isna(inp.net_debt) else inp.net_debt
                        row["fiyatlanan_faaliyet_marji"] = _val.implied_margin(mcap + nd, replace(inp, net_debt=nd))
                    except (ValueError, KeyError) as e:
                        notes.append(f"değerleme: {e}")
            row.update(_quality(a, reps, cpi, p, item, kind))
            row["not"] = "; ".join(notes)
            rows[t] = row
        except Exception as e:  # noqa: BLE001
            rows[t] = {**base, "not": f"hata: {e}"}
    return pd.DataFrame(rows).T.replace([np.inf, -np.inf], np.nan)


def _quality(a: "Analysis", reps: list, cpi: pd.Series, p: pd.Period, item: str, kind: str) -> dict:
    """Kâr kalitesi, nakit üretimi ve bilanço göstergeleri (son 12 ay, baz tarih TL'si; mn TL).
    İşletme nakit akışı − yatırım harcaması serbest nakit akışı (FCFF) değildir; kaba göstergedir."""
    nan = float("nan")
    out = {k: nan for k in ("net_kar_ana_ttm_mn", "isletme_na_ttm_mn", "capex_ttm_mn", "serbest_nakit_ttm_mn", "nakit_donusumu",
                            "faaliyet_disi_pay", "net_borc_mn", "net_borc_favok", "reel_hasilat_9a")}

    def ttm(k):
        try:
            v = a.ttm(k)
            return v if np.isfinite(v) else nan
        except Exception:  # noqa: BLE001
            return nan
    ni, ocf, cx = ttm(item), ttm("operating_cash_flow"), ttm("capex")
    out.update(net_kar_ana_ttm_mn=ni / 1e6, isletme_na_ttm_mn=ocf / 1e6, capex_ttm_mn=cx / 1e6)
    if pd.notna(ocf):
        out["serbest_nakit_ttm_mn"] = (ocf - abs(cx if pd.notna(cx) else 0.0)) / 1e6
        if pd.notna(ni) and ni > 0:
            out["nakit_donusumu"] = ocf / ni
    if kind == "sanayi":
        op, dep = ttm("operating_profit"), ttm("depreciation")
        if pd.notna(op) and op > 0 and pd.notna(ni):
            out["faaliyet_disi_pay"] = ni / op
        nd = a.metrics.loc["net_debt"].dropna() if "net_debt" in a.metrics.index else pd.Series(dtype=float)
        if len(nd):
            out["net_borc_mn"] = float(nd.iloc[-1]) / 1e6
            ebitda = (op if pd.notna(op) else nan) + (dep if pd.notna(dep) else 0.0)
            if pd.notna(ebitda) and ebitda > 0:
                out["net_borc_favok"] = float(nd.iloc[-1]) / ebitda
        prev = [r for r in reps if r.report_date == p - 4]
        cur = [r for r in reps if r.report_date == p]
        if prev and cur and p in cpi.index and (p - 4) in cpi.index:
            x, y = cur[0].values[p].get("revenue", nan), prev[0].values[p - 4].get("revenue", nan)
            if pd.notna(x) and pd.notna(y) and y > 0:
                out["reel_hasilat_9a"] = x / (y * cpi[p] / cpi[p - 4]) - 1
    return out
