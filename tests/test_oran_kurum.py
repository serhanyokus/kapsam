import json

import pandas as pd

from kapsam import kiyas, kurumlar, oranlar

UNI = pd.DataFrame({"kod": ["TUPRS", "HALKB", "SKYMD", "HDFGS", "KCHOL", "ASTOR"],
                    "ad": ["Tüpraş", "Halkbank", "Şeker Yatırım Menkul", "Hedef Girişim", "Koç Holding", "Astor Enerji"],
                    "kapanis": [300, 40, 10, 2, 180, 150]})


def test_parse_multi_broker_and_context():
    al = kurumlar.alias_map(UNI)
    txt = ("Tüpraş (TUPRS):\nTacirler Yatırım, Tüpraş için 481 TL hedef fiyat açıklayarak \"al\" tavsiyesini korudu. "
           "Şeker Yatırım, 395 TL hedef fiyat ve \"al\" tavsiyesini sürdürdü.\n"
           "Vakıf Yatırım, TUPRS için 510 TL hedef fiyat ve \"endeks üstü getiri\" tavsiyesi açıklarken İş Yatırım, ASTOR için 297,24 TL hedef fiyat açıkladı.\n"
           "Şeker Yatırım, Halkbank için hedef fiyatını 46,4 TL'den 52,3 TL'ye yükseltirken \"tut\" tavsiyesini korudu.")
    got = {(r["kod"], r["kurum"], r["hedef"], r["tavsiye"]) for r in kurumlar.parse(txt, set(UNI["kod"]), al)}
    assert ("TUPRS", "Şeker Yatırım", 395.0, "AL") in got
    assert ("ASTOR", "İş Yatırım", 297.24, "") in got
    assert ("HALKB", "Şeker Yatırım", 52.3, "TUT") in got
    assert not any(k in ("SKYMD", "HDFGS") for k, *_ in got)


def test_ozet_and_kiyas_merge(tmp_path):
    (tmp_path / "data" / "gercek").mkdir(parents=True)
    pd.DataFrame([
        {"tarih": "2026-11-10", "kod": "TUPRS", "kurum": "Tacirler Yatırım", "hedef": 450, "tavsiye": "AL", "cumle": "", "kaynak": ""},
        {"tarih": "2026-11-15", "kod": "TUPRS", "kurum": "Tacirler Yatırım", "hedef": 481, "tavsiye": "AL", "cumle": "", "kaynak": ""},
        {"tarih": "2026-11-12", "kod": "TUPRS", "kurum": "Gedik Yatırım", "hedef": 501, "tavsiye": "TUT", "cumle": "", "kaynak": ""},
        {"tarih": "2026-11-12", "kod": "TUPRS", "kurum": "X", "hedef": 5000, "tavsiye": "AL", "cumle": "", "kaynak": ""},
        {"tarih": "2025-01-01", "kod": "KCHOL", "kurum": "Eski", "hedef": 200, "tavsiye": "AL", "cumle": "", "kaynak": ""},
    ]).to_csv(tmp_path / "data" / "gercek" / "kurum_hedefleri.csv", index=False)
    o = kurumlar.ozet(tmp_path, {"TUPRS": 300}, pd.Timestamp("2026-11-22"))
    assert list(o.index) == ["TUPRS"] and o.loc["TUPRS", "kurum_sayisi"] == 2 and o.loc["TUPRS", "medyan_hedef"] == 491
    sc = pd.DataFrame({"seviye": ["TUT"], "fiyat": [300], "hedef_12a": [420], "guven": ["yüksek"], "bayraklar": [None]}, index=["TUPRS"])
    d, es = kiyas.build(sc, tmp_path, 0.3, pd.Timestamp("2026-11-22"))
    assert d.loc["TUPRS", "kurum_sayisi"] == 2 and abs(d.loc["TUPRS", "kurum_getiri"] - (491 / 300 - 1)) < 1e-9


class FakeEVDS:
    def _meta(self, path):
        if path.startswith("datagroups"):
            return [{"DATAGROUP_NAME": "Piyasa Katılımcıları Anketi", "DATAGROUP_CODE": "bie_pka"},
                    {"DATAGROUP_NAME": "TCMB Politika Faizi", "DATAGROUP_CODE": "bie_pf"}]
        if "bie_pka" in path:
            return [{"SERIE_NAME": "12 Ay Sonrası Yıllık TÜFE Beklentisi (%)", "SERIE_CODE": "TP.PKA.T12"}]
        return [{"SERIE_NAME": "Bir Hafta Vadeli Repo İhale Faiz Oranı", "SERIE_CODE": "TP.PF.R1H"}]

    def series(self, code, start, end):
        v = 23.4 if "PKA" in code else 36.0
        return pd.Series([v + 1, v], index=pd.to_datetime(["2026-10-01", "2026-11-01"]))


def test_oranlar_evds_then_news(tmp_path):
    o = oranlar.guncelle(tmp_path, client=FakeEVDS(), rss=lambda *a, **k: [])
    assert o["politika_faizi"]["deger"] == 0.36 and o["enflasyon_beklentisi_12a"]["kod"] == "TP.PKA.T12"
    v, t, src = oranlar.deger(tmp_path, "politika_faizi", pd.Timestamp("2026-11-22"))
    assert v == 0.36 and "EVDS" in src
    news = lambda q, **k: [{"baslik": "Merkez Bankası politika faizini yüzde 35'e indirdi", "tarih": "2026-12-10", "kaynak": "X"}] \
        if "politika" in q else [{"baslik": "12 ay sonrası enflasyon beklentisi yüzde 22,8 oldu", "tarih": "2026-12-12", "kaynak": "Y"}]
    o2 = oranlar.guncelle(tmp_path / "b", client=None, rss=news)
    assert o2["politika_faizi"]["deger"] == 0.35 and abs(o2["enflasyon_beklentisi_12a"]["deger"] - 0.228) < 1e-9


def test_table_page():
    h = ("<title>Tüpraş (TUPRS) Hisse Hedef Fiyat</title><table><tr><th>Aracı Kurum</th><th>Tarih</th><th>Hedef Fiyat TL</th><th>Tavsiye</th></tr>"
         "<tr><td>Ziraat Yatırım</td><td>11 Kasım 2026</td><td>490,00</td><td>Al</td></tr>"
         "<tr><td>Ortalama</td><td></td><td>476,22</td><td></td></tr></table>")
    r = kurumlar.tablolar(h, set(UNI["kod"]), kurumlar.alias_map(UNI))
    assert r == [{"kod": "TUPRS", "kurum": "Ziraat Yatırım", "hedef": 490.0, "tavsiye": "AL", "tarih": "2026-11-11",
                  "cumle": "Ziraat Yatırım | 11 Kasım 2026 | 490,00 | Al"}]
    assert kurumlar.parse("2026 yılında en yüksek hedef fiyat 510,00 TL (Vakıf Yatırım) oldu.", {"TUPRS"}, {"tupras": "TUPRS"}) == []
