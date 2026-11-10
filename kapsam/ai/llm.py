"""LLM özet katmanı (isteğe bağlı).

Model yalnızca verilen KAP metnine dayanarak yanıt verir ve her iddia için kaynak alıntı
döndürmek zorundadır. Çıktıdaki tüm sayılar validate.grounded ile kaynakta aranır;
bulunamayan sayı varsa özet 'DOĞRULANMADI' olarak işaretlenir ve analiste gösterilir.

Sağlayıcıdan bağımsızdır: `complete(prompt) -> str` imzasına uyan herhangi bir fonksiyon
(açık kaynak yerel model, ticari API) verilebilir.
"""
from __future__ import annotations

import json
from typing import Callable

from ..validate import grounded

SYSTEM_PROMPT = """Sen bir buy-side hisse analistinin araştırma asistanısın.
Kurallar:
- YALNIZCA verilen KAP bildirim metnini kullan. Metinde olmayan bilgi ekleme.
- Yatırım tavsiyesi verme (al/sat/tut deme).
- Her sayıyı metinde geçtiği biçimde yaz.
- Yanıtı şu JSON biçiminde ver:
{"ozet": "en fazla 3 cümle", "kilit_rakamlar": [sayı, ...],
 "alintilar": ["metinden birebir kısa alıntı", ...],
 "tez_etkisi": "olumlu|olumsuz|nötr", "gerekce": "1 cümle"}"""


def summarize(text: str, complete: Callable[[str], str], thesis: str | None = None) -> dict:
    prompt = SYSTEM_PROMPT + (f"\nAnalistin yatırım tezi: {thesis}" if thesis else "") + f"\n\nKAP METNİ:\n{text}"
    raw = complete(prompt)
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except json.JSONDecodeError:
        return {"status": "HATALI_ÇIKTI", "raw": raw}
    nums = [float(n) for n in data.get("kilit_rakamlar", []) if isinstance(n, (int, float))]
    g = grounded(nums, text)
    quotes_ok = all(q in text for q in data.get("alintilar", []))
    data["status"] = "DOĞRULANDI" if g["all_grounded"] and quotes_ok else "DOĞRULANMADI"
    data["dogrulama"] = {"sayilar": g["detail"], "alintilar_kaynakta": quotes_ok}
    return data
