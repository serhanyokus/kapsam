import pandas as pd

from kapsam import kiyas


def test_groups_and_broker(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "takip.json").write_text('{"politika_faizi": 0.36, "enflasyon_beklentisi_12a": 0.24}', encoding="utf-8")
    (tmp_path / "config" / "kurum_konsensus.csv").write_text("kod,kurum_sayisi,medyan_hedef,kaynak,tarih\nAAA,5,150,x,2026-02-01\n", encoding="utf-8")
    sc = pd.DataFrame({"seviye": ["TUT", "TUT", "TUT", "SAT", "VERİ YOK"], "fiyat": [100, 100, 100, 100, 100],
                       "hedef_12a": [150, 130, 110, 200, 300], "guven": ["yüksek", "orta", "yüksek", "düşük", "yüksek"],
                       "bayraklar": [None] * 5}, index=["AAA", "BBB", "CCC", "DDD", "EEE"])
    d, es = kiyas.build(sc, tmp_path, 0.3, pd.Timestamp("2026-11-22"))
    assert list(d["grup"]) == ["Faizi geçiyor", "Enflasyonu geçiyor", "Enflasyonun altında", "Güven düşük", "Değer yok"]
    assert abs(d.loc["AAA", "kurum_getiri"] - 0.5) < 1e-9 and bool(d.loc["AAA", "kurum_eski"])
    assert d.loc["AAA", "uyum"] == "İkisi de olumlu"
    assert "Faizi geçiyor" in kiyas.section(d, es) and "AAA" in kiyas.summary_md(d, es)
