"""Gerçek KAP Excel düzenini taklit eden dosyalarla ayrıştırıcı testi.

Gerçek indirilen dosyalarda: üstte başlık satırları, 'Dipnot Referansı' sütunu, tarih aralıklı
sütun başlıkları ('Cari Dönem 01.01.2025 - 30.09.2025'), ayrı sayfalarda bilanço / gelir tablosu /
nakit akış, girintili kalem adları ve '3 Aylık' sütunları bulunur.
"""
import sys

import numpy as np
import pandas as pd
import pytest

from kapsam import pipeline
from kapsam.data.statements import classify_header, load_file, map_label
from kapsam.normalize import tms29
from kapsam.validate import reported_quarter_checks

from .test_core import DEMO, demo  # noqa: F401


@pytest.mark.parametrize("h,period,kind", [
    ("Cari Dönem 01.01.2025 - 30.09.2025", "2025Q3", "nokta"),
    ("Cari 3 Aylık 01.07.2025 - 30.09.2025", "2025Q3", "3ay"),
    ("Önceki 3 Aylık\n01.07.2024 - 30.09.2024", "2024Q3", "3ay"),
    ("Önceki Dönem 31.12.2024", "2024Q4", "nokta"),
    ("Current Period 2025-01-01 - 2025-06-30", "2025Q2", "nokta"),
    ("2025/9", "2025Q3", "nokta"),
    ("Dipnot Referansı", None, "yok"),
    ("Unnamed: 3", None, "yok"),
])
def test_classify_header(h, period, kind):
    p, k = classify_header(h)
    assert k == kind and (p is None if period is None else p == pd.Period(period))


@pytest.mark.parametrize("label,code", [
    ("   Hasılat", "revenue"), ("Revenue", "revenue"), ("Gains (losses) on net monetary position", "net_monetary_gain"),
    ("Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları", "capex"),
    ("1.1 Hasılat", "revenue"), ("Total assets", "total_assets"),
])
def test_label_variants(label, code):
    assert map_label(label) == code


def _kap_workbook(path, p, demo_mod, english=False):
    """Sentetik şirketin p raporunu KAP'ın Excel düzeninde yazar (3 sayfa, başlık satırları, dipnot sütunu)."""
    g = demo_mod
    ytd, ytd_prev = g.ytd(p, p), g.ytd(p - 4, p)
    q, q_prev = {k: v * g.CPI[p] / g.CPI[p] for k, v in g.nominal(p).items()}, \
        {k: v * g.CPI[p] / g.CPI[p - 4] for k, v in g.nominal(p - 4).items()}
    bal, bal_prev = g.balance(p, p), g.balance(pd.Period(year=p.year - 1, quarter=4, freq="Q"), p)
    end = p.end_time.strftime("%d.%m.%Y")
    s_ytd, s_q = f"01.01.{p.year}", (p.start_time).strftime("%d.%m.%Y")
    lab = (lambda tr, en: en) if english else (lambda tr, en: tr)

    is_rows = [["", "", "", "", "", ""],
               ["DEMO SANAYİ A.Ş.", "", "", "", "", ""],
               [lab("Kar veya Zarar Tablosu", "Profit or loss"), "", "", "", "", ""],
               [lab("Kalem", "Item"), lab("Dipnot Referansı", "Footnote"),
                f"Cari Dönem {s_ytd} - {end}", f"Önceki Dönem 01.01.{p.year-1} - {(p-4).end_time:%d.%m.%Y}",
                f"Cari 3 Aylık {s_q} - {end}", f"Önceki 3 Aylık {(p-4).start_time:%d.%m.%Y} - {(p-4).end_time:%d.%m.%Y}"],
               [lab("Kar veya Zarar Kısmı", "Profit or loss section"), "", "", "", "", ""]]
    names = {"Hasılat": "Revenue", "Satışların Maliyeti (-)": "Cost of sales", "Brüt Kar (Zarar)": "Gross Profit (Loss)",
             "Esas Faaliyet Karı (Zararı)": "Profit (loss) from operating activities",
             "Net Parasal Pozisyon Kazançları (Kayıpları)": "Gains (losses) on net monetary position",
             "Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)": "Profit (loss) from continuing operations before tax",
             "Dönem Karı (Zararı)": "Profit (loss)"}
    for k in ytd:
        is_rows.append(["   " + (names[k] if english else k), "12", ytd[k], ytd_prev[k], q[k], q_prev[k]])
    bs_rows = [["Finansal Durum Tablosu", "", "", ""],
               ["Kalem", "Dipnot Referansı", f"Cari Dönem {end}", f"Önceki Dönem 31.12.{p.year-1}"]]
    bnames = {"Nakit ve Nakit Benzerleri": "Cash and cash equivalents", "Toplam Varlıklar": "Total assets",
              "Kısa Vadeli Borçlanmalar": "Current borrowings", "Uzun Vadeli Borçlanmalar": "Non-current borrowings",
              "Toplam Özkaynaklar": "Total equity", "Toplam Kaynaklar": "Total liabilities and equity"}
    for k in bal:
        bs_rows.append([bnames[k] if english else k, "", bal[k], bal_prev[k]])
    cf_rows = [["Nakit Akış Tablosu", "", "", ""],
               ["Kalem", "Dipnot", f"Cari Dönem {s_ytd} - {end}", f"Önceki Dönem 01.01.{p.year-1} - {(p-4).end_time:%d.%m.%Y}"],
               ["Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "", 0.04 * ytd["Hasılat"], 0.04 * ytd_prev["Hasılat"]],
               ["Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları", "", -0.07 * ytd["Hasılat"],
                -0.07 * ytd_prev["Hasılat"]]]
    with pd.ExcelWriter(path) as w:
        pd.DataFrame(bs_rows).to_excel(w, sheet_name="Finansal Durum", header=False, index=False)
        pd.DataFrame(is_rows).to_excel(w, sheet_name="Kar veya Zarar", header=False, index=False)
        pd.DataFrame(cf_rows).to_excel(w, sheet_name="Nakit Akış", header=False, index=False)


@pytest.fixture(scope="module")
def gen(demo):  # noqa: F811
    sys.path.insert(0, str(DEMO))
    import generate_demo
    return generate_demo


@pytest.mark.parametrize("english", [False, True])
def test_real_layout_matches_engine_truth(tmp_path, gen, english):
    for p in pd.period_range("2025Q1", "2025Q4", freq="Q"):
        _kap_workbook(tmp_path / f"DEMO_{p.year}_{p.quarter*3}.xlsx", p, gen, english)
    reps = pipeline.load_company(tmp_path, "DEMO")
    st = [r for r in reps if r.report_date == pd.Period("2025Q3")][0]
    assert {"revenue", "net_monetary_gain", "total_assets", "capex", "depreciation"} <= set(st.values.index)
    assert pd.Period("2024Q4") in st.values.columns            # önceki yıl sonu bilanço sütunu
    assert not st.quarterly_reported.empty
    cpi = gen.CPI
    q = tms29.quarterly_from_reports(reps, cpi)
    for p in q.columns:
        assert q.at["revenue", p] == pytest.approx(gen.nominal(p)["Hasılat"], rel=1e-6)
    checks = reported_quarter_checks(q, reps)
    assert len(checks) >= 8 and all(c.passed for c in checks)


def test_cross_check_catches_parsing_error(tmp_path, gen):
    for p in pd.period_range("2025Q1", "2025Q3", freq="Q"):
        _kap_workbook(tmp_path / f"DEMO_{p.year}_{p.quarter*3}.xlsx", p, gen)
    reps = pipeline.load_company(tmp_path, "DEMO")
    q = tms29.quarterly_from_reports(reps, gen.CPI)
    q.loc["revenue", pd.Period("2025Q3")] *= 1.05            # hatalı ayrıştırmayı taklit et
    bad = [c for c in reported_quarter_checks(q, reps) if not c.passed]
    assert bad and bad[0].name == "3_aylık_revenue"


def test_unreadable_file_raises_clear_error(tmp_path):
    pd.DataFrame([["Merhaba", "dünya"]]).to_excel(tmp_path / "X_2025_9.xlsx", header=False, index=False)
    with pytest.raises(ValueError, match="dönem sütunu"):
        load_file(tmp_path / "X_2025_9.xlsx", "X", "2025/9")


def test_sales_to_capital_estimated_from_cash_flow(tmp_path, gen):
    from kapsam import report
    for p in pd.period_range("2024Q1", "2025Q4", freq="Q"):
        _kap_workbook(tmp_path / f"DEMO_{p.year}_{p.quarter*3}.xlsx", p, gen)
    cpi, fx = gen.CPI, gen.USDTRY
    a = pipeline.analyze("DEMO", pipeline.load_company(tmp_path, "DEMO"), cpi, fx)
    assert "capex" in a.real.index and (a.real.loc["capex"] < 0).all()   # çeyreğe ayrıştırıldı, işaret korundu
    s2c, why = report.estimate_sales_to_capital(a)
    # sentetik: capex %7, amortisman %4 hasılat → net yatırım %3 hasılat; reel büyüme %6,1 → s2c ≈ 0,061/0,03 ≈ 2
    assert s2c == pytest.approx(2.0, rel=0.1) and "net yatırım" in why
    assert report.inputs_from_analysis(a).sales_to_capital == pytest.approx(s2c)
    assert report.inputs_from_analysis(a, sales_to_capital=3.0).sales_to_capital == 3.0


def test_file_into_names_by_detected_period(tmp_path, gen):
    from kapsam.data.statements import file_into
    src = tmp_path / "indirilen_rapor (3).xlsx"
    _kap_workbook(src, pd.Period("2025Q3"), gen)
    out = file_into(src, "demo", tmp_path / "kap")
    assert out.name == "DEMO_2025_9.xlsx" and out.exists()
    assert list(pipeline.discover(tmp_path / "kap")) == ["DEMO"]
