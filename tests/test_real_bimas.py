"""Gerçek veriyle regresyon testi: BİM 2025/09 – 2026/09 raporları, gerçek TÜFE ve kur (kaynaklar: data/gercek/KAYNAKLAR.md)."""
from pathlib import Path

import pandas as pd
import pytest

from kapsam import pipeline, report, valuation as val
from kapsam.normalize import tms29

ROOT = Path(__file__).resolve().parents[1] / "data" / "gercek"


@pytest.fixture(scope="module")
def bim():
    cpi, fx = pipeline.load_macro_csv(ROOT / "makro_ceyrek.csv")
    reps = pipeline.load_company(ROOT / "kap", "BIMAS")
    return reps, cpi, pipeline.analyze("BIMAS", reps, cpi, fx)


def test_real_cpi_matches_official_annual_rates():
    t = pd.read_csv(ROOT / "tufe_aylik.csv", parse_dates=["tarih"]).set_index("tarih")["tufe"]
    assert t["2024-12-31"] / t["2023-12-31"] - 1 == pytest.approx(0.4438, abs=0.0002)   # TÜİK Aralık 2024: %44,38
    assert t["2025-01-31"] / t["2024-01-31"] - 1 == pytest.approx(0.4212, abs=0.0002)   # TÜİK Ocak 2025: %42,12


def test_press_q3_figure_equals_naive_subtraction(bim):
    reps, cpi, a = bim
    nv = tms29.naive_vs_correct(reps, cpi, "net_income_parent")
    assert nv.at[pd.Period("2026Q3"), "naive"] == pytest.approx(10_385_559e3, rel=1e-4)   # basında çıkan rakam
    assert nv.at[pd.Period("2026Q3"), "correct"] == pytest.approx(9.509e9, rel=1e-3)
    assert nv.at[pd.Period("2026Q3"), "error_pct"] == pytest.approx(0.092, abs=0.002)


def test_cumulative_consistency(bim):
    """Reel çeyreklerin toplamı, 9 aylık kümülatif rakama eşit olmalı (aynı satın alma gücünde)."""
    _, cpi, a = bim
    nine = a.real.loc["net_monetary_gain", [pd.Period(f"2026Q{i}") for i in (1, 2, 3)]].sum()
    assert nine == pytest.approx(22_188_094e3, rel=1e-6)


def test_reverse_dcf_margin_is_finite(bim):
    _, _, a = bim
    inp = report.inputs_from_analysis(a, shares=1.2e9, growth_high=0.03, real_wacc=0.10)
    m = val.implied_margin(402.5 * 1.2e9 + inp.net_debt, inp)
    assert 0.05 < m < 0.15 and inp.net_debt > 0


def test_real_scan_all_companies():
    """8 gerçek BIST şirketi: düzeltmesiz çeyrek hesabı her birinde hasılatı şişiriyor."""
    cpi, fx = pipeline.load_macro_csv(ROOT / "makro_ceyrek.csv")
    sc = pipeline.screen(ROOT / "kap", cpi, fx)
    assert {"BIMAS", "TCELL", "FROTO", "TUPRS", "ASELS", "MGROS", "ARCLK", "ULKER"} <= set(sc.index)
    err = sc["duz_fark_hatasi_hasilat"].astype(float)
    assert (err > 0.05).all() and err.max() < 0.15
    assert sc.loc["MGROS", "parasal_kazanc_olmadan_zarar"]            # parasal kazanç olmasa zarar
    assert sc.loc["ASELS", "parasal_kazanc_net_kar_ytd"] < 0           # net parasal varlık → kayıp
