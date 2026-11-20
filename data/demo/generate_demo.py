"""SENTETİK demo verisi üretir (gerçek bir şirkete veya gerçek TÜFE'ye ait DEĞİLDİR).

Amaç: Motorun uçtan uca çalıştığını ve TMS 29 matematiğini doğru uyguladığını,
gerçek veriye ihtiyaç duymadan göstermek. Her rapor, KAP'tan indirilen tablolarla aynı
mantıkta üretilir: kümülatif gelir tablosu, tüm sütunlar rapor tarihinin TL'siyle.

Canlı kullanım için: KAP'tan tabloları indirip `kapsam.data.statements.load_file`
ile yükleyin, TÜFE/kur için EVDS_API_KEY tanımlayın.
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
TICKER = "DEMO"
QUARTERS = pd.period_range("2024Q1", "2025Q4", freq="Q")

# Sentetik çeyreklik enflasyon patikası (düşen enflasyon senaryosu) ve kur
q_infl = np.linspace(0.11, 0.06, len(QUARTERS) + 4)
cpi_all = 100 * np.cumprod(1 + q_infl)
all_q = pd.period_range("2023Q1", "2025Q4", freq="Q")
CPI = pd.Series(cpi_all, index=all_q)
USDTRY = pd.Series(np.linspace(18.5, 43.0, len(all_q)), index=all_q)

# Şirketin "gerçek" ekonomisi: sabit fiyatlarla %1,5 çeyreklik reel büyüme, sonra marj iyileşmesi
rng = np.random.default_rng(42)
real_rev = pd.Series(1_000_000_000 * (1.015 ** np.arange(len(all_q))), index=all_q)  # baz: 2023Q1 TL
gm = pd.Series(np.r_[np.full(8, 0.24), np.linspace(0.245, 0.29, 4)], index=all_q)
opex_ratio = 0.12
NET_MONETARY_LIAB_REAL = 600_000_000  # net parasal borç (2023Q1 TL) → parasal KAZANÇ üretir


# İkinci sentetik şirket (sektör karşılaştırması için): daha hızlı büyüyen, marjı daralan,
# net parasal VARLIK pozisyonu nedeniyle parasal KAYIP yazan bir şirket.
PROFILES = {
    "DEMO": dict(real_rev=real_rev, gm=gm, nml=NET_MONETARY_LIAB_REAL, assets=5_000_000_000),
    "DEMO2": dict(real_rev=pd.Series(600_000_000 * (1.03 ** np.arange(len(all_q))), index=all_q),
                  gm=pd.Series(np.linspace(0.34, 0.27, len(all_q)), index=all_q),
                  nml=-250_000_000, assets=2_500_000_000),
}


def nominal(p, ticker="DEMO"):
    """Çeyrek p'de gerçekleşen akışların, p dönem sonu TL'siyle değeri."""
    pr = PROFILES[ticker]
    f = CPI[p] / CPI[all_q[0]]
    rev = pr["real_rev"][p] * f
    cogs = -rev * (1 - pr["gm"][p])
    gp = rev + cogs
    op = gp - rev * opex_ratio
    nmg = pr["nml"] * f * (CPI[p] / CPI[p - 1] - 1) if p > all_q[0] else 0.0
    pretax = op - rev * 0.03 + nmg
    ni = pretax * 0.75
    return {"Hasılat": rev, "Satışların Maliyeti (-)": cogs, "Brüt Kar (Zarar)": gp,
            "Esas Faaliyet Karı (Zararı)": op, "Net Parasal Pozisyon Kazançları (Kayıpları)": nmg,
            "Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)": pretax, "Dönem Karı (Zararı)": ni}


def ytd(p, in_p, ticker="DEMO"):
    """p çeyreğine kadar yıl başından kümülatif, in_p tarihinin TL'siyle."""
    tot = {}
    for q in pd.period_range(pd.Period(year=p.year, quarter=1, freq="Q"), p, freq="Q"):
        for k, v in nominal(q, ticker).items():
            tot[k] = tot.get(k, 0.0) + v * CPI[in_p] / CPI[q]
    return tot


def balance(p, in_p, ticker="DEMO"):
    f = CPI[in_p] / CPI[all_q[0]]
    k = PROFILES[ticker]["assets"] / 5_000_000_000
    assets = PROFILES[ticker]["assets"] * f * (1.01 ** all_q.get_loc(p))
    cash = 400_000_000 * f * k * (2.5 if ticker == "DEMO2" else 1)
    st, lt = 900_000_000 * f * k, 700_000_000 * f * k
    equity = assets * 0.45
    return {"Nakit ve Nakit Benzerleri": cash, "Toplam Varlıklar": assets,
            "Kısa Vadeli Borçlanmalar": st, "Uzun Vadeli Borçlanmalar": lt,
            "Toplam Özkaynaklar": equity, "Toplam Kaynaklar": assets}


def fmt(v):
    s = f"{abs(v):,.0f}".replace(",", ".")
    return f"({s})" if v < 0 else s


def main():
    for ticker in PROFILES:
        for p in QUARTERS:
            cur = {**ytd(p, p, ticker), **balance(p, p, ticker)}
            prior = {**ytd(p - 4, p, ticker), **balance(p - 4, p, ticker)}
            df = pd.DataFrame({"Kalem": list(cur), f"{p.year}/{p.quarter*3}": [fmt(cur[k]) for k in cur],
                               f"{p.year-1}/{p.quarter*3}": [fmt(prior[k]) for k in cur]})
            df.to_csv(OUT / f"{ticker}_{p.year}_{p.quarter*3}.csv", index=False)
    pd.DataFrame({"period": CPI.index.astype(str), "cpi": CPI.values, "usdtry": USDTRY.values}).to_csv(OUT / "macro_SENTETIK.csv", index=False)
    print(f"{len(PROFILES)} şirket × {len(QUARTERS)} sentetik rapor üretildi → {OUT}")


if __name__ == "__main__":
    main()
