"""Türkçe metin yardımcıları (büyük/küçük harf ve aksan normalizasyonu)."""
import re
import unicodedata

_TR_MAP = str.maketrans({"I": "ı", "İ": "i"})
_ASCII_MAP = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"})


def tr_lower(text: str) -> str:
    """Türkçe kurallarına uygun küçük harfe çevirir (I→ı, İ→i)."""
    return text.translate(_TR_MAP).lower()


def norm(text: str) -> str:
    """Eşleştirme için: küçük harf, Türkçe karakterleri sadeleştir, noktalama ve fazla boşlukları at."""
    t = tr_lower(str(text)).translate(_ASCII_MAP)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\(.*?\)", " ", t)          # parantez içi açıklamaları at: "(Zararı)" vb.
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_tr_number(value) -> float:
    """'1.234.567,89' veya '(1.234)' gibi Türkçe biçimli sayıları float'a çevirir."""
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(" ", "").replace(" ", "")
    if s in {"", "-", "—"}:
        return float("nan")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")  # Türkçe binlik ayırıcı: 1.234 → 1234
    v = float(s)
    return -v if neg else v
