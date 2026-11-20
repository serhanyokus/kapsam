from dataclasses import replace

import pandas as pd
import pytest
from openpyxl import load_workbook

from kapsam import pipeline, report, valuation as val
from kapsam.cli import main

from .test_core import DEMO, demo  # noqa: F401  (fixture yeniden kullanımı)


@pytest.fixture(scope="module")
def analysis(demo):  # noqa: F811
    cpi, fx = pipeline.load_macro_csv(DEMO / "macro_SENTETIK.csv")
    return pipeline.analyze("DEMO", pipeline.load_company(DEMO, "DEMO"), cpi, fx)


BASE = val.DCFInputs(revenue0=1000.0, growth_high=0.05, growth_terminal=0.02, ebit_margin=0.15,
                     tax_rate=0.25, sales_to_capital=2.0, real_wacc=0.10, net_debt=100.0, shares=10.0)


def test_fisher():
    assert val.real_rate(0.40, 0.30) == pytest.approx(1.40 / 1.30 - 1)


def test_zero_growth_perpetuity():
    """Büyüme yok, yeniden yatırım yok → FD = NOPAT / AOSM."""
    inp = replace(BASE, growth_high=0.0, growth_terminal=0.0)
    nopat = 1000 * 0.15 * 0.75
    assert val.dcf(inp)["ev"] == pytest.approx(nopat / 0.10, rel=1e-9)


def test_value_monotonic():
    v = val.dcf(BASE)["per_share"]
    assert val.dcf(replace(BASE, real_wacc=0.11))["per_share"] < v
    assert val.dcf(replace(BASE, ebit_margin=0.18))["per_share"] > v


def test_growth_requires_reinvestment():
    """Büyüme bedava değil: sermaye getirisi AOSM'nin altındaysa büyüme değer YOK eder,
    üstündeyse yaratır; eşitse (yatırımla hasılatın aynı yıla düşmesinden gelen küçük
    zamanlama etkisi dışında) değer neredeyse değişmez."""
    def ev(roic, g):
        inp = replace(BASE, sales_to_capital=roic / (0.15 * 0.75))
        return val.dcf(replace(inp, growth_high=g, growth_terminal=0.0))["ev"]
    assert ev(0.05, 0.05) < ev(0.05, 0.0)
    assert ev(0.20, 0.05) > ev(0.20, 0.0)
    assert ev(0.10, 0.05) == pytest.approx(ev(0.10, 0.0), rel=0.05)


def test_wacc_must_exceed_terminal_growth():
    with pytest.raises(ValueError):
        val.dcf(replace(BASE, real_wacc=0.02, growth_terminal=0.02))


def test_reverse_dcf_roundtrip():
    target = val.dcf(replace(BASE, growth_high=0.08))["ev"]
    assert val.implied_growth(target, BASE) == pytest.approx(0.08, abs=1e-4)


def test_sensitivity_shape():
    s = val.sensitivity(BASE, [0.09, 0.10, 0.11], [0.03, 0.05, 0.07])
    assert s.shape == (3, 3)
    assert s.loc[0.10, 0.05] == pytest.approx(val.dcf(BASE)["per_share"])


def test_ttm_and_multiples(analysis):
    rev = analysis.real.loc["revenue"]
    assert val.ttm(rev) == pytest.approx(rev.iloc[-4:].sum())
    m = val.multiples(analysis.real, market_cap=10e9, net_debt=2e9)
    assert m["F/K (temel)"] > m["F/K (raporlanan)"]  # parasal kazanç kârı şişiriyor


def test_compare_detects_opposite_monetary_effects(demo):  # noqa: F811
    cpi, fx = pipeline.load_macro_csv(DEMO / "macro_SENTETIK.csv")
    tab = pipeline.compare([pipeline.analyze(t, pipeline.load_company(DEMO, t), cpi, fx) for t in ["DEMO", "DEMO2"]])
    assert tab.at["Parasal kazanç / net kâr", "DEMO"] > 0 > tab.at["Parasal kazanç / net kâr", "DEMO2"]


def test_html_note(analysis):
    inp = report.inputs_from_analysis(analysis, shares=1.5e9)
    h = report.html_note(analysis, inp, 15e9, synthetic=True)
    assert "SENTETİK" in h and "data:image/png;base64" in h and "yatırım tavsiyesi değildir" in h


def test_excel_formulas_present(analysis, tmp_path):
    inp = report.inputs_from_analysis(analysis, shares=1.5e9)
    path = report.excel_model(analysis, inp, 15e9, tmp_path / "m.xlsx")
    ws = load_workbook(path)["INA"]
    formulas = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert len(formulas) > 60


def test_cli_report(tmp_path, demo):  # noqa: F811
    main(["report", "--ticker", "DEMO2", "--price", "5", "--shares", "1e9", "--out", str(tmp_path)])
    assert (tmp_path / "DEMO2_arastirma_notu.html").exists() and (tmp_path / "DEMO2_model.xlsx").exists()


def test_discover(demo):  # noqa: F811
    found = pipeline.discover(DEMO)
    assert set(found) >= {"DEMO", "DEMO2"} and len(found["DEMO"]) == 8


def test_implied_margin_roundtrip():
    target = val.dcf(replace(BASE, ebit_margin=0.21))["ev"]
    assert val.implied_margin(target, BASE) == pytest.approx(0.21, abs=1e-4)
