"""Genel tablo kaynağı: ağ yok; kaynak sayfaların düzenini taklit eden HTML ile test edilir."""
import pandas as pd
import pytest

from kapsam import pipeline
from kapsam.data.sources import EkofinSource, UnsupportedFormat, clean_cell, parse_table, store

PER = ["2026-09", "2026-06", "2026-03", "2025-12", "2025-09"]


def html_table(head, rows):
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></body></html>"


GT = html_table(["Gelir Tablosu Kalemleri"] + PER, [
    ["Gelir Tablosu", "", "", "", "", ""],
    ["Ana Ortaklık Payları", "26.151.834.000%79", "15.766.410.961%103", "7.299.323.180%83", "23.162.794.369%-23", "14.598.567.000%-39"],
    ["Brüt Kar (Zarar)", "140.000.000.000%8", "91.000.000.000%10", "46.000.000.000%19", "174.000.000.000%17", "129.000.000.000%18"],
    ["Dönem Karı (Zararı)", "26.393.828.000%79", "15.935.681.752%106", "7.401.206.167%85", "23.291.024.407%-23", "14.746.548.000%-39"],
    ["Faaliyet Karı (Zararı)", "18.301.878.000%61", "8.497.926.000%154", "2.869.362.610%250", "19.823.603.279%130", "11.356.187.000%166"],
    ["Net Parasal Pozisyon Kazançları (Kayıpları)", "22.188.094.000%8", "18.622.024.061%32", "11.466.228.289%-6", "22.629.922.654%-36", "20.614.793.000%-30"],
    ["Satış Gelirleri", "720.477.782.000%8", "474.745.808.446%10", "240.481.999.116%10", "896.400.050.586%6", "665.220.543.000%5"],
    ["Satışların Maliyeti (-)", "-581.104.267.000%-8", "-384.156.319.499%-10", "-194.943.529.153%-8", "-723.044.707.800%-4", "-536.332.421.000%-2"],
    ["Ticari Faaliyetlerden Brüt Kar (Zarar)", "139.373.515.000%8", "90.589.488.947%10", "45.538.469.963%19", "173.355.342.786%17", "128.888.122.000%18"],
    ["Amortisman", "", "", "5.790.386.133%12", "", ""],
])
BS = html_table(["Bilanço Kalemleri"] + PER[1:] + ["2025-06"], [
    ["Nakit ve Nakit Benzerleri", "4.325.864.000%5", "5.329.422.473%1", "4.075.075.000%2", "4.401.935.831%3", "3.859.066.490%1"],
    ["Toplam Varlıklar", "428.574.350.000%1", "426.225.739.309%2", "398.122.648.000%1", "401.499.946.770%1", "390.329.295.336%1"],
    ["Kısa Vadeli Yükümlülükler", "", "", "", "", ""],
    ["Finansal Borçlar", "15.350.001.000%1", "15.133.602.599%1", "15.359.928.000%1", "13.798.120.059%1", "13.597.640.299%1"],
    ["Uzun Vadeli Yükümlülükler", "", "", "", "", ""],
    ["Finansal Borçlar", "47.242.509.000%1", "47.012.985.717%1", "46.728.128.000%1", "46.233.884.791%1", "47.781.096.893%1"],
    ["Özkaynaklar", "", "", "", "", ""],
    ["Toplam Özkaynaklar", "203.137.363.000%1", "204.170.107.252%1", "196.762.594.000%1", "188.658.529.448%1", "180.595.623.828%1"],
])
NA = html_table(["Nakit Akım Tablosu Kalemleri"] + PER, [
    ["Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "23.750.347.000", "15.909.256.384", "8.233.821.737", "33.113.996.275", "25.873.929.000"],
    ["Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları", "-18.607.969.000", "-12.377.563.040",
     "-5.421.943.608", "-26.457.901.566", "-19.951.081.000"],
])


def getter_for(pages):
    def get(url):
        for key, html in pages.items():
            if url.endswith(key):
                return html
        raise AssertionError(url)
    return get


@pytest.mark.parametrize("raw,val", [("720.477.782.000%8", 720477782000.0), ("-581.104.267.000%-8", -581104267000.0),
                                     ("", float("nan")), ("1.234,5%3", 1234.5)])
def test_clean_cell(raw, val):
    out = clean_cell(raw)
    assert (pd.isna(out) and pd.isna(val)) or out == pytest.approx(val)


def test_fetch_parses_three_pages_and_sections():
    src = EkofinSource(getter_for({"gelir-tablosu": GT, "bilancolar": BS, "nakit-akim-tablosu": NA}), delay=0)
    f = src.fetch("bimas")
    q = f.periods["2026/6"]
    assert f.ticker == "BIMAS" and not f.warnings
    assert q["revenue"] == 474_745_808_446 and q["gross_profit"] == 90_589_488_947   # "Ticari Faaliyetler..." tercih edildi
    assert q["short_term_debt"] == 15_350_001_000 and q["long_term_debt"] == 47_242_509_000   # bölümlere göre ayrıldı
    assert q["capex"] < 0 and "depreciation" in q
    assert "revenue" not in f.periods.get("2025/6", {})                                # yalnızca bilanço dönemi


def test_store_keeps_as_reported_history(tmp_path):
    src = EkofinSource(getter_for({"gelir-tablosu": GT, "bilancolar": BS, "nakit-akim-tablosu": NA}), delay=0)
    f = src.fetch("BIMAS")
    first = store(f, tmp_path)
    assert {p.name for p in first} == {"BIMAS_2026_9.csv", "BIMAS_2026_6.csv", "BIMAS_2026_3.csv", "BIMAS_2025_12.csv", "BIMAS_2025_9.csv"}
    (tmp_path / "BIMAS_2025_9.csv").write_text((tmp_path / "BIMAS_2025_9.csv").read_text() + "\n")   # eski dosya işaretle
    before = (tmp_path / "BIMAS_2025_9.csv").read_text()
    assert store(f, tmp_path) == []                                   # ikinci çalıştırma hiçbir şeyi ezmez
    assert (tmp_path / "BIMAS_2025_9.csv").read_text() == before
    reps = pipeline.load_company(tmp_path, "BIMAS")                   # yazılan dosyalar motor tarafından okunur
    assert len(reps) == 5 and all("revenue" in r.values.index for r in reps)


# Gerçek Akbank ve Aksigorta tablo düzeni (değerler 20.11.2026'da kaynaktan okunan rakamlar)
AKBNK_GT = html_table(["Gelir Tablosu Kalemleri"] + PER, [
    ["Gelir Tablosu", "", "", "", "", ""],
    ["FAİZ GELİRLERİ", "570.656.000.000%1", "368.213.000.000", "171.455.000.000", "654.700.844.000", "480.288.000.000"],
    ["FAİZ GİDERLERİ (-)", "-440.283.000.000", "-280.187.000.000", "-128.369.000.000", "-545.715.623.000", "-409.596.000.000"],
    ["NET FAİZ GELİRİ VEYA GİDERİ", "130.373.000.000", "88.026.000.000", "43.086.000.000", "108.985.221.000", "70.692.000.000"],
    ["NET ÜCRET VE KOMİSYON GELİRLERİ VEYA GİDERLERİ", "106.531.000.000", "69.098.000.000", "32.401.000.000", "120.971.683.000", "86.341.000.000"],
    ["SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ KARI (ZARARI)", "62.830.000.000", "46.955.000.000", "26.856.000.000", "76.749.116.000", "48.566.000.000"],
    ["DÖNEM NET KARI VEYA ZARARI", "45.933.000.000", "34.333.000.000", "19.143.000.000", "57.224.231.000", "38.908.000.000"],
    ["FAİZ GELİRLERİ", "", "", "", "", ""],
    ["Kredilerden Alınan Faizler", "1", "1", "1", "1", "1"],
    ["Beklenen Zarar Karşılıkları (-)", "-35.704.000.000", "-26.481.000.000", "-11.927.000.000", "-39.785.993.000", "-31.429.000.000"],
    ["Grubun Karı (Zararı)", "45.950.000.000", "34.350.000.000", "19.152.000.000", "57.254.821.000", "38.923.000.000"],
])
AKBNK_BS = html_table(["Bilanço Tablosu Kalemleri"] + PER, [
    ["KREDİLER (Net)", "2.579.977.000.000", "", "2.233.902.112.000", "2.126.627.000.000", "1.926.564.932.000"],
    ["VARLIKLAR TOPLAMI", "4.197.902.000.000", "4.012.479.000.000", "3.643.975.000.000", "3.558.950.000.000", "3.231.443.118.000"],
    ["Mevduat", "2.641.432.000.000", "2.511.089.000.000", "2.318.398.125.000", "2.173.421.000.000", "2.026.921.233.000"],
    ["ÖZKAYNAKLAR", "330.260.000.000", "", "302.574.628.000", "310.170.000.000", "277.390.463.000"],
    ["ÖZKAYNAKLAR", "999", "999", "999", "999", "999"],
])
AKGRT_GT = html_table(["Gelir Tablosu Kalemleri"] + PER, [
    ["I-TEKNİK BÖLÜM", "", "", "", "", ""],
    ["Brüt Yazılan Primler (+)", "32.607.367.177", "22.096.932.144", "11.693.047.117", "35.101.021.882", "23.625.367.466"],
    ["Yazılan Primler (Reasürör Payı Düşülmüş Olarak)", "14.823.688.637", "10.014.856.801", "4.891.292.948", "14.055.886.012", "8.809.393.663"],
    ["TEKNİK BÖLÜM DENGESİ - HAYAT DIŞI", "2.159.137.448", "1.123.705.077", "290.139.993", "3.271.632.423", "2.582.757.841"],
    ["Dönem Net Karı Veya Zararı", "1.893.551.980", "1.018.491.244", "268.169.185", "2.485.797.839", "2.034.770.000"],
])


def test_bank_format_parsed_in_nominal_mode(tmp_path):
    src = EkofinSource(getter_for({"gelir-tablosu": AKBNK_GT, "bilancolar": AKBNK_BS, "nakit-akim-tablosu": AKBNK_GT}), delay=0)
    f = src.fetch("AKBNK")
    assert f.kind == "banka" and not f.warnings
    q = f.periods["2026/9"]
    assert q["net_interest_income"] == 130_373_000_000 and q["net_fee_income"] == 106_531_000_000
    assert q["credit_provisions"] == -35_704_000_000 and q["net_income_parent"] == 45_950_000_000
    assert q["total_equity"] == 330_260_000_000          # ilk ÖZKAYNAKLAR satırı (ana blok)
    assert q["interest_income"] == 570_656_000_000       # ikinci "FAİZ GELİRLERİ" alt başlığı boş, ilk satır korunur
    store(f, tmp_path)
    from kapsam.normalize import tms29
    reps = pipeline.load_company(tmp_path, "AKBNK")
    assert tms29.statement_kind(reps) == "banka" and not tms29.applies_tms29(reps)
    cpi = pd.Series(range(100, 120), index=pd.period_range("2022Q1", periods=20, freq="Q"), dtype=float)
    qd = tms29.quarterly_from_reports(reps, cpi)
    assert qd.at["net_income", pd.Period("2026Q3")] == pytest.approx(45_933e6 - 34_333e6)   # düz fark: TMS 29 yok
    assert qd.attrs["restated"] is False


def test_insurer_format_parsed():
    f = EkofinSource(getter_for({"gelir-tablosu": AKGRT_GT, "bilancolar": AKGRT_GT, "nakit-akim-tablosu": AKGRT_GT}), delay=0).fetch("AKGRT")
    assert f.kind == "sigorta"
    assert f.periods["2026/9"]["gross_premiums"] == 32_607_367_177 and f.periods["2026/9"]["net_income"] == 1_893_551_980


def test_no_monetary_line_warns():
    gt = GT.replace("Net Parasal Pozisyon Kazançları (Kayıpları)", "Başka Bir Kalem")
    f = EkofinSource(getter_for({"gelir-tablosu": gt, "bilancolar": BS, "nakit-akim-tablosu": NA}), delay=0).fetch("THYAO")
    assert f.warnings and "TMS 29" in f.warnings[0]


def test_unknown_ticker_raises():
    empty = "<html><body><p>Bulunamadı</p></body></html>"
    with pytest.raises(ValueError, match="tablo bulunamadı"):
        EkofinSource(lambda u: empty, delay=0).fetch("XXXX")
