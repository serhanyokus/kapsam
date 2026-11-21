"""Uçtan uca demo: python -m kapsam.cli [--data data/demo]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from . import graph as kg
from . import models as md
from . import pipeline, report, valuation
from .ai.classifier import classify
from .data.statements import load_file
from .normalize import tms29
from .thesis import Rule, Thesis
from .validate import accounting_checks


def load_demo(folder: Path):
    macro = pd.read_csv(folder / "macro_SENTETIK.csv")
    macro.index = pd.PeriodIndex(macro["period"], freq="Q")
    reports = []
    for f in sorted(folder.glob("DEMO_*.csv")):
        _, y, m = f.stem.split("_")
        reports.append(load_file(f, "DEMO", f"{y}/{m}"))
    return reports, macro["cpi"], macro["usdtry"]


def pct(x):
    return f"{x*100:6.1f}%"


DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "demo"


def _macro(args):
    if args.evds:
        start, end = args.evds
        return pipeline.load_macro_evds(start, end)
    path = Path(args.macro) if args.macro else Path(args.data) / "macro_SENTETIK.csv"
    return pipeline.load_macro_csv(path)


def cmd_report(args):
    """Tek şirket: HTML araştırma notu + formüllü Excel modeli."""
    cpi, fx = _macro(args)
    reps = pipeline.load_company(args.data, args.ticker)
    a = pipeline.analyze(args.ticker, reps, cpi, fx, args.tax)
    over = {k: v for k, v in dict(real_wacc=args.wacc, growth_high=args.growth, ebit_margin=args.margin,
                                   sales_to_capital=args.s2c, shares=args.shares).items() if v is not None}
    inp = report.inputs_from_analysis(a, **over)
    mcap = args.price * inp.shares
    th = Thesis(args.ticker, "Marj genişlemesi + reel büyüme", [
        Rule("gross_margin", "up", 0.0, 2, "Brüt marj önceki çeyreğe göre artıyor"),
        Rule("revenue_real_yoy", ">", 0.03, 1, "Reel yıllık büyüme > %3"),
        Rule("monetary_gain_share", "<", 0.5, 1, "Kârın yarısından azı parasal kazanç"),
    ]).evaluate(a.metrics)
    disc = []
    dfile = Path(args.data) / "disclosures_SENTETIK.json"
    if args.disclosures or dfile.exists():
        items = json.loads(Path(args.disclosures or dfile).read_text(encoding="utf-8"))
        for d in items:
            c = classify(d["metin"], market_cap_try=mcap, usdtry=float(fx.iloc[-1]))
            disc.append({"baslik": d["baslik"], "kategori": c.category, "yon": c.sentiment, "onem": c.importance})
    network = None
    gfile = Path(args.data) / "graph_SENTETIK.json"
    if gfile.exists():
        g, events, _ = kg.load_with_disclosures(gfile)
        if args.ticker in g.g:
            network = report.network_section(g, args.ticker, events)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    synthetic = Path(args.data).resolve() == DEMO_DIR or (not args.evds and "SENTETIK" in str(args.macro or "macro_SENTETIK"))
    (out / f"{args.ticker}_arastirma_notu.html").write_text(
        report.html_note(a, inp, mcap, th, disc, synthetic=synthetic, network=network), encoding="utf-8")
    report.excel_model(a, inp, mcap, out / f"{args.ticker}_model.xlsx")
    res = valuation.dcf(inp)
    print(f"{args.ticker}: hisse başı değer {res['per_share']:.2f} (fiyat {args.price:.2f}), "
          f"piyasanın fiyatladığı reel büyüme {valuation.implied_growth(mcap + inp.net_debt, inp):.1%}")
    print(f"Çıktılar → {out}")


def cmd_compare(args):
    cpi, fx = _macro(args)
    tickers = args.tickers or sorted(pipeline.discover(args.data))
    tab = pipeline.compare([pipeline.analyze(t, pipeline.load_company(args.data, t), cpi, fx) for t in tickers])
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 140):
        print(tab)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        tab.to_csv(args.out)
        print(f"→ {args.out}")


def cmd_graph(args):
    """İlişki ağı: olay etkisi, benzer şirketler, araştırma önceliği ve model değerlendirmesi."""
    path = Path(args.graph) if args.graph else Path(args.data) / "graph_SENTETIK.json"
    g, events, found = kg.load_with_disclosures(path)
    print(f"{len(g.g.nodes)} şirket, {len(g.relations())} ilişki ({len(found)} tanesi KAP metninden çıkarıldı)")
    for r in found:
        print(f"  + {r.source} → {r.target} [{r.kind}, {r.weight:g}]  kanıt: {r.evidence[:70]}")
    if args.event:
        t, shock = args.event[0], float(args.event[1])
        print(f"\nOlay: {t} ({shock:+.2f}) → etkilenen şirketler")
        for i in g.propagate(t, shock)[: args.top]:
            print(f"  {i.ticker:6s} {i.score:+.3f}  {i.explanation}")
    if args.similar:
        print(f"\n{args.similar} için benzer şirketler (rol benzerliği):")
        for t, v in g.similar(args.similar, args.top).items():
            print(f"  {t:6s} {v:.2f}")
    if args.watchlist:
        print("\nAraştırma önceliği (yatırım önerisi değildir):")
        q = kg.research_queue(g, events, args.watchlist)
        for t, row in q.iterrows():
            print(f"  {t:6s} {row.oncelik:.2f}  {row.neden[:110]}")
    if any(e.truth for e in events):
        print("\nModel değerlendirmesi (sentetik vakalar, k=5):")
        with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 140):
            print(kg.evaluate([kg.DirectOnly(), kg.SectorOnly(), md.PersonalizedPageRank(), md.TransE(), kg.Propagation()],
                              g, events, k=5))
        print("\nFark anlamlı mı? (eşleştirilmiş bootstrap, nDCG@5, %95 güven aralığı)")
        for b in [kg.SectorOnly(), md.PersonalizedPageRank()]:
            r = md.paired_bootstrap(kg.Propagation(), b, g, events)
            verdict = "anlamlı" if r["GA_alt"] > 0 else "anlamlı değil"
            print(f"  KAPSAM − {b.name}: {r['fark']:+.3f}  [{r['GA_alt']:+.3f}, {r['GA_üst']:+.3f}]  → {verdict} ({r['olay_sayısı']} olay)")


def _real_context():
    from .update import Paths
    p = Paths()
    cpi, fx = pipeline.load_macro_csv(p.data / "makro_ceyrek.csv")
    px = pd.read_csv(p.data / "fiyatlar.csv", index_col=0, parse_dates=True) if (p.data / "fiyatlar.csv").exists() else None
    prices = {t: float(px[t].dropna().iloc[-1]) for t in px.columns if px[t].notna().any()} if px is not None else {}
    shares = json.loads((p.data / "hisse_sayilari.json").read_text()) if (p.data / "hisse_sayilari.json").exists() else {}
    return p, cpi, fx, prices, shares


def cmd_analiz(args):
    """Herhangi bir BIST hissesi için uçtan uca analiz."""
    from .data.sources import EkofinSource, UnsupportedFormat, store
    p, cpi, fx, prices, shares = _real_context()
    t = args.hisse.upper()
    if not args.cevrimdisi:
        try:
            f = EkofinSource().fetch(t)
            new = store(f, p.kap)
            print(f"{t}: {len(f.periods)} dönem okundu, {len(new)} yeni rapor kaydedildi")
            for w in f.warnings:
                print("  uyarı:", w)
        except UnsupportedFormat as e:
            print("Desteklenmiyor:", e)
            return None
        except Exception as e:  # noqa: BLE001
            print(f"{t}: kaynağa ulaşılamadı ({e}); kayıtlı dosyalarla devam")
    row = pipeline.screen(p.kap, cpi, fx, prices, shares, tickers=[t]).loc[t]
    print(row.to_string())
    price, sh = args.price or prices.get(t), args.shares or shares.get(t)
    evren = p.root / "config" / "bist_evren.csv"
    if evren.exists() and not (price and sh):
        from .data import universe
        u = universe.load(evren).set_index("kod")
        if t in u.index and pd.notna(u.at[t, "kapanis"]) and pd.notna(u.at[t, "piyasa_degeri_mn_tl"]):
            price = price or float(u.at[t, "kapanis"])
            sh = sh or float(u.at[t, "piyasa_degeri_mn_tl"]) * 1e6 / float(u.at[t, "kapanis"])
    a = pipeline.analyze(t, pipeline.load_company(p.kap, t), cpi, fx)
    p.out.mkdir(parents=True, exist_ok=True)
    if report.is_financial(a):
        (p.out / f"{t}.html").write_text(report.financial_note(a, price * sh if (price and sh) else None), encoding="utf-8")
        print(f"Finansal sektör notu (PD/DD, F/K, özkaynak kârlılığı) → {p.out / (t + '.html')}")
        return row
    if not (price and sh):
        print("Not ve Excel için --price ve --shares verin (ya da takip listesine ekleyip 'guncelle' çalıştırın).")
        return row
    inp = report.inputs_from_analysis(a, shares=sh, growth_high=args.growth, real_wacc=args.wacc)
    mcap = price * sh
    p.out.mkdir(parents=True, exist_ok=True)
    (p.out / f"{t}.html").write_text(report.html_note(a, inp, mcap), encoding="utf-8")
    report.excel_model(a, inp, mcap, p.out / f"{t}_model.xlsx")
    print(f"Fiyatlanan kalıcı faaliyet marjı: {valuation.implied_margin(mcap + inp.net_debt, inp):.1%}  → {p.out / (t + '.html')}")
    return row


def cmd_tarama(args):
    p, cpi, fx, prices, shares = _real_context()
    sc = pipeline.screen(p.kap, cpi, fx, prices, shares)
    cols = ["son_ceyrek", "duz_fark_hatasi_net_kar", "duz_fark_hatasi_hasilat", "parasal_kazanc_net_kar_ytd",
            "raporlanan_net_marj", "temel_net_marj", "fiyatlanan_faaliyet_marji", "not"]
    with pd.option_context("display.width", 200, "display.max_colwidth", 60):
        print(sc[[c for c in cols if c in sc]].to_string(float_format=lambda v: f"{v:.3f}"))
    out = Path(args.out) if args.out else p.out / "tarama.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    sc.to_csv(out)
    print(f"→ {out}")
    return sc


def main(argv=None):
    ap = argparse.ArgumentParser(description="KAPSAM: TMS 29 farkındalıklı hisse araştırma asistanı")
    ap.add_argument("--data", default=str(DEMO_DIR), help="KAP dosyalarının klasörü (HISSE_YYYY_A.csv|xlsx)")
    ap.add_argument("--macro", help="period,cpi,usdtry sütunlu CSV")
    ap.add_argument("--evds", nargs=2, metavar=("BASLANGIC", "BITIS"), help="EVDS'den çek: GG-AA-YYYY GG-AA-YYYY")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("report", help="HTML araştırma notu + Excel modeli")
    r.add_argument("--ticker", default="DEMO")
    r.add_argument("--price", type=float, default=11.0, help="Hisse fiyatı (TL)")
    r.add_argument("--shares", type=float, default=1_500_000_000)
    r.add_argument("--wacc", type=float, help="Reel AOSM (ör. 0.10)")
    r.add_argument("--growth", type=float, help="İlk dönem reel büyüme")
    r.add_argument("--margin", type=float, help="Hedef faaliyet marjı")
    r.add_argument("--s2c", type=float, help="Satış / yatırılan sermaye")
    r.add_argument("--tax", type=float, default=0.0, help="Parasal kazanç vergi varsayımı")
    r.add_argument("--disclosures", help="Bildirim JSON dosyası")
    r.add_argument("--out", default="cikti")
    c = sub.add_parser("compare", help="Şirketler arası karşılaştırma")
    c.add_argument("tickers", nargs="*")
    c.add_argument("--out")
    gp = sub.add_parser("graph", help="İlişki ağı, etki yayılımı, benzer şirket, araştırma önceliği")
    gp.add_argument("--graph", help="Grafik JSON dosyası")
    gp.add_argument("--event", nargs=2, metavar=("HISSE", "SOK"), help="Ör. OTO1 -0.8")
    gp.add_argument("--similar", metavar="HISSE")
    gp.add_argument("--watchlist", nargs="*")
    gp.add_argument("--top", type=int, default=8)
    ke = sub.add_parser("kap-ekle", help="İndirilen KAP dosyalarını doğru adla data/gercek/kap klasörüne ekle")
    ke.add_argument("dosyalar", nargs="+")
    ke.add_argument("--hisse", required=True)
    an = sub.add_parser("analiz", help="Herhangi bir hisse: tabloları çek, TMS 29 analizi, not ve Excel")
    an.add_argument("hisse")
    an.add_argument("--price", type=float, help="Fiyat (yoksa data/gercek/fiyatlar.csv)")
    an.add_argument("--shares", type=float, help="Hisse sayısı (yoksa data/gercek/hisse_sayilari.json)")
    an.add_argument("--growth", type=float, default=0.03)
    an.add_argument("--wacc", type=float, default=0.10)
    an.add_argument("--cevrimdisi", action="store_true", help="Kaynağa bağlanma, yalnızca kayıtlı dosyaları kullan")
    tr = sub.add_parser("tarama", help="Kayıtlı tüm şirketler için TMS 29 taraması")
    tr.add_argument("--out", default=None)
    sub.add_parser("risk", help="Tüm hisseler için risk tablosu, korelasyon ve kovaryans matrisleri (kayıtlı fiyatlardan)")
    sub.add_parser("guncelle", help="Gerçek veriyi güncelle (EVDS, fiyatlar, KAP dosyaları) ve durum sayfasını üret")
    args = ap.parse_args(argv)
    if args.cmd == "analiz":
        return cmd_analiz(args)
    if args.cmd == "tarama":
        return cmd_tarama(args)
    if args.cmd == "risk":
        from . import update as up
        p, st_ = up.Paths(), up.Status()
        cfg = up.load_config(p)
        evren = p.root / "config" / "bist_evren.csv"
        tab = up.step_risk(p, cfg, st_, pd.read_csv(evren) if evren.exists() else None, pd.Timestamp("2000-01-07"))
        print(st_.steps["risk"]["detay"], "→", p.out / "risk" / "index.html")
        return tab
    if args.cmd == "kap-ekle":
        from .data.statements import file_into
        from .update import Paths
        for f in args.dosyalar:
            print(f"{f} → {file_into(f, args.hisse, Paths().kap)}")
        return None
    if args.cmd == "guncelle":
        from . import update
        st = update.run()
        for k, v in st.steps.items():
            print(f"{k:8s} {v['durum']:8s} {v['detay']}")
        print(f"→ {update.Paths().out / 'index.html'}")
        return st
    if args.cmd == "graph":
        return cmd_graph(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "compare":
        return cmd_compare(args)
    return demo(Path(args.data))


def demo(folder: Path):
    reports, cpi, fx = load_demo(folder)

    print("=" * 72)
    print("KAPSAM v0.9 — DEMO (SENTETİK VERİ: gerçek şirket/TÜFE değildir)")
    print("=" * 72)
    print(f"{len(reports)} KAP raporu okundu. Eşlenemeyen kalem: {sum(len(r.unmapped) for r in reports)}")

    q = tms29.quarterly_from_reports(reports, cpi)
    real = tms29.to_base(q, cpi)
    usd = tms29.to_usd(q, fx)
    m = tms29.metrics(real)

    print("\n[1] Sık yapılan hata: kümülatif rakamları düzeltmeden çıkarmak (Hasılat)")
    nv = tms29.naive_vs_correct(reports, cpi)
    for p, r in nv.iterrows():
        print(f"  {p}: düzeltmesiz={r.naive/1e6:9,.0f} mn  TMS29-tutarlı={r.correct/1e6:9,.0f} mn  hata={pct(r.error_pct)}")

    print(f"\n[2] Reel (baz: {real.attrs['base']} TL) ve USD hasılat, çeyreklik")
    for p in real.columns:
        print(f"  {p}: reel={real.at['revenue', p]/1e6:9,.0f} mn TL   USD={usd.at['revenue', p]/1e6:7,.1f} mn $")

    print("\n[3] Raporlanan vs temel (parasal kazançtan arındırılmış) net kâr marjı")
    for p in m.columns:
        print(f"  {p}: net marj={pct(m.at['net_margin', p])}  temel marj={pct(m.at['core_net_margin', p])}  "
              f"parasal kazanç/net kâr={pct(m.at['monetary_gain_share', p])}")

    print("\n[4] Sayısal doğrulama")
    checks = accounting_checks(q)
    failed = [c for c in checks if not c.passed]
    print(f"  {len(checks)} kontrol, {len(failed)} başarısız")

    print("\n[5] Tez takibi")
    th = Thesis("DEMO", "Marj genişlemesi + reel büyüme", [
        Rule("gross_margin", "up", 0.0, 2, "Brüt marj önceki çeyreğe göre artıyor"),
        Rule("revenue_real_yoy", ">", 0.03, 1, "Reel yıllık büyüme > %3"),
        Rule("monetary_gain_share", "<", 0.5, 1, "Kârın yarısından azı parasal kazanç"),
    ])
    res = th.evaluate(m)
    print(f"  {res['donem']} durum: {res['durum']} (skor {res['skor']})")
    for r in res["kurallar"]:
        print(f"   - {r['kural']}: {'veri yok' if r['saglandi'] is None else ('✓' if r['saglandi'] else '✗')} ({r['deger']:.3f})")

    print("\n[6] KAP bildirim sınıflandırma (sentetik bildirimler)")
    mcap = 30_000_000_000
    for d in json.loads((folder / "disclosures_SENTETIK.json").read_text(encoding="utf-8")):
        c = classify(d["metin"], market_cap_try=mcap, usdtry=float(fx.iloc[-1]))
        yon = {1: "+", 0: "0", -1: "-"}[c.sentiment]
        print(f"  {d['id']} {d['baslik'][:28]:28s} → {c.category:18s} yön={yon} önem={c.importance:.2f}")
    print()


if __name__ == "__main__":
    main()
