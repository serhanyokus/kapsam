import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kapsam.ai.classifier import classify, extract_amounts
from kapsam.ai.llm import summarize
from kapsam.cli import load_demo
from kapsam.data.statements import from_frame, map_label
from kapsam.normalize import tms29
from kapsam.textutil import norm, parse_tr_number
from kapsam.thesis import Rule, Thesis
from kapsam.validate import accounting_checks, grounded

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "demo"


@pytest.fixture(scope="session")
def demo():
    if not (DEMO / "macro_SENTETIK.csv").exists():
        subprocess.run([sys.executable, str(DEMO / "generate_demo.py")], check=True)
    return load_demo(DEMO)


# --- metin ve sayı ayrıştırma ---------------------------------------------------
@pytest.mark.parametrize("raw,val", [("1.234.567,89", 1234567.89), ("(1.234)", -1234), ("-", np.nan), ("12,5", 12.5), (1000, 1000)])
def test_parse_tr_number(raw, val):
    out = parse_tr_number(raw)
    assert (np.isnan(out) and np.isnan(val)) or out == pytest.approx(val)


def test_turkish_normalization():
    assert norm("DÖNEM KARI (ZARARI)") == norm("Dönem Karı")
    assert norm("İhracat ISPARTA") == "ihracat isparta"


@pytest.mark.parametrize("label,code", [
    ("Hasılat", "revenue"), ("Brüt Kar (Zarar)", "gross_profit"),
    ("Net Parasal Pozisyon Kazançları (Kayıpları)", "net_monetary_gain"),
    ("TOPLAM VARLIKLAR", "total_assets"), ("Bilinmeyen Kalem", None),
])
def test_account_mapping(label, code):
    assert map_label(label) == code


def test_kap_period_formats():
    df = pd.DataFrame({"Kalem": ["Hasılat"], "2025/9": ["100"], "30.06.2025": ["50"], "2024Q4": ["10"]})
    st = from_frame(df, "X", "2025/9")
    assert st.report_date == pd.Period("2025Q3")
    assert set(st.values.columns) == {pd.Period("2025Q3"), pd.Period("2025Q2"), pd.Period("2024Q4")}


# --- TMS 29 motoru ----------------------------------------------------------------
def test_restate_roundtrip():
    cpi = pd.Series([100.0, 110.0], index=pd.period_range("2025Q1", periods=2, freq="Q"))
    v = tms29.restate(100.0, cpi.index[0], cpi.index[1], cpi)
    assert v == pytest.approx(110.0)
    assert tms29.restate(v, cpi.index[1], cpi.index[0], cpi) == pytest.approx(100.0)


def test_quarterly_decomposition_matches_truth(demo):
    """Motor, sentetik verideki 'gerçek' çeyreklik hasılatı birebir geri elde etmeli."""
    reports, cpi, _ = demo
    sys.path.insert(0, str(DEMO))
    import generate_demo as g  # noqa: E402
    q = tms29.quarterly_from_reports(reports, cpi)
    for p in q.columns:
        assert q.at["revenue", p] == pytest.approx(g.nominal(p)["Hasılat"], rel=1e-6)


def test_real_growth_recovered(demo):
    reports, cpi, _ = demo
    real = tms29.to_base(tms29.quarterly_from_reports(reports, cpi), cpi)
    qoq = (real.loc["revenue"] / real.loc["revenue"].shift(1) - 1).dropna()
    assert np.allclose(qoq.values, 0.015, atol=1e-6)  # sentetik reel büyüme %1,5


def test_naive_method_is_biased(demo):
    reports, cpi, _ = demo
    nv = tms29.naive_vs_correct(reports, cpi)
    assert (nv["error_pct"] > 0.05).all()  # düzeltmesiz yöntem hasılatı sistematik şişirir


def test_core_earnings_removes_monetary_gain(demo):
    reports, cpi, _ = demo
    m = tms29.metrics(tms29.quarterly_from_reports(reports, cpi))
    assert (m.loc["core_net_margin"] < m.loc["net_margin"]).all()


def test_usd_uses_report_date_rate(demo):
    reports, cpi, fx = demo
    q = tms29.quarterly_from_reports(reports, cpi)
    usd = tms29.to_usd(q, fx)
    p = q.columns[-1]
    assert usd.at["revenue", p] == pytest.approx(q.at["revenue", p] / fx[p])


# --- doğrulama -----------------------------------------------------------------------
def test_accounting_checks_pass_and_catch_errors(demo):
    reports, cpi, _ = demo
    q = tms29.quarterly_from_reports(reports, cpi)
    assert all(c.passed for c in accounting_checks(q))
    broken = q.copy()
    broken.loc["total_assets", broken.columns[0]] *= 1.1
    assert not all(c.passed for c in accounting_checks(broken))


def test_grounding_flags_hallucinated_numbers():
    src = "Sözleşme bedeli 45 milyon USD olup 3 yıl sürelidir."
    assert grounded([45, 3], src)["all_grounded"]
    assert not grounded([46], src)["all_grounded"]


def test_llm_summary_marked_unverified_when_number_invented():
    src = "Toplam bedel 120 milyon TL idari para cezası verilmiştir."
    fake_ok = lambda _: json.dumps({"ozet": "120 milyon TL ceza.", "kilit_rakamlar": [120], "alintilar": ["idari para cezası"], "tez_etkisi": "olumsuz", "gerekce": "-"})  # noqa: E731
    fake_bad = lambda _: json.dumps({"ozet": "150 milyon TL ceza.", "kilit_rakamlar": [150], "alintilar": ["idari para cezası"], "tez_etkisi": "olumsuz", "gerekce": "-"})  # noqa: E731
    assert summarize(src, fake_ok)["status"] == "DOĞRULANDI"
    assert summarize(src, fake_bad)["status"] == "DOĞRULANMADI"


# --- sınıflandırıcı ve tez -------------------------------------------------------------
@pytest.mark.parametrize("text,cat,sent", [
    ("Şirketimiz ile X arasında tedarik sözleşmesi imzalanmıştır.", "yeni_is_iliskisi", 1),
    ("Bedelsiz sermaye artırımı yapılmasına karar verilmiştir.", "sermaye_artirimi", 0),
    ("Rekabet Kurulu idari para cezası vermiştir.", "dava_ceza", -1),
    ("Pay geri alım programı başlatılmıştır.", "pay_geri_alim", 1),
])
def test_classifier(text, cat, sent):
    c = classify(text)
    assert c.category == cat and c.sentiment == sent


def test_amount_extraction_and_importance():
    assert extract_amounts("bedeli 45 milyon USD")[0] == (45e6, "USD")
    small = classify("tedarik sözleşmesi imzalanmıştır, bedeli 1 milyon TL", market_cap_try=10e9)
    big = classify("tedarik sözleşmesi imzalanmıştır, bedeli 2 milyar TL", market_cap_try=10e9)
    assert big.importance > small.importance


def test_thesis_status(demo):
    reports, cpi, _ = demo
    m = tms29.metrics(tms29.to_base(tms29.quarterly_from_reports(reports, cpi), cpi))
    good = Thesis("DEMO", "marj", [Rule("gross_margin", "up", 0, 1)]).evaluate(m)
    bad = Thesis("DEMO", "marj", [Rule("gross_margin", "down", 0, 1)]).evaluate(m)
    assert good["durum"] == "GÜÇLENDİ" and bad["durum"] == "ZAYIFLADI"
