"""KAPSAM analist panosu (Streamlit).  Çalıştır:  streamlit run app.py"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

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
    mode = st.radio("Veri kaynağı", ["Demo (sentetik)", "Kendi KAP dosyalarım + EVDS"])
    tax = st.slider("Parasal kazanç vergi varsayımı", 0.0, 0.3, 0.0, 0.05)

if mode.startswith("Demo"):
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

t1, t2, t3, t4 = st.tabs(["Normalize seriler", "Düzeltmesiz yöntem hatası", "Tez takibi", "KAP bildirimleri"])
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
