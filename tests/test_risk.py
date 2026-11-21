"""Risk modülü: beta/korelasyon doğruluğu, Ledoit–Wolf, sektör korelasyonu, yıllara bölünmüş fiyat deposu, tüm piyasa adımı."""
import json

import numpy as np
import pandas as pd
import pytest

from kapsam import risk, update
from kapsam.data.market import Market


def factor_prices(n_days=400, betas=(0.5, 1.0, 1.5, 1.2), idio=0.01, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-02", periods=n_days)
    m = rng.normal(0.0005, 0.012, n_days)
    data = {"XU100": 1000 * np.exp(np.cumsum(m))}
    for i, b in enumerate(betas):
        data[f"H{i}"] = 10 * np.exp(np.cumsum(b * m + rng.normal(0, idio, n_days)))
    return pd.DataFrame(data, index=idx)


def test_beta_and_correlation_recovered():
    px = factor_prices()
    tab = risk.risk_table(px, days=252)
    for i, b in enumerate((0.5, 1.0, 1.5, 1.2)):
        assert tab.loc[f"H{i}", "beta"] == pytest.approx(b, abs=0.12)
    assert tab.loc["H2", "korelasyon_xu100"] > tab.loc["H0", "korelasyon_xu100"]     # yüksek beta, aynı özgün risk → daha yüksek korelasyon
    assert (tab["oynaklik_yillik"] > 0).all() and (tab["max_dusus"] <= 0).all()
    assert (tab["var95_gunluk"] > 0).all() and (tab["es95_gunluk"] >= tab["var95_gunluk"]).all()
    assert tab["sistematik_risk_payi"].between(0, 1).all()


def test_real_and_usd_returns():
    px = factor_prices()
    cpi = pd.Series(np.linspace(100, 130, 30), index=pd.date_range("2024-07-31", periods=30, freq="ME"))
    fx = pd.Series(np.linspace(30, 45, 600), index=pd.bdate_range("2024-09-02", periods=600))
    tab = risk.risk_table(px, cpi_monthly=cpi, usdtry=fx)
    infl = cpi.iloc[-1] / cpi.iloc[-13] - 1
    row = tab.loc["H1"]
    assert row["reel_getiri_yillik"] == pytest.approx((1 + row["getiri_yillik"]) / (1 + infl) - 1)
    assert row["usd_getiri_yillik"] < row["getiri_yillik"]                             # TL değer kaybettiği için


def test_bad_ticks_removed():
    px = factor_prices()
    px.iloc[200, 1] *= 3                                                                  # veri hatası: tek günlük 3 kat
    r = risk.log_returns(px)
    assert r["H0"].abs().max() < np.log(1.6)


def test_cov_corr_and_ledoit_wolf_psd():
    px = factor_prices(betas=tuple(np.linspace(0.3, 1.6, 12)))
    r = risk.window(risk.log_returns(px))
    cov, corr = risk.cov_corr(r)
    assert np.allclose(np.diag(corr), 1) and np.allclose(cov, cov.T)
    lw, delta = risk.ledoit_wolf(r.drop(columns="XU100"))
    assert 0 <= delta <= 1 and np.linalg.eigvalsh(lw.values).min() > 0
    s = r.drop(columns="XU100").cov().values * 252
    # küçültme: köşegen dışı elemanlar örnek kovaryansa göre sıfıra doğru çekilir
    off = ~np.eye(len(lw), dtype=bool)
    assert np.abs(lw.values[off]).sum() <= np.abs(s[off]).sum() + 1e-12


def test_sector_corr_and_cluster_order():
    px = factor_prices(betas=(1, 1, 1, 1))
    r = risk.log_returns(px)
    _, corr = risk.cov_corr(r.drop(columns="XU100"))
    sec = pd.Series({"H0": "A", "H1": "A", "H2": "B", "H3": "B"})
    sc = risk.sector_corr(corr, sec)
    assert list(sc.index) == ["A", "B"] and np.allclose(sc.values, sc.values.T)
    assert set(risk.cluster_order(corr)) == set(corr.index)


def test_prices_by_year_roundtrip(tmp_path):
    px = factor_prices(n_days=500)
    written = risk.save_prices_by_year(px, tmp_path)
    assert {f.name for f in written} == {"2025.csv", "2026.csv"}
    back = risk.load_prices(tmp_path)
    assert back.shape == px.shape and np.allclose(back.values, px.round(4).values)
    assert risk.save_prices_by_year(px, tmp_path) == []                                 # değişmeyen yıl yeniden yazılmaz


def test_full_universe_prices_and_risk_step(tmp_path):
    """Evren='tum': tüm hisselerin fiyatı parça parça indirilir, yıllara bölünür; risk adımı tablo ve matrisleri yazar."""
    tick = [f"H{i}" for i in range(4)]
    px = factor_prices()
    calls = []

    def dl(symbols, start):                                                            # Yahoo sembolleriyle döner (THYAO.IS, XU100.IS)
        calls.append(len(symbols))
        return pd.DataFrame({s: px[s.removesuffix(".IS")] for s in symbols})

    (tmp_path / "config").mkdir()
    cfg = {"baslangic": "2025-01-01", "evren": "tum", "hisseler": [{"kod": "H0", "hisse_sayisi": 1e9}, {"kod": "H1", "hisse_sayisi": 1e9}],
           "olaylar": []}
    (tmp_path / "config" / "takip.json").write_text(json.dumps(cfg))
    uni = pd.DataFrame({"kod": tick, "ad": [f"Şirket {t}" for t in tick], "sektor": ["A", "A", "B", "B"]})
    p = update.Paths(tmp_path)
    st = update.Status()
    update.step_prices(p, cfg, st, Market(dl, lambda s: 1e9), uni)
    assert st.steps["fiyat"]["durum"] == "tamam" and "4/4 hisse" in st.steps["fiyat"]["detay"]
    assert set(risk.load_prices(p.data / "fiyat").columns) == set(tick) | {"XU100"}
    assert list(pd.read_csv(p.data / "fiyatlar.csv", index_col=0).columns) == ["H0", "H1", "XU100"]
    tab = update.step_risk(p, cfg, st, uni, today=pd.Timestamp("2026-07-31"))          # cuma → tüm matrisler
    assert st.steps["risk"]["durum"] == "tamam", st.steps["risk"]
    out = p.out / "risk"
    for f in ["risk_ozet.csv", "takip_korelasyon.csv", "takip_kovaryans.csv", "sektor_korelasyon.csv",
              "korelasyon_tum.csv.gz", "kovaryans_tum.csv.gz", "kovaryans_ledoit_wolf.csv.gz", "index.html"]:
        assert (out / f).exists(), f
    full = pd.read_csv(out / "korelasyon_tum.csv.gz", index_col=0)
    assert full.shape == (5, 5)
    assert tab.loc["H0", "sektor"] == "A" and "en_yakin_3" in tab
    assert "Risk tablosu" in (out / "index.html").read_text(encoding="utf-8")


def test_every_stock_included_even_new_listings():
    """Yeni halka arz (30 gün verisi) da risk tablosuna ve Ledoit–Wolf matrisine girer; güvenilirliği 'düşük' işaretlenir."""
    px = factor_prices(betas=tuple(np.linspace(0.4, 1.4, 8)))
    px.loc[px.index[:-30], "H7"] = np.nan                                                # son 30 gün işlem gören hisse
    r = risk.window(risk.log_returns(px))
    tab = risk.risk_table(px)
    assert "H7" in tab.index and tab.loc["H7", "guvenilirlik"].startswith("düşük") and tab.loc["H0", "guvenilirlik"] == "yüksek"
    lw, delta = risk.ledoit_wolf_all(r.drop(columns="XU100"))
    assert "H7" in lw.index and len(lw) == 8 and 0 <= delta <= 1
    assert np.linalg.eigvalsh(lw.values).min() > 0 and np.allclose(lw.values, lw.values.T)
    # tam veri olan hisselerde örnek kovaryansa yakın (küçültme küçük)
    s = r[["H0", "H1"]].cov().values * 252
    assert lw.loc["H0", "H0"] == pytest.approx(s[0, 0], rel=0.3)


def test_ttm_from_cumulative_reports_semiannual():
    """6 ayda bir rapor veren şirket: çeyrek ayrıştırılamaz; son 12 ay = YB + önceki yıl − önceki yıl aynı dönem (TÜFE ile)."""
    from kapsam.data.statements import Statement
    from kapsam.normalize import tms29
    idx = pd.period_range("2025Q2", "2026Q2", freq="Q")
    cpi = pd.Series([100, 105, 110, 116, 122.0], index=idx)

    def rep(p, rev):
        return Statement("YARI", pd.Period(p, "Q"), pd.DataFrame({pd.Period(p, "Q"): pd.Series(
            {"revenue": rev, "net_income": rev / 10, "net_monetary_gain": 1.0}, dtype=float)}), cumulative=True)
    reps = [rep("2025Q2", 50), rep("2025Q4", 110), rep("2026Q2", 70)]
    v = tms29.ttm_ytd(reps, "revenue", cpi)
    assert v == pytest.approx(70 + 110 * 122 / 110 - 50 * 122 / 100)
    from kapsam import pipeline
    a = pipeline.analyze("YARI", reps, cpi, pd.Series(30.0, index=idx))
    assert a.ttm("revenue") == pytest.approx(v)


def test_basic_note_for_company_without_sales():
    from kapsam import pipeline, report
    from kapsam.data.statements import Statement
    idx = pd.period_range("2025Q3", "2026Q3", freq="Q")
    cpi = pd.Series([100, 106, 112, 118, 124.0], index=idx)
    reps = [Statement("HOLD", p, pd.DataFrame({p: pd.Series({"net_income": 10.0 * (p.quarter), "net_monetary_gain": 3.0 * p.quarter,
                                                             "total_equity": 500.0}, dtype=float)}), cumulative=True) for p in idx]
    a = pipeline.analyze("HOLD", reps, cpi, pd.Series(30.0, index=idx))
    with pytest.raises(report.NoDCF):
        report.inputs_from_analysis(a, shares=1e6)
    page = report.basic_note(a, 1e4, "Holding A.Ş.", {"beta": 0.9, "gozlem": 252, "oynaklik_yillik": 0.4}, "hasılat yok")
    assert "İNA) uygulanmadı" in page and "Piyasa riski" in page and "Holding A.Ş." in page
