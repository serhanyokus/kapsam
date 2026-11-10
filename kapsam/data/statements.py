"""KAP finansal tablolarını içe aktarma ve standart hesap planına eşleme.

KAP'ta her finansal rapor sayfasından tablolar Excel olarak indirilebilir. Bu modül,
satırları kalem ("Hasılat", "Brüt Kar (Zarar)" ...), sütunları dönem olan bir tabloyu
okur ve kalemleri KAPSAM standart hesap kodlarına eşler.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..textutil import norm, parse_tr_number

# Standart kod -> KAP/TFRS taksonomisinde görülen etiket varyantları
ACCOUNT_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["Hasılat", "Satış Gelirleri", "Net Satışlar"],
    "cogs": ["Satışların Maliyeti", "Satışların Maliyeti (-)"],
    "gross_profit": ["Brüt Kar (Zarar)", "Brüt Kâr", "Ticari Faaliyetlerden Brüt Kar (Zarar)"],
    "operating_profit": ["Esas Faaliyet Karı (Zararı)", "Esas Faaliyet Kârı"],
    "net_monetary_gain": [
        "Net Parasal Pozisyon Kazançları (Kayıpları)",
        "Parasal Kazanç (Kayıp)",
        "Net Parasal Pozisyon Kazancı",
    ],
    "pretax_profit": ["Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)", "Vergi Öncesi Kar (Zarar)"],
    "net_income": ["Dönem Karı (Zararı)", "Net Dönem Karı (Zararı)", "Dönem Net Karı"],
    "net_income_parent": ["Ana Ortaklık Payları"],
    "depreciation": ["Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "Amortisman ve İtfa Payları"],
    "cash": ["Nakit ve Nakit Benzerleri"],
    "total_assets": ["Toplam Varlıklar", "TOPLAM VARLIKLAR"],
    "total_liabilities_equity": ["Toplam Kaynaklar", "TOPLAM KAYNAKLAR"],
    "total_equity": ["Toplam Özkaynaklar", "Özkaynaklar"],
    "short_term_debt": ["Kısa Vadeli Borçlanmalar"],
    "current_portion_lt_debt": ["Uzun Vadeli Borçlanmaların Kısa Vadeli Kısımları"],
    "long_term_debt": ["Uzun Vadeli Borçlanmalar"],
}

_LOOKUP = {norm(label): code for code, labels in ACCOUNT_SYNONYMS.items() for label in labels}


def map_label(label: str) -> str | None:
    """Bir KAP kalem etiketini standart koda eşler; eşleşme yoksa None."""
    key = norm(label)
    if key in _LOOKUP:
        return _LOOKUP[key]
    # baştaki numaralandırmayı ("1.", "A)") atıp tekrar dene
    stripped = key.split(" ", 1)[1] if key[:1].isdigit() and " " in key else key
    return _LOOKUP.get(stripped)


@dataclass
class Statement:
    """Tek bir KAP raporundan (örn. 2025/9 aylık) okunan tablolar.

    values: index=standart kod, columns=dönem sonu (pd.Period, çeyrek), değerler TL.
    report_date: Raporun ait olduğu dönem sonu. TMS 29 gereği TÜM sütunlar
    bu tarihin satın alma gücüyle ifade edilmiştir.
    cumulative: Gelir tablosu kalemleri yıl başından itibaren kümülatif mi?
    """

    ticker: str
    report_date: pd.Period
    values: pd.DataFrame
    cumulative: bool = True
    source: str = ""
    unmapped: list[str] = field(default_factory=list)


def from_frame(df: pd.DataFrame, ticker: str, report_date: str, source: str = "", cumulative: bool = True) -> Statement:
    """İlk sütunu kalem adı, diğer sütunları dönem ('2025Q3', '2025/9', '30.09.2025') olan tabloyu okur."""
    label_col = df.columns[0]
    rows, unmapped = {}, []
    for _, row in df.iterrows():
        code = map_label(str(row[label_col]))
        if code is None:
            unmapped.append(str(row[label_col]))
            continue
        if code in rows:  # ilk eşleşen satırı (ana toplam) koru
            continue
        rows[code] = {_to_period(c): parse_tr_number(row[c]) for c in df.columns[1:]}
    values = pd.DataFrame(rows).T
    values = values[sorted(values.columns)]
    return Statement(ticker, _to_period(report_date), values, cumulative, source, unmapped)


def load_file(path: str | Path, ticker: str, report_date: str, cumulative: bool = True) -> Statement:
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    return from_frame(df, ticker, report_date, source=str(path), cumulative=cumulative)


def _to_period(label) -> pd.Period:
    s = str(label).strip()
    if "Q" in s.upper():
        return pd.Period(s.upper(), freq="Q")
    if "/" in s:  # KAP gösterimi: 2025/9 → 2025Q3
        y, m = s.split("/")[:2]
        return pd.Period(year=int(y), quarter=(int(m) - 1) // 3 + 1, freq="Q")
    if "." in s:  # 30.09.2025
        d, m, y = s.split(".")[:3]
        return pd.Period(year=int(y), quarter=(int(m) - 1) // 3 + 1, freq="Q")
    return pd.Period(s, freq="Q")
