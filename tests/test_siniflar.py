import numpy as np
import pandas as pd

from kapsam import siniflar


def row(**kw):
    base = dict(tur="sanayi", rapor_sayisi=5, fk_ttm=8.0, pd_dd=1.2, piyasa_degeri_mn_tl=10000.0, ozkaynak_karliligi_yillik=0.25,
                net_kar_ana_ttm_mn=1250.0, isletme_na_ttm_mn=1500.0, capex_ttm_mn=-400.0, serbest_nakit_ttm_mn=1100.0,
                nakit_donusumu=1.2, faaliyet_disi_pay=0.9, net_borc_mn=-200.0, net_borc_favok=-0.1, reel_hasilat_9a=0.05,
                parasal_kazanc_net_kar_ytd=-0.1, parasal_kazanc_olmadan_zarar=False, sektor="X", ad="A", son_ceyrek="2026Q3", guven="yüksek", potansiyel=0.3, deger=130.0, fiyat=100.0, **{"not": ""})
    base.update(kw)
    return base


def test_clean_cheap_company_is_kademeli():
    df = siniflar.build(pd.DataFrame({"A": row(), "B": row(fk_ttm=12.0)}).T)
    assert df.at["A", "sinif"] == "Kademeli Al" and df.at["A", "bayraklar"] == ""


def test_loss_and_monetary_dependence():
    df = siniflar.build(pd.DataFrame({"L": row(net_kar_ana_ttm_mn=-5.0, fk_ttm=np.nan),
                                      "P": row(parasal_kazanc_olmadan_zarar=True), "Q": row(parasal_kazanc_net_kar_ytd=0.4)}).T)
    assert df.at["L", "sinif"] == "Uzak Dur" and "ZARAR" in df.at["L", "bayraklar"]
    assert df.at["P", "sinif"] == "Uzak Dur"
    assert df.at["Q", "sinif"] == "Seçici İzle" and "PARASAL" in df.at["Q", "bayraklar"]


def test_cash_and_non_operating_profit():
    df = siniflar.build(pd.DataFrame({"R": row(isletme_na_ttm_mn=-100.0, serbest_nakit_ttm_mn=-500.0),
                                      "Y": row(nakit_donusumu=0.1, faaliyet_disi_pay=4.0, reel_hasilat_9a=-0.2)}).T)
    assert df.at["R", "sinif"] == "Temkinli İzle" and "NAKIT-" in df.at["R", "bayraklar"] and "SERBEST" not in df.at["R", "bayraklar"]
    assert df.at["Y", "sinif"] == "Temkinli İzle" and set(df.at["Y", "bayraklar"].split()) == {"NAKIT", "FDISI", "KUCULME"}


def test_missing_data_and_page():
    df = siniflar.build(pd.DataFrame({"M": row(isletme_na_ttm_mn=np.nan), "A": row()}).T)
    assert df.at["M", "sinif"] == "Veri Eksik"
    html = siniflar.page(df, "2026-11-21T12:00")
    assert "lvl al" in html and "lvl sat" in html and "yatırım tavsiyesi değildir" in html and "noindex" in html


def test_model_portfolio_caps():
    rows = {f"B{i}": row(sektor="Banka", oynaklik_yillik=0.2 + i / 100) for i in range(5)}
    rows.update({f"S{i}": row(sektor=f"S{i}", oynaklik_yillik=0.3 + i / 10) for i in range(6)})
    df = siniflar.build(pd.DataFrame(rows).T)
    mp = siniflar.model_portfolio(df)
    assert abs(mp["agirlik"].sum() + mp.attrs["nakit"] - 1) < 1e-9
    assert mp["agirlik"].max() <= 0.15 + 1e-9
    assert mp.groupby("sektor")["agirlik"].sum().max() <= 0.30 + 1e-9
    assert "Model portföy" in siniflar.page(df, "2026-11-22T00:00")


def test_azaltma_and_changes():
    from kapsam import deger
    assert deger.azaltma_orani("SAT", "ZARAR", 0.1) == 1.0
    assert deger.azaltma_orani("TUT", "PARASAL", 0.1) == 0.0
    assert deger.azaltma_orani("AZALT", "NAKIT-", 0.0) == 0.5
    assert deger.azaltma_orani("AZALT", "PARASAL KUCULME SERBEST FDISI", -0.5) == 0.25 + 0.2 + 0.15
    h = pd.DataFrame({"tarih": ["2026-11-20", "2026-11-20", "2026-11-21", "2026-11-21"], "kod": ["A", "B", "A", "B"],
                      "seviye": ["AL", "SAT", "TUT", "SAT"]})
    c = deger.changes(h)
    assert len(c) == 1 and c.iloc[0]["kod"] == "A" and c.iloc[0]["onceki"] == "AL" and c.iloc[0]["yeni"] == "TUT"
    assert "lvl al" in deger.changes_section(c)


def test_ina_blocks_al_and_explains():
    df = siniflar.build(pd.DataFrame({"A": row(), "D": row(potansiyel=-0.10, deger=90.0), "X": row(potansiyel=-0.5, deger=50.0)}).T)
    assert df.at["A", "seviye"] == "AL" and "Neden AL" in df.at["A", "gerekce"]
    assert df.at["D", "seviye"] == "TUT" and "AL eşiğinin" in df.at["D", "gerekce"]
    assert df.at["X", "seviye"] == "TUT" and "INA-" in df.at["X", "bayraklar"]


def test_public_quality_page_has_no_levels():
    df = siniflar.build(pd.DataFrame({"A": row(), "B": row(nakit_donusumu=0.1)}).T)
    h = siniflar.kalite_page(df, "2026-11-22T00:00")
    assert "Zayıf nakit dönüşümü" in h and "Bayrak yok" in h
    for w in ("lvl al", "Kademeli", "AZALT", "Model portföy", "12 ay hedef"):
        assert w not in h


def test_v2_rules():
    rows = {"B1": row(sektor="Bankacılık"), "B2": row(sektor="Bankacılık"), "S1": row(sektor="Sigorta"), "S2": row(sektor="Sigorta"),
            "V1": row(sektor="Varlık Yönetim"), "T1": row(sektor="Teknoloji"), "E1": row(sektor="Elektrik"),
            "L": row(sektor="Gıda", islem_hacmi_tl=5e6), "K": row(sektor="Kimya", karantina="2026-11-22")}
    df = siniflar.build(pd.DataFrame(rows).T)
    assert df.at["L", "seviye"] == "TUT" and "likidite" in df.at["L", "gerekce"]
    assert df.at["K", "seviye"] == "TUT" and "veri yeni tamamlandı" in df.at["K", "gerekce"]
    mp = siniflar.model_portfolio(df)
    fin = mp[mp["ust_sektor"] == "Finans"]["agirlik"].sum()
    assert fin <= 0.35 + 1e-9 and mp["agirlik"].max() <= 0.15 + 1e-9
    assert abs(mp["agirlik"].sum() + mp.attrs["nakit"] - 1) < 1e-9
    assert siniflar.ust_sektor("Varlık Yönetim") == "Finans" and siniflar.ust_sektor("Sigorta") == "Finans"


def test_single_al_stays_capped():
    df = siniflar.build(pd.DataFrame({"A": row()}).T)
    mp = siniflar.model_portfolio(df)
    assert abs(mp["agirlik"].iloc[0] - 0.15) < 1e-9 and abs(mp.attrs["nakit"] - 0.85) < 1e-9
