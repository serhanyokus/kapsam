"""KAP finansal tablolarını içe aktarma ve standart hesap planına eşleme.

KAP'ta her finansal rapor sayfasından tablolar Excel olarak indirilebilir. Bu modül,
satırları kalem ("Hasılat", "Brüt Kar (Zarar)" ...), sütunları dönem olan bir tabloyu
okur ve kalemleri KAPSAM standart hesap kodlarına eşler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..textutil import norm, parse_tr_number

# Standart kod -> KAP/TFRS taksonomisinde görülen etiket varyantları (Türkçe ve KAP İngilizce)
ACCOUNT_SYNONYMS: dict[str, list[str]] = {
    "revenue": ["Hasılat", "Satış Gelirleri", "Net Satışlar", "Revenue"],
    "cogs": ["Satışların Maliyeti", "Satışların Maliyeti (-)", "Cost of sales"],
    "gross_profit": ["Brüt Kar (Zarar)", "Brüt Kâr", "Ticari Faaliyetlerden Brüt Kar (Zarar)", "Gross Profit (Loss)",
                     "Gross profit (loss) from commercial operations"],
    "operating_profit": ["Esas Faaliyet Karı (Zararı)", "Esas Faaliyet Kârı", "Profit (loss) from operating activities"],
    "net_monetary_gain": [
        "Net Parasal Pozisyon Kazançları (Kayıpları)",
        "Parasal Kazanç (Kayıp)",
        "Net Parasal Pozisyon Kazancı",
        "Gains (losses) on net monetary position",
        "Monetary gain (loss)",
    ],
    "pretax_profit": ["Sürdürülen Faaliyetler Vergi Öncesi Karı (Zararı)", "Vergi Öncesi Kar (Zarar)",
                      "Profit (loss) from continuing operations before tax"],
    "net_income": ["Dönem Karı (Zararı)", "Net Dönem Karı (Zararı)", "Dönem Net Karı", "Profit (loss)"],
    "net_income_parent": ["Ana Ortaklık Payları", "Owners of parent"],
    "depreciation": ["Amortisman ve İtfa Gideri İle İlgili Düzeltmeler", "Amortisman ve İtfa Payları",
                     "Adjustments for depreciation and amortisation expense"],
    "capex": ["Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları",
              "Maddi Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları",
              "Purchase of property, plant, equipment and intangible assets",
              "Purchase of property, plant and equipment"],
    "operating_cash_flow": ["İşletme Faaliyetlerinden Nakit Akışları", "Cash flows from (used in) operating activities"],
    "cash": ["Nakit ve Nakit Benzerleri", "Cash and cash equivalents"],
    "total_assets": ["Toplam Varlıklar", "TOPLAM VARLIKLAR", "Total assets"],
    "total_liabilities_equity": ["Toplam Kaynaklar", "TOPLAM KAYNAKLAR", "Total liabilities and equity"],
    "total_equity": ["Toplam Özkaynaklar", "Özkaynaklar", "Total equity", "Özsermaye Toplamı", "ÖZKAYNAK", "Toplam Özsermaye"],
    "short_term_debt": ["Kısa Vadeli Borçlanmalar", "Current borrowings"],
    "current_portion_lt_debt": ["Uzun Vadeli Borçlanmaların Kısa Vadeli Kısımları",
                                "Current portion of non-current borrowings"],
    "long_term_debt": ["Uzun Vadeli Borçlanmalar", "Long-term borrowings", "Non-current borrowings"],
    # Bankacılık (BDDK biçimi)
    "interest_income": ["Faiz Gelirleri"], "interest_expense": ["Faiz Giderleri (-)"],
    "net_interest_income": ["Net Faiz Geliri", "Net Faiz Geliri veya Gideri"],
    "net_fee_income": ["Net Ücret ve Komisyon Gelirleri", "Net Ücret ve Komisyon Gelirleri veya Giderleri"],
    "operating_income": ["Faaliyet Brüt Kârı"], "credit_provisions": ["Beklenen Zarar Karşılıkları (-)"],
    "loans": ["Krediler (Net)"], "deposits": ["Mevduat"],
    # Sigorta (SEDDK biçimi)
    "gross_premiums": ["Brüt Yazılan Primler", "Brüt Yazılan Primler (+)"],
    "net_premiums": ["Net Yazılan Primler", "Yazılan Primler (Reasürör Payı Düşülmüş Olarak)"],
    "technical_result_nonlife": ["Teknik Bölüm Dengesi - Hayat Dışı"],
    "technical_result": ["Genel Teknik Bölüm Dengesi"],
}

_LOOKUP = {norm(label): code for code, labels in ACCOUNT_SYNONYMS.items() for label in labels}
_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})|(\d{4})-(\d{2})-(\d{2})")


def map_label(label: str) -> str | None:
    """Bir KAP kalem etiketini standart koda eşler; eşleşme yoksa None."""
    key = norm(label)
    if key in _LOOKUP:
        return _LOOKUP[key]
    # baştaki numaralandırmayı ("1.", "A)", "1.1") atıp tekrar dene
    stripped = re.sub(r"^([0-9]+ )+|^[a-z] ", "", key)
    return _LOOKUP.get(stripped)


@dataclass
class Statement:
    """Tek bir KAP raporundan (örn. 2025/9 aylık) okunan tablolar.

    values: index=standart kod, columns=dönem sonu (pd.Period, çeyrek), değerler TL.
    report_date: Raporun ait olduğu dönem sonu. TMS 29 gereği TÜM sütunlar
    bu tarihin satın alma gücüyle ifade edilmiştir.
    cumulative: Gelir tablosu kalemleri yıl başından itibaren kümülatif mi?
    quarterly_reported: KAP'taki "3 aylık" sütunları (varsa); çapraz doğrulama için.
    """

    ticker: str
    report_date: pd.Period
    values: pd.DataFrame
    cumulative: bool = True
    source: str = ""
    unmapped: list[str] = field(default_factory=list)
    quarterly_reported: pd.DataFrame = field(default_factory=pd.DataFrame)


def _dates(text: str) -> list[pd.Timestamp]:
    out = []
    for m in _DATE.finditer(str(text)):
        if m.group(1):
            out.append(pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        else:
            out.append(pd.Timestamp(int(m.group(4)), int(m.group(5)), int(m.group(6))))
    return out


def classify_header(h) -> tuple[pd.Period | None, str]:
    """Sütun başlığından (dönem, tür). tür: 'nokta' (bilanço / kümülatif), '3ay' veya 'yok'."""
    if isinstance(h, (pd.Timestamp, datetime)):
        t = pd.Timestamp(h)
        return pd.Period(t, freq="Q"), "nokta"
    s = str(h).strip()
    if not s or s.lower().startswith("unnamed") or "dipnot" in norm(s) or "note" in s.lower():
        return None, "yok"
    ds = _dates(s)
    if len(ds) >= 2:
        start, end = min(ds), max(ds)
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        kind = "3ay" if months <= 3 and start.month != 1 else "nokta"
        if "3 ayl" in norm(s) or "3 month" in s.lower():
            kind = "3ay"
        return pd.Period(end, freq="Q"), kind
    if len(ds) == 1:
        return pd.Period(ds[0], freq="Q"), "nokta"
    if re.fullmatch(r"\d{4}\s*/\s*\d{1,2}", s) or re.fullmatch(r"\d{4}Q[1-4]", s.upper()):
        return _to_period(s), "nokta"
    return None, "yok"


def _find_header(raw: pd.DataFrame) -> int | None:
    for i in range(min(25, len(raw))):
        if sum(classify_header(c)[1] != "yok" for c in raw.iloc[i].tolist()) >= 1:
            return i
    return None


def _label_column(body: pd.DataFrame, period_cols: list) -> int:
    best, best_score = 0, -1
    for j in range(body.shape[1]):
        if j in period_cols:
            continue
        col = body.iloc[:, j].dropna().astype(str)
        score = sum(map_label(x) is not None for x in col) * 10 + sum(any(ch.isalpha() for ch in x) for x in col)
        if score > best_score:
            best, best_score = j, score
    return best


def parse_table(raw: pd.DataFrame) -> tuple[dict, dict, list[str]]:
    """Başlık satırını bulur, kalem ve dönem sütunlarını ayırır. (değerler, 3 aylık, eşlenmeyenler)."""
    h = _find_header(raw)
    if h is None:
        return {}, {}, []
    header = raw.iloc[h].tolist()
    cols = {j: classify_header(v) for j, v in enumerate(header)}
    period_cols = [j for j, (p, k) in cols.items() if k != "yok"]
    body = raw.iloc[h + 1:]
    lab = _label_column(body, period_cols)
    vals, q3, unmapped = {}, {}, []
    for _, row in body.iterrows():
        label = row.iloc[lab]
        if pd.isna(label) or not str(label).strip():
            continue
        code = map_label(str(label))
        if code is None:
            unmapped.append(str(label).strip())
            continue
        for j in period_cols:
            p, k = cols[j]
            try:
                v = parse_tr_number(row.iloc[j])
            except ValueError:
                continue
            target = q3 if k == "3ay" else vals
            target.setdefault(code, {})
            if p not in target[code]:          # ilk eşleşen satır (ana toplam) ve ilk sütun korunur
                target[code][p] = v
    return vals, q3, unmapped


def _frame(d: dict) -> pd.DataFrame:
    df = pd.DataFrame(d).T if d else pd.DataFrame()
    return df[sorted(df.columns)] if not df.empty else df


def from_frame(df: pd.DataFrame, ticker: str, report_date: str, source: str = "", cumulative: bool = True) -> Statement:
    """Başlıklı tabloyu okur (ilk satır başlık). Gerçek KAP dosyaları için `load_file` kullanın."""
    raw = pd.concat([pd.DataFrame([list(df.columns)]), pd.DataFrame(df.values)], ignore_index=True)
    vals, q3, unmapped = parse_table(raw)
    return Statement(ticker, _to_period(report_date), _frame(vals), cumulative, source, unmapped, _frame(q3))


def load_file(path: str | Path, ticker: str, report_date: str, cumulative: bool = True) -> Statement:
    """CSV ya da (çok sayfalı) KAP Excel dosyasını okur; tüm sayfalardaki tabloları birleştirir."""
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        sheets = pd.read_excel(path, sheet_name=None, header=None)
    else:
        sheets = {"csv": pd.read_csv(path, header=None, dtype=str)}
    vals, q3, unmapped = {}, {}, []
    for raw in sheets.values():
        v, q, u = parse_table(raw)
        for code, per in v.items():
            vals.setdefault(code, {}).update({k: x for k, x in per.items() if k not in vals.get(code, {})})
        for code, per in q.items():
            q3.setdefault(code, {}).update({k: x for k, x in per.items() if k not in q3.get(code, {})})
        unmapped += u
    if not vals:
        raise ValueError(f"{path.name}: dönem sütunu veya tanınan kalem bulunamadı")
    return Statement(ticker, _to_period(report_date), _frame(vals), cumulative, str(path), unmapped, _frame(q3))


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


def infer_report_date(path: str | Path) -> pd.Period:
    """Dosyadaki en son dönem sütunundan rapor tarihini çıkarır (ör. '... - 30.09.2025' → 2025Q3)."""
    st = load_file(path, "X", "2000Q1")
    return max(st.values.columns)


def file_into(path: str | Path, ticker: str, folder: str | Path) -> Path:
    """İndirilmiş KAP dosyasını okur, rapor tarihini bulur ve 'HISSE_YYYY_A.uzantı' adıyla klasöre kopyalar."""
    import shutil
    path, folder = Path(path), Path(folder)
    p = infer_report_date(path)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{ticker.upper()}_{p.year}_{p.quarter * 3}{path.suffix.lower()}"
    shutil.copy(path, target)
    return target
