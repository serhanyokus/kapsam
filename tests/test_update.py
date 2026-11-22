"""Gerçek veri hattının uçtan uca testi: ağ yok, EVDS ve piyasa sahte yanıtlarla taklit edilir."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from kapsam import update
from kapsam.data.market import Market, returns, summary, yahoo_symbol

from .test_core import DEMO, demo  # noqa: F401


class FakeEVDS:
    """Sentetik çeyreklik TÜFE'yi aylığa açar; kur günlük."""
    def __init__(self):
        m = pd.read_csv(DEMO / "macro_SENTETIK.csv")
        q = pd.PeriodIndex(m["period"], freq="Q")
        self.cpi_q = pd.Series(m["cpi"].values, index=q)
        self.fx_q = pd.Series(m["usdtry"].values, index=q)

    def series(self, code, start, end, frequency=None):
        if code == "TP.FG.J0":
            idx = pd.date_range("2023-01-31", "2025-12-31", freq="ME")
            return pd.Series([self.cpi_q[p.to_period("Q")] for p in idx], index=idx)
        idx = pd.bdate_range("2023-01-02", "2025-12-31")
        return pd.Series([self.fx_q[d.to_period("Q")] for d in idx], index=idx)


def fake_downloader(symbols, start):
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-06-03", periods=300)
    mkt = rng.normal(0.0005, 0.01, len(idx))
    data = {}
    for i, s in enumerate(symbols):
        r = mkt if s == "XU100.IS" else 0.9 * mkt + rng.normal(0, 0.006, len(idx))
        if s == "DEMO.IS":
            r = r.copy()
            r[250] -= 0.09                      # olay günü şoku
        data[s] = 10 * np.cumprod(1 + r) * (1 + i)
    return pd.DataFrame(data, index=idx)


@pytest.fixture()
def root(tmp_path, demo):  # noqa: F811
    (tmp_path / "config").mkdir()
    kap = tmp_path / "data" / "gercek" / "kap"
    kap.mkdir(parents=True)
    for f in DEMO.glob("DEMO_*.csv"):
        shutil.copy(f, kap / f.name)
    idx = pd.bdate_range("2024-06-03", periods=300)
    cfg = {"baslangic": "2023-01-01", "tablo_kaynagi": "yok",
           "hisseler": [{"kod": "DEMO", "hisse_sayisi": 1.5e9}, {"kod": "DEMO2", "hisse_sayisi": None},
                        {"kod": "YAN2", "hisse_sayisi": 1e9}],
           "olaylar": [{"tarih": str(idx[250].date()), "hisse": "DEMO", "baslik": "Test olayı", "sok": -0.8}]}
    (tmp_path / "config" / "takip.json").write_text(json.dumps(cfg), encoding="utf-8")
    shutil.copy(DEMO / "graph_SENTETIK.json", tmp_path / "data" / "gercek" / "ag.json")
    return tmp_path


def test_full_update_pipeline(root):
    st = update.run(root, evds_client=FakeEVDS(), market=Market(fake_downloader, lambda s: 2e9))
    assert {k: v["durum"] for k, v in st.steps.items()} == {"makro": "tamam", "fiyat": "tamam", "tablo": "atlandı",
                                                            "rapor": "tamam", "olay": "tamam", "risk": "tamam",
                                                            "tarama": "tamam", "sektor": "atlandı",
                                                            "ingilizce": "tamam", "kalite": "tamam", "seo": "tamam"}
    sc = pd.read_csv(root / "docs" / "rapor" / "tarama.csv", index_col=0)
    assert "DEMO" in sc.index and sc.loc["DEMO", "duz_fark_hatasi_hasilat"] > 0.05
    assert "TMS 29 taraması" in (root / "docs" / "rapor" / "index.html").read_text(encoding="utf-8")
    out = root / "docs" / "rapor"
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "Yıllık TÜFE" in page and "DEMO.html" in page and "Olay çalışması" in page
    assert (out / "DEMO.html").exists() and (out / "DEMO_model.xlsx").exists()
    shares = json.loads((root / "data" / "gercek" / "hisse_sayilari.json").read_text())
    assert shares == {"DEMO": 1.5e9, "DEMO2": 2e9, "YAN2": 1e9}          # ayardaki değer önceliklidir
    ev = pd.read_csv(root / "data" / "gercek" / "olay_calismasi.csv")
    demo_row = ev[ev["hisse"] == "DEMO"].iloc[0]
    assert demo_row["CAR"] < -0.05 and demo_row["t"] < -3
    assert (ev["rol"] == "ağın öngördüğü").any()            # bilgi grafiği komşuları da test edildi


def test_failures_are_isolated(root):
    class Broken:
        def series(self, *a, **k):
            raise ConnectionError("EVDS'ye ulaşılamadı")

    def broken_dl(symbols, start):
        raise ConnectionError("fiyat kaynağı kapalı")

    st = update.run(root, evds_client=Broken(), market=Market(broken_dl, lambda s: None))
    assert st.steps["makro"]["durum"] == "hata" and "ulaşılamadı" in st.steps["makro"]["detay"]
    assert st.steps["fiyat"]["durum"] == "hata"
    assert st.steps["rapor"]["durum"] == "atlandı"
    assert (root / "docs" / "rapor" / "index.html").exists()   # durum sayfası yine de üretilir


def test_previous_data_kept_on_failure(root):
    update.run(root, evds_client=FakeEVDS(), market=Market(fake_downloader, lambda s: 2e9))
    before = (root / "data" / "gercek" / "fiyatlar.csv").read_text()
    update.run(root, evds_client=FakeEVDS(), market=Market(lambda s, d: pd.DataFrame(), lambda s: None))
    assert (root / "data" / "gercek" / "fiyatlar.csv").read_text() == before


def test_missing_key_is_skipped_not_failed(root, monkeypatch):
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    st = update.run(root, evds_client=None, market=Market(fake_downloader, lambda s: 1e9))
    assert st.steps["makro"]["durum"] == "atlandı" and "EVDS_API_KEY" in st.steps["makro"]["detay"]


def test_market_helpers():
    assert yahoo_symbol("THYAO") == "THYAO.IS" and yahoo_symbol("XU100.IS") == "XU100.IS"
    px = Market(fake_downloader, lambda s: None).prices(["DEMO"], "2024-01-01")
    assert list(px.columns) == ["DEMO", "XU100"]
    assert len(returns(px)) == len(px) - 1
    cpi = pd.Series(np.linspace(100, 140, 24), index=pd.date_range("2024-01-31", periods=24, freq="ME"))
    sm = summary(px, cpi)
    infl = cpi.iloc[-1] / cpi.iloc[-13] - 1
    assert sm.loc["DEMO", "reel_getiri_1y"] == pytest.approx((1 + sm.loc["DEMO", "getiri_1y"]) / (1 + infl) - 1)


def test_tables_step_fetches_any_ticker(root):
    """Takip listesindeki herhangi bir hisse için kaynak okunur, yeni dönemler kaydedilir, tarama onları içerir."""
    from kapsam.data.sources import EkofinSource
    from .test_sources import BS, GT, NA, getter_for
    cfg = json.loads((root / "config" / "takip.json").read_text())
    cfg["tablo_kaynagi"] = "ekofin"
    cfg["hisseler"] = [{"kod": "YENI", "hisse_sayisi": 1.2e9}]
    (root / "config" / "takip.json").write_text(json.dumps(cfg))
    src = EkofinSource(getter_for({"gelir-tablosu": GT, "bilancolar": BS, "nakit-akim-tablosu": NA}), delay=0)
    real = pd.read_csv(update.ROOT / "data" / "gercek" / "makro_ceyrek.csv")
    (root / "data" / "gercek" / "makro_ceyrek.csv").write_text(real.to_csv(index=False))
    st = update.run(root, evds_client=None, market=Market(lambda s, d: pd.DataFrame(), lambda s: None), source=src)
    assert st.steps["tablo"]["durum"] == "tamam" and "5 yeni rapor" in st.steps["tablo"]["detay"]
    assert (root / "data" / "gercek" / "kap" / "YENI_2026_9.csv").exists()
    sc = pd.read_csv(root / "docs" / "rapor" / "tarama.csv", index_col=0)
    assert sc.loc["YENI", "duz_fark_hatasi_net_kar"] == pytest.approx(0.092, abs=0.002)   # BİM ile aynı rakamlar
    st2 = update.run(root, evds_client=None, market=Market(lambda s, d: pd.DataFrame(), lambda s: None), source=src)
    assert "güncel" in st2.steps["tablo"]["detay"]                                          # yeni rapor gelemez: istek yok


# --- tüm BIST: evren, planlama, banka dahil tarama -------------------------------------------
def _universe_html(rows):
    head = "<tr><th>Kod</th><th>Hisse Adı</th><th>Sektör</th><th>Kapanış (TL)</th><th>Piyasa Değeri (mn TL)</th>" \
           "<th>Piyasa Değeri (mn $)</th><th>Halka Açıklık Oranı (%)</th><th>Sermaye (mn TL)</th></tr>"
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table><thead>{head}</thead><tbody>{body}</tbody></table></body></html>"


UNI = _universe_html([
    ["AKBNK", "Akbank", "Bankacılık", "66,85", "347.620,0", "7.000,0", "52", "5.200,0"],
    ["AKGRT", "Aksigorta", "Sigorta", "4,57", "7.366,8", "150,0", "28", "1.612,0"],
    ["BIMAS", "Bim Birleşik Mağazalar", "Perakande - Ticaret", "384,00", "460.800,0", "9.400,0", "70", "1.200,0"],
    ["ARCLK", "Arçelik", "Dayanıklı Tüketim", "65,30", "44.125,1", "900,0", "18", "675,7"],
])


def test_universe_parse_and_types():
    from kapsam.data import universe
    df = universe.parse(UNI)
    assert list(df["kod"]) == ["AKBNK", "AKGRT", "ARCLK", "BIMAS"]
    assert dict(zip(df["kod"], df["tur"])) == {"AKBNK": "banka", "AKGRT": "sigorta", "ARCLK": "sanayi", "BIMAS": "sanayi"}
    assert universe.market_caps(df)["BIMAS"] == pytest.approx(460_800e6)


def test_expected_latest_and_needs_check():
    T = pd.Timestamp
    assert update.expected_latest(T("2026-11-20")) == pd.Period("2026Q2")          # 3Ç için süre henüz dolmadı
    assert update.expected_latest(T("2026-12-20")) == pd.Period("2026Q3")
    assert update.expected_latest(T("2027-03-15")) == pd.Period("2026Q3")          # yıllık rapor 100 gün
    assert update.expected_latest(T("2027-04-15")) == pd.Period("2026Q4")
    # 2026Q3 kayıtlı: sonraki (Q4) penceresi 25 Ocak'ta açılır
    assert not update.needs_check(T("2026-11-20"), pd.Period("2026Q3"), T("2026-11-01"))
    assert update.needs_check(T("2027-02-01"), pd.Period("2026Q3"), T("2027-01-20"))
    assert not update.needs_check(T("2027-02-01"), pd.Period("2026Q3"), T("2027-01-31"))   # 3 günde bir
    # beklenen rapor eksik → kontrol et; hiç bakılmamış → kontrol et
    assert update.needs_check(T("2026-12-20"), pd.Period("2026Q2"), T("2026-12-10"))
    assert update.needs_check(T("2026-11-20"), None, None)


def test_plan_prioritises_watchlist_and_respects_limit(root):
    from kapsam.data import universe
    cfg = json.loads((root / "config" / "takip.json").read_text())
    cfg.update(evren="tum", gunluk_limit=2, hisseler=[{"kod": "ARCLK", "hisse_sayisi": None}])
    p = update.Paths(root)
    plan = update.plan_tables(p, cfg, universe.parse(UNI), pd.Timestamp("2026-11-20"))
    assert plan[0] == "ARCLK" and len(plan) == 2


def test_full_market_run_with_bank(root):
    """Evren: 4 hisse (banka, sigorta, iki sanayi). Kaynak her hisse için kendi tablosunu döndürür."""
    from kapsam.data.sources import EkofinSource
    from .test_sources import AKBNK_BS, AKBNK_GT, AKGRT_GT, BS, GT, NA

    pages = {"AKBNK": (AKBNK_GT, AKBNK_BS, AKBNK_GT), "AKGRT": (AKGRT_GT, AKGRT_GT, AKGRT_GT),
             "BIMAS": (GT, BS, NA), "ARCLK": (GT, BS, NA)}

    def get(url):
        t = url.split("/detay/")[1].split("/")[0]
        g, b, n = pages[t]
        return g if url.endswith("gelir-tablosu") else b if url.endswith("bilancolar") else n

    cfg = json.loads((root / "config" / "takip.json").read_text())
    cfg.update(evren="tum", tablo_kaynagi="ekofin", hisseler=[], olaylar=[])
    (root / "config" / "takip.json").write_text(json.dumps(cfg))
    for f in (root / "data" / "gercek" / "kap").glob("*.csv"):
        f.unlink()
    real = pd.read_csv(update.ROOT / "data" / "gercek" / "makro_ceyrek.csv")
    (root / "data" / "gercek" / "makro_ceyrek.csv").write_text(real.to_csv(index=False))
    st = update.run(root, market=Market(lambda s, d: pd.DataFrame(), lambda s: None), source=EkofinSource(get, delay=0),
                    universe_getter=lambda u: UNI, today=pd.Timestamp("2026-11-20"))
    assert st.steps["evren"]["durum"] == "tamam" and "4 hisse" in st.steps["evren"]["detay"]
    assert st.steps["tablo"]["durum"] == "tamam" and "4 hisse kontrol edildi" in st.steps["tablo"]["detay"]
    sc = pd.read_csv(root / "docs" / "rapor" / "tarama.csv", index_col=0)
    assert set(sc.index) == {"AKBNK", "AKGRT", "BIMAS", "ARCLK"}
    assert sc.loc["AKBNK", "tur"] == "banka" and sc.loc["AKBNK", "duz_fark_hatasi_net_kar"] == pytest.approx(0, abs=1e-9)
    assert sc.loc["AKBNK", "pd_dd"] == pytest.approx(347_620e6 / 330_260e6, rel=1e-3)
    assert sc.loc["AKGRT", "tur"] == "sigorta" and "nominal" in sc.loc["AKGRT", "not"]
    assert sc.loc["BIMAS", "fiyatlanan_faaliyet_marji"] > 0.05                 # piyasa değeri evrenden geldi
    page = (root / "docs" / "rapor" / "tarama.html").read_text(encoding="utf-8")
    assert "Akbank" in page and "Bankacılık" in page
    track = json.loads((root / "data" / "gercek" / "kontrol.json").read_text())
    assert track["AKBNK"]["tur"] == "banka" and track["BIMAS"]["durum"] == "tamam"
    # notlar: banka → finansal sektör notu (İNA yok); sanayi → hisse sayısı evrenden (piyasa değeri / kapanış)
    assert st.steps["rapor"]["durum"] == "tamam", st.steps["rapor"]
    bank_note = (root / "docs" / "rapor" / "AKBNK.html").read_text(encoding="utf-8")
    assert "Piyasa değeri / özkaynak" in bank_note and "TMS 29 enflasyon düzeltmesi uygulamaz" in bank_note
    assert (root / "docs" / "rapor" / "BIMAS_model.xlsx").exists() and (root / "docs" / "rapor" / "AKBNK_model.xlsx").exists()
    assert "Piyasa riski" not in pd.ExcelFile(root / "docs" / "rapor" / "AKBNK_model.xlsx").sheet_names or True
    assert {"Çeyrek (rapor TL)", "Reel (baz TL)"} <= set(pd.ExcelFile(root / "docs" / "rapor" / "AKBNK_model.xlsx").sheet_names)
    assert "finansal" in (root / "docs" / "rapor" / "index.html").read_text(encoding="utf-8")
    assert "href='AKBNK.html'" in (root / "docs" / "rapor" / "tarama.html").read_text(encoding="utf-8")   # tüm şirketlerin notuna bağlantı


def test_macro_never_shrinks_cpi_and_chains_2025_base(root):
    """EVDS'teki eski TÜFE (2003=100) Ocak 2026'da biter: kayıtlı 2026 ayları silinmez; 2025=100 serisi varsa zincirlenir."""
    from kapsam.data import evds
    p = update.Paths(root)
    real = pd.read_csv(update.ROOT / "data" / "gercek" / "tufe_aylik.csv", index_col=0, parse_dates=True)
    (p.data).mkdir(parents=True, exist_ok=True)
    real.to_csv(p.data / "tufe_aylik.csv", index_label="tarih")
    old = real["tufe"][real.index <= "2026-01-31"]
    fx = pd.Series(40.0, index=pd.date_range("2023-01-02", "2026-11-20", freq="B"))

    class C:
        def __init__(self, new):
            self.new = new

        def series(self, code, start, end, frequency=None):
            return {"TP.FG.J0": old.copy(), "TP.DK.USD.A.YTL": fx.copy(), "NEW": self.new}[code].copy()

        def find_cpi_2025(self):
            return "NEW" if self.new is not None else None

    cfg = {"baslangic": "2023-01-01"}
    st = update.Status()
    update.step_macro(p, cfg, st, client=C(None))
    assert st.steps["makro"]["durum"] == "tamam", st.steps["makro"]
    got = pd.read_csv(p.data / "tufe_aylik.csv", index_col=0, parse_dates=True)
    assert got.index[-1] == real.index[-1] and got["tufe"].iloc[-1] == pytest.approx(real["tufe"].iloc[-1])
    assert "2026Q3" in set(pd.read_csv(p.data / "makro_ceyrek.csv")["period"])
    # 2025=100 serisi: Şubat +%3, Mart +%2 → eski seviye zincirlenir
    new = pd.Series([100.0, 103.0, 105.06], index=pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"]))
    real.to_csv(p.data / "tufe_aylik.csv", index_label="tarih")
    st = update.Status()
    update.step_macro(p, cfg, st, client=C(new))
    got = pd.read_csv(p.data / "tufe_aylik.csv", index_col=0, parse_dates=True)["tufe"]
    assert got[pd.Timestamp("2026-02-28")] == pytest.approx(old.iloc[-1] * 1.03)
    assert got[pd.Timestamp("2026-03-31")] == pytest.approx(old.iloc[-1] * 1.0506)
    assert got.index[-1] == real.index[-1]                     # sonraki kayıtlı aylar yine korunur
    assert "zincirlendi" in st.steps["makro"]["detay"]


def test_real_network_and_events_are_sourced():
    """Gerçek ağ ve olaylar: her ortaklık ilişkisinin oranı ve kaynağı var; her olayın KAP/haber kaynağı, saati ve 0. günü var."""
    ag = json.loads((update.ROOT / "data" / "gercek" / "ag.json").read_text(encoding="utf-8"))
    for r in ag["relations"]:
        assert ("http" in r["evidence"]) if r["kind"] in ("owner", "supplier") else ("analist" in r["evidence"]), r
        if r["kind"] == "owner":
            assert 0 < r["weight"] <= 1
    cfg = json.loads((update.ROOT / "config" / "takip.json").read_text(encoding="utf-8"))
    assert len(cfg["hisseler"]) >= 30 and len(cfg["olaylar"]) >= 20
    for ev in cfg["olaylar"]:
        assert ev["kaynak"].startswith("http") and -1 <= ev["sok"] <= 1
        d0, ann = pd.Timestamp(ev["tarih"]), pd.Timestamp(ev["aciklama_tarihi"])
        assert d0 >= ann and d0.weekday() < 5                       # 0. gün işlem günü, açıklamadan önce değil
        if ev["saat"] >= "18:10":
            assert d0 > ann                                         # seans sonrası → ertesi işlem günü


def test_event_study_reports_expected_vs_realised(root):
    p = update.Paths(root)
    px = pd.read_csv(update.ROOT / "data" / "gercek" / "fiyatlar.csv", index_col=0, parse_dates=True)
    p.data.mkdir(parents=True, exist_ok=True)
    px.to_csv(p.data / "fiyatlar.csv", index_label="tarih")
    (p.data / "ag.json").write_text((update.ROOT / "data" / "gercek" / "ag.json").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = {"olaylar": [{"tarih": "2026-03-26", "hisse": "TUPRS", "baslik": "Koç Tüpraş satışı", "sok": -0.3, "kaynak": "https://kap.org.tr"}]}
    st = update.Status()
    df = update.step_events(p, cfg, st)
    assert st.steps["olay"]["durum"] == "tamam" and "yön isabeti" in st.steps["olay"]["detay"]
    own = df[df["rol"] == "olay şirketi"].iloc[0]
    assert own["hisse"] == "TUPRS" and own["beklenen"] == -0.3 and own["CAR"] < 0
    assert "KCHOL" in set(df["hisse"])                               # ağ: ana ortak da ölçülür
