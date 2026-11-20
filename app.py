"""KAPSAM analist panosu (Streamlit).  Çalıştır:  streamlit run app.py"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import tempfile

from kapsam import graph as kg
from kapsam import models as md
from kapsam import pipeline, report, valuation
from kapsam.ai.classifier import classify
from kapsam.cli import load_demo
from kapsam.data.statements import load_file
from kapsam.normalize import tms29
from kapsam.thesis import Rule, Thesis
from kapsam.validate import accounting_checks

DEMO = Path(__file__).parent / "data" / "demo"
st.set_page_config(page_title="KAPSAM", layout="wide")
st.title("KAPSAM · TMS 29 farkındalıklı hisse araştırma asistanı")

with st.sidebar:
    REAL = Path(__file__).parent / "data" / "gercek"
    real_ready = (REAL / "makro_ceyrek.csv").exists() and bool(pipeline.discover(REAL / "kap")) if (REAL / "kap").exists() else False
    options = (["Gerçek veri (otomatik güncellenen)"] if real_ready else []) + ["Demo (sentetik)", "Kendi KAP dosyalarım + EVDS"]
    mode = st.radio("Veri kaynağı", options)
    tax = st.slider("Parasal kazanç vergi varsayımı", 0.0, 0.3, 0.0, 0.05)

TARAMA = Path(__file__).parent / "docs" / "rapor" / "tarama.csv"
if mode.startswith("Gerçek") and st.sidebar.radio("Görünüm", ["Tek hisse", "Tüm BIST tarama"]) == "Tüm BIST tarama":
    if not TARAMA.exists():
        st.info("Tarama henüz üretilmedi: `python -m kapsam.cli guncelle` çalıştırın (GitHub Actions her iş günü çalıştırır).")
        st.stop()
    sc = pd.read_csv(TARAMA, index_col=0)
    f1, f2, f3 = st.columns(3)
    turler = f1.multiselect("Tablo türü", sorted(sc["tur"].dropna().unique()) if "tur" in sc else [], default=None)
    sektor = f2.multiselect("Sektör", sorted(sc["sektor"].dropna().unique()) if "sektor" in sc else [])
    ara = f3.text_input("Kod / ad ara")
    v = sc
    if turler:
        v = v[v["tur"].isin(turler)]
    if sektor:
        v = v[v["sektor"].isin(sektor)]
    if ara:
        v = v[v.index.str.contains(ara.upper()) | v.get("ad", pd.Series("", index=v.index)).fillna("").str.contains(ara, case=False)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Taranan hisse", len(sc))
    k2.metric("TMS 29 uygulayan", int(sc["tms29"].fillna(False).astype(bool).sum()) if "tms29" in sc else 0)
    k3.metric("Parasal kazanç olmadan zararda", int(sc["parasal_kazanc_olmadan_zarar"].fillna(False).astype(bool).sum())
              if "parasal_kazanc_olmadan_zarar" in sc else 0)
    err = sc["duz_fark_hatasi_hasilat"].abs().median() if "duz_fark_hatasi_hasilat" in sc else float("nan")
    k4.metric("Düz fark hatası (medyan, hasılat)", "–" if pd.isna(err) else f"{err*100:.1f}%")
    st.dataframe(v, width="stretch")
    st.download_button("CSV indir", v.to_csv().encode("utf-8"), "kapsam_tarama.csv", "text/csv")
    st.caption("Banka ve sigorta şirketleri TMS 29 uygulamaz (BDDK/SEDDK); nominal modda analiz edilir. Kaynak: KAP finansal tablolar, İş Yatırım hisse listesi.")
    st.stop()

if mode.startswith("Gerçek"):
    cpi, fx = pipeline.load_macro_csv(REAL / "makro_ceyrek.csv")
    ticker = st.sidebar.selectbox("Hisse", sorted(pipeline.discover(REAL / "kap")))
    reports = pipeline.load_company(REAL / "kap", ticker)
    if tms29.statement_kind(reports) != "sanayi":
        import streamlit.components.v1 as components
        a = pipeline.analyze(ticker, reports, cpi, fx)
        st.info("Banka/sigorta tablo biçimi: TMS 29 uygulanmaz, İNA yerine PD/DD, F/K ve özkaynak kârlılığı gösterilir.")
        components.html(report.financial_note(a), height=1300, scrolling=True)
        st.stop()
    durum = REAL.parent.parent / "docs" / "rapor" / "durum.json"
    if durum.exists():
        st.caption(f"Veri güncellemesi: {json.loads(durum.read_text(encoding='utf-8'))['guncelleme']} (UTC) · Kaynak: TCMB EVDS, KAP")
elif mode.startswith("Demo"):
    st.warning("Demo modu SENTETİK veri kullanır: gerçek bir şirkete veya gerçek TÜFE'ye ait değildir.")
    reports, cpi, fx = load_demo(DEMO)
    ticker = "DEMO"
else:
    ticker = st.sidebar.text_input("Hisse kodu", "THYAO")
    files = st.sidebar.file_uploader("KAP tabloları (CSV/XLSX, her rapor ayrı dosya)", accept_multiple_files=True)
    dates = st.sidebar.text_input("Rapor dönemleri (dosya sırasıyla, ör. 2025/3,2025/6,2025/9)")
    start = st.sidebar.text_input("EVDS başlangıç (GG-AA-YYYY)", "01-01-2023")
    end = st.sidebar.text_input("EVDS bitiş", pd.Timestamp.today().strftime("%d-%m-%Y"))
    if not files or not dates:
        st.info("KAP'tan indirdiğiniz tabloları yükleyin ve EVDS_API_KEY ortam değişkenini tanımlayın.")
        st.stop()
    from kapsam.data.evds import EVDSClient
    macro = EVDSClient().quarterly_macro(start, end)
    cpi, fx = macro["cpi"], macro["usdtry"]
    reports = []
    for f, d in zip(files, [x.strip() for x in dates.split(",")]):
        tmp = Path(st.session_state.get("tmp", "/tmp")) / f.name
        tmp.write_bytes(f.getvalue())
        reports.append(load_file(tmp, ticker, d))

q = tms29.quarterly_from_reports(reports, cpi)
real = tms29.to_base(q, cpi)
usd = tms29.to_usd(q, fx)
m = tms29.metrics(real, tax)

c1, c2, c3, c4 = st.columns(4)
last = m.columns[-1]
c1.metric("Reel hasılat (yıllık)", f"{m.at['revenue_real_yoy', last]*100:.1f}%")
c2.metric("Brüt marj", f"{m.at['gross_margin', last]*100:.1f}%")
c3.metric("Raporlanan net marj", f"{m.at['net_margin', last]*100:.1f}%")
c4.metric("Temel net marj", f"{m.at['core_net_margin', last]*100:.1f}%",
          delta=f"{(m.at['core_net_margin', last]-m.at['net_margin', last])*100:.1f} puan")

t1, t2, t5, t6, t7, t3, t4 = st.tabs(["Normalize seriler", "Düzeltmesiz yöntem hatası", "Değerleme", "Karşılaştırma",
                                       "İlişki ağı", "Tez takibi", "KAP bildirimleri"])
with t1:
    view = st.selectbox("Görünüm", ["Reel TL", "USD", "Rapor TL'si (her çeyrek kendi tarihinde)"])
    df = {"Reel TL": real, "USD": usd}.get(view, q)
    st.line_chart(df.loc[["revenue", "gross_profit", "operating_profit"]].T.set_index(df.columns.astype(str)))
    st.dataframe((m.T.set_index(m.columns.astype(str))).style.format("{:.3f}"))
    checks = accounting_checks(q)
    st.caption(f"Sayısal doğrulama: {sum(c.passed for c in checks)}/{len(checks)} kontrol geçti")
with t2:
    nv = tms29.naive_vs_correct(reports, cpi)
    nv.index = nv.index.astype(str)
    st.write("Kümülatif rakamları TMS 29 düzeltmesi yapmadan çıkarmak çeyreklik hasılatı şu kadar saptırır:")
    st.bar_chart(nv["error_pct"] * 100)
    st.dataframe(nv.style.format({"naive": "{:,.0f}", "correct": "{:,.0f}", "error_pct": "{:.1%}"}))
with t3:
    th = Thesis(ticker, "Marj genişlemesi + reel büyüme", [
        Rule("gross_margin", "up", 0.0, 2, "Brüt marj artıyor"),
        Rule("revenue_real_yoy", ">", 0.03, 1, "Reel yıllık büyüme > %3"),
        Rule("monetary_gain_share", "<", 0.5, 1, "Kârın yarısından azı parasal kazanç"),
    ])
    res = th.evaluate(m)
    st.subheader(f"{res['tez']} → {res['durum']} (skor {res['skor']})")
    st.table(pd.DataFrame(res["kurallar"]))
with t4:
    if mode.startswith("Demo"):
        items = json.loads((DEMO / "disclosures_SENTETIK.json").read_text(encoding="utf-8"))
    else:
        items = [{"id": "1", "baslik": "Yapıştırılan bildirim", "metin": st.text_area("KAP bildirim metni")}]
    mcap = st.number_input("Piyasa değeri (TL)", value=30_000_000_000.0, step=1e9)
    for d in items:
        if not d["metin"]:
            continue
        c = classify(d["metin"], market_cap_try=mcap, usdtry=float(fx.iloc[-1]))
        with st.expander(f"{d['baslik']} · {c.category} · önem {c.importance:.2f} · yön {c.sentiment:+d}"):
            st.write(d["metin"])
            st.caption(f"Kanıt: {', '.join(c.evidence)} · Tutarlar: {c.amounts}")

with t5:
    a = pipeline.Analysis(ticker, reports, q, real, usd, m, tms29.naive_vs_correct(reports, cpi), accounting_checks(q))
    base_inp = report.inputs_from_analysis(a)
    st.caption(f"Tüm tutarlar {real.attrs['base']} TL'si (reel). Nominal AOSM'yi beklenen enflasyonla reele çevirebilirsiniz.")
    c1, c2, c3 = st.columns(3)
    with c1:
        nom = st.number_input("Nominal AOSM (TL)", value=0.40, step=0.01, format="%.2f")
        inf = st.number_input("Beklenen enflasyon", value=0.27, step=0.01, format="%.2f")
        wacc = valuation.real_rate(nom, inf)
        st.metric("Reel AOSM (Fisher)", f"{wacc:.1%}")
    with c2:
        g = st.slider("İlk 5 yıl reel büyüme", -0.05, 0.25, float(round(base_inp.growth_high, 3)), 0.005)
        gt = st.slider("Sürekli reel büyüme", 0.0, 0.04, 0.02, 0.005)
        mg = st.slider("Hedef faaliyet marjı", 0.0, 0.40, float(round(base_inp.ebit_margin, 3)), 0.005)
    with c3:
        s2c = st.number_input("Satış / yatırılan sermaye", value=2.0, step=0.1)
        shares = st.number_input("Hisse sayısı", value=1_500_000_000.0, step=1e8, format="%.0f")
        price = st.number_input("Hisse fiyatı (TL)", value=11.0, step=0.1)
    inp = report.inputs_from_analysis(a, real_wacc=wacc, growth_high=g, growth_terminal=gt, ebit_margin=mg,
                                      sales_to_capital=s2c, shares=shares)
    try:
        res = valuation.dcf(inp)
        mcap = price * shares
        ig = valuation.implied_growth(mcap + inp.net_debt, inp)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Hisse başı değer", f"{res['per_share']:.2f}", f"{res['per_share']/price-1:+.1%} potansiyel")
        k2.metric("Firma değeri (mn)", f"{res['ev']/1e6:,.0f}")
        k3.metric("Piyasanın fiyatladığı reel büyüme", f"{ig:.1%}")
        k4.metric("Sürekli değer payı", f"{res['tv_share']:.0%}")
        st.dataframe(res["projection"].style.format({"buyume": "{:.1%}", "marj": "{:.1%}", "iskonto": "{:.3f}"} |
                                                     {c: "{:,.0f}" for c in ["hasilat", "ebit", "nopat", "yeniden_yatirim", "fcff", "bd_fcff"]}))
        sens = valuation.sensitivity(inp, [wacc - 0.01, wacc, wacc + 0.01], [g - 0.02, g, g + 0.02])
        st.write("Duyarlılık (hisse başı değer): satırlar reel AOSM, sütunlar reel büyüme")
        st.dataframe(sens.rename(index=lambda x: f"{x:.1%}", columns=lambda x: f"{x:.1%}").style.format("{:.2f}"))
        with tempfile.TemporaryDirectory() as td:
            xl = report.excel_model(a, inp, mcap, f"{td}/model.xlsx").read_bytes()
        note = report.html_note(a, inp, mcap, synthetic=mode.startswith("Demo"))
        d1, d2 = st.columns(2)
        d1.download_button("Araştırma notunu indir (HTML)", note, f"{ticker}_arastirma_notu.html", "text/html")
        d2.download_button("Formüllü Excel modelini indir", xl, f"{ticker}_model.xlsx")
    except ValueError as err:
        st.error(str(err))
with t6:
    if mode.startswith("Demo"):
        an = [pipeline.analyze(t, pipeline.load_company(DEMO, t), cpi, fx, tax) for t in sorted(pipeline.discover(DEMO))]
        tab = pipeline.compare(an)
        st.write("Raporlanan net marjlar farklı görünse de parasal etki ayıklanınca şirketler benzer kârlılıkta olabilir:")
        st.caption(f"Son çeyrek: {tab.loc['Son çeyrek'].iloc[0]}")
        st.dataframe(tab.drop("Son çeyrek").astype(float).style.format("{:.1%}"))
    else:
        st.info("Karşılaştırma için klasördeki birden çok şirketi komut satırından çalıştırın: python -m kapsam.cli --data KLASOR compare")

with t7:
    real_graph = Path(__file__).parent / "data" / "gercek" / "ag.json"
    gfile = real_graph if (mode.startswith("Gerçek") and real_graph.exists()) else DEMO / "graph_SENTETIK.json"
    up = st.file_uploader("Kendi ilişki ağınız (JSON, isteğe bağlı)", type="json", key="graph_json")
    if up is not None:
        tmpg = Path(tempfile.gettempdir()) / "kapsam_graph.json"
        tmpg.write_bytes(up.getvalue())
        gfile = tmpg
    elif gfile.name == "graph_SENTETIK.json":
        st.warning("Sentetik ağ: şirketler, ilişkiler ve olaylar kurgudur. Gerçek ağ için data/gercek/ag.json ekleyin "
                   "(biçim: docs/kendi_modelin.md).")
    G, events, found = kg.load_with_disclosures(gfile)
    st.caption(f"{len(G.g.nodes)} şirket · {len(G.relations())} ilişki · {len(found)} tanesi KAP metninden kanıtıyla çıkarıldı")
    titles = {f"{e.title} ({e.ticker}, şok {e.shock:+.1f})": e for e in events}
    c1, c2 = st.columns([1, 1])
    with c1:
        choice = st.selectbox("Olay", list(titles) + ["Özel olay gir"])
        if choice == "Özel olay gir":
            tk = st.selectbox("Şirket", sorted(G.g.nodes))
            sh = st.slider("Şok (- olumsuz, + olumlu)", -1.0, 1.0, -0.8, 0.1)
            ev = kg.Event(tk, sh, f"{tk} özel olay")
        else:
            ev = titles[choice]
        hops = st.slider("En fazla adım", 1, 4, 3)
        imp = G.propagate(ev.ticker, ev.shock, max_hops=hops)
        st.dataframe(pd.DataFrame([{"Şirket": i.ticker, "Etki": round(i.score, 3), "Adım": i.hops, "Neden": i.explanation} for i in imp]),
                     hide_index=True)
    with c2:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 5))
        kg.draw(G, focus=ev.ticker, impacts=imp, ax=ax)
        st.pyplot(fig)
    st.subheader("Araştırma önceliği")
    wl = st.multiselect("Takip listesi", sorted(G.g.nodes), default=sorted(G.g.nodes)[:5])
    if wl:
        st.dataframe(kg.research_queue(G, events, wl), width="stretch")
    st.subheader("Benzer şirket")
    who = st.selectbox("Şirket seç", sorted(G.g.nodes), key="sim")
    st.dataframe(G.similar(who, 5).rename("Benzerlik").to_frame().style.format("{:.2f}"))
    if any(e.truth for e in events):
        st.subheader("Model değerlendirmesi")
        st.caption("Sentetik vakalarda, elle belirlenmiş 'gerçekten etkilenen şirketler' listesine göre. Gerçek veride doğrulama: olay çalışması (CAR).")
        st.dataframe(kg.evaluate([kg.DirectOnly(), kg.SectorOnly(), md.PersonalizedPageRank(), md.TransE(), kg.Propagation()],
                                 G, events, k=5).style.format("{:.2f}"))
        rows = []
        for b in [kg.SectorOnly(), md.PersonalizedPageRank(), md.TransE()]:
            r = md.paired_bootstrap(kg.Propagation(), b, G, events, n=2000)
            rows.append({"Karşılaştırma": f"KAPSAM − {b.name}", "nDCG@5 farkı": r["fark"], "%95 GA alt": r["GA_alt"],
                         "%95 GA üst": r["GA_üst"], "Sonuç": "anlamlı" if r["GA_alt"] > 0 else "anlamlı değil"})
        st.write("Fark anlamlı mı? (eşleştirilmiş bootstrap)")
        st.dataframe(pd.DataFrame(rows), hide_index=True)
