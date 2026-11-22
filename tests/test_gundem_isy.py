import pandas as pd

from kapsam import gundem
from kapsam.data import isyatirim, statements

SAMPLE = [{"itemCode": "3C", "value1": "151486106000", "value2": "88494252000"},
          {"itemCode": "3DF", "value1": "39308750000", "value2": "22530965000"},
          {"itemCode": "3HA", "value1": "2309538000", "value2": "1670370000"},
          {"itemCode": "3HAC", "value1": "-732993000", "value2": "-248997000"},
          {"itemCode": "3HB", "value1": "2975067000", "value2": "1643140000"},
          {"itemCode": "3HC", "value1": "-20295506000", "value2": "-12945154000"},
          {"itemCode": "3I", "value1": "24564856000", "value2": "12650324000"},
          {"itemCode": "3L", "value1": "26349554000", "value2": "14449834000"},
          {"itemCode": "3Z", "value1": "26470603000", "value2": "14439306000"},
          {"itemCode": "4C", "value1": "22998149000", "value2": "15206440000"},
          {"itemCode": "2N", "value1": "340068373000", "value2": "308524609000"},
          {"itemCode": "1AA", "value1": "31845162000", "value2": "39468926000"}]


def test_isyatirim_parse_and_write(tmp_path):
    pers = [pd.Period("2026Q3"), pd.Period("2026Q2")]
    d = isyatirim.parse(SAMPLE, pers)
    assert d[pers[0]]["Hasılat"] == 151486106000
    assert abs(d[pers[0]]["Net Parasal Pozisyon Kazançları (Kayıpları)"] - 1e9) < 1     # vergi öncesi kârdaki açıklanmayan fark
    assert "Net Parasal Pozisyon Kazançları (Kayıpları)" not in d[pers[1]]
    isyatirim.write("TEST", d, tmp_path)
    st = statements.load_file(tmp_path / "TEST_2026_9.csv", "TEST", "2026/9")
    assert st.values.loc["revenue"].iloc[0] == 151486106000 and st.values.loc["operating_cash_flow"].iloc[0] == 22998149000
    assert "TEST" in isyatirim.incomplete(tmp_path, ["TEST"])          # 4'ten az rapor


def test_gundem_score_and_erp():
    assert gundem.score("Şirket rekor kâr açıkladı") > 0 and gundem.score("Şirkete soruşturma, hisse sert düştü") < 0
    ind = pd.DataFrame({"son": {"^VIX": 30.0, "USDTRY=X": 50.0}, "ay": {"^VIX": 0.1, "USDTRY=X": 0.06}})
    adj, why = gundem.erp_adjustment(ind)
    assert abs(adj - 0.02) < 1e-12 and len(why) == 2
    html = gundem.page({"gostergeler": {"^VIX": {"ad": "VIX", "son": 30, "gun": 0.01, "ay": 0.1, "yil": 0.2, "tarih": "2026-11-20"}},
                        "erp_ek": 0.01, "erp_neden": ["x"], "makro_tr": [{"baslik": "Faiz", "link": "https://x", "tarih": "2026-11-20", "puan": 1}],
                        "makro_global": [], "sirket": {"ABC": {"haberler": [], "olumlu": 0, "olumsuz": 2, "bayrak": "HABER-"}}}, "2026-11-22T00:00")
    assert "Gündem" in html and "%7" in html and "ABC" in html


def test_haber_flag_in_levels():
    from kapsam import siniflar
    from tests.test_siniflar import row
    df = siniflar.build(pd.DataFrame({"A": row(), "B": row(haber_bayrak="HABER-", haber_ozet="son 14 gün 0 olumlu / 3 olumsuz başlık")}).T)
    assert df.at["A", "seviye"] == "AL" and df.at["B", "seviye"] == "TUT" and "HABER-" in df.at["B", "bayraklar"]
    assert "Gündem" in df.at["B", "gerekce"]


def test_isyatirim_financial_and_depth(tmp_path):
    pers = [pd.Period("2026Q3")]
    d = isyatirim.parse([{"itemCode": "2O", "value1": "28892000000"}, {"itemCode": "3Z", "value1": "4250000000"},
                         {"itemCode": "1Z", "value1": "581422000000"}], pers, fin=True)
    assert d[pers[0]]["Toplam Özkaynaklar"] == 28892000000 and d[pers[0]]["Dönem Karı (Zararı)"] == 4250000000
    for y, m in [(2025, 9), (2025, 12), (2026, 3), (2026, 6)]:
        pd.DataFrame({"Kalem": ["Hasılat", "Dönem Karı (Zararı)", "Toplam Özkaynaklar"], f"{y}/{m}": [1, 1, 1]}).to_csv(tmp_path / f"X_{y}_{m}.csv", index=False)
    pd.DataFrame({"Kalem": ["Hasılat", "Dönem Karı (Zararı)", "Toplam Özkaynaklar", "İşletme Faaliyetlerinden Nakit Akışları"],
                  "2026/9": [1, 1, 1, 1]}).to_csv(tmp_path / "X_2026_9.csv", index=False)
    assert "X" in isyatirim.incomplete(tmp_path, ["X"])            # eski raporlarda nakit akışı eksik
