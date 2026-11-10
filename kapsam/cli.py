"""Uçtan uca demo: python -m kapsam.cli [--data data/demo]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

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


def main(argv=None):
    ap = argparse.ArgumentParser(description="KAPSAM demo")
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[1] / "data" / "demo"))
    args = ap.parse_args(argv)
    folder = Path(args.data)
    reports, cpi, fx = load_demo(folder)

    print("=" * 72)
    print("KAPSAM v0.1 — DEMO (SENTETİK VERİ: gerçek şirket/TÜFE değildir)")
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
        print(f"   - {r['kural']}: {'✓' if r['saglandi'] else '✗'} ({r['deger']:.3f})")

    print("\n[6] KAP bildirim sınıflandırma (sentetik bildirimler)")
    mcap = 30_000_000_000
    for d in json.loads((folder / "disclosures_SENTETIK.json").read_text(encoding="utf-8")):
        c = classify(d["metin"], market_cap_try=mcap, usdtry=float(fx.iloc[-1]))
        yon = {1: "+", 0: "0", -1: "-"}[c.sentiment]
        print(f"  {d['id']} {d['baslik'][:28]:28s} → {c.category:18s} yön={yon} önem={c.importance:.2f}")
    print()


if __name__ == "__main__":
    main()
