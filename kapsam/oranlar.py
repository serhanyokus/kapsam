"""Politika faizi ve 12 ay sonrası enflasyon beklentisi: her çalıştırmada kendiliğinden güncellenir.

Sıra: (1) TCMB EVDS (seri kodları EVDS üst verisinden bulunur ve önbelleğe alınır),
(2) Google Haberler başlıkları ("politika faizini yüzde X", "12 ay sonrası enflasyon beklentisi yüzde X"),
(3) önceki kayıt (data/gercek/oranlar.json), (4) config/takip.json, (5) varsayılan.
Sonuç data/gercek/oranlar.json'a yazılır; kiyas ve deger modülleri buradan okur.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DOSYA = ("data", "gercek", "oranlar.json")
VARSAYILAN = {"politika_faizi": 0.36, "enflasyon_beklentisi_12a": 0.2395}
TAZE_GUN = 75                       # bu kadar günden eski canlı değer yerine config kullanılır

# EVDS üst verisinde aranacak adlar (küçük harf)
ARAMA = {
    "politika_faizi": {"grup": ["politika faiz", "tcmb faiz oran", "açık piyasa işlem"],
                       "seri": [["bir hafta", "repo"], ["politika faiz"], ["1 hafta", "repo"]]},
    "enflasyon_beklentisi_12a": {"grup": ["piyasa katılımcıları anketi"],
                                 "seri": [["12 ay sonra", "tüfe"], ["12 ay sonra", "enflasyon"], ["12 ay", "yıllık", "tüfe"]]},
}
HABER = {
    "politika_faizi": ("TCMB politika faizi", re.compile(r"politika faiz\w*\D{0,40}?(?:yüzde|%)\s*(\d{1,2}(?:[.,]\d{1,2})?)", re.I)),
    "enflasyon_beklentisi_12a": ("piyasa katılımcıları anketi 12 ay sonrası enflasyon beklentisi",
                                 re.compile(r"12 ay sonrası\D{0,60}?(?:yüzde|%)\s*(\d{1,2}(?:[.,]\d{1,2})?)", re.I)),
}


def yol(root: Path) -> Path:
    return Path(root).joinpath(*DOSYA)


def oku(root: Path) -> dict:
    try:
        return json.loads(yol(root).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def deger(root: Path, key: str, today: pd.Timestamp | None = None) -> tuple[float, str, str]:
    """(oran, tarih, kaynak). Canlı değer tazeyse o; değilse config; o da yoksa varsayılan."""
    today = today or pd.Timestamp.today().normalize()
    o = oku(root).get(key) or {}
    if o.get("deger") is not None:
        t = pd.to_datetime(o.get("tarih"), errors="coerce")
        if pd.notna(t) and (today - t).days <= TAZE_GUN:
            return float(o["deger"]), str(o.get("tarih", "")), str(o.get("kaynak", ""))
    try:
        cfg = json.loads((Path(root) / "config" / "takip.json").read_text(encoding="utf-8"))
        if cfg.get(key) is not None:
            return float(cfg[key]), str(cfg.get(key.split("_")[0] + "_tarih", "") or ""), "config/takip.json"
    except Exception:  # noqa: BLE001
        pass
    if o.get("deger") is not None:
        return float(o["deger"]), str(o.get("tarih", "")), str(o.get("kaynak", "")) + " (eski)"
    return VARSAYILAN[key], "", "varsayılan"


def _evds(client, key: str, cache: dict) -> tuple[float, str, str] | None:
    code = cache.get(key, {}).get("kod")
    if not code:
        groups = client._meta("datagroups/mode=0&type=json")
        spec = ARAMA[key]
        cands = [g for g in groups if any(w in str(g.get("DATAGROUP_NAME", "")).lower() for w in spec["grup"])]
        for g in cands[:8]:
            for s_ in client._meta(f"serieList/type=json&code={g.get('DATAGROUP_CODE')}"):
                name = str(s_.get("SERIE_NAME", "")).lower()
                if any(all(w in name for w in ws) for ws in spec["seri"]):
                    code = s_.get("SERIE_CODE")
                    break
            if code:
                break
    if not code:
        return None
    end = pd.Timestamp.today()
    s = client.series(code, (end - pd.Timedelta(days=400)).strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")).dropna()
    if not len(s):
        return None
    v = float(s.iloc[-1])
    v = v / 100 if v > 1 else v
    if not 0.0 < v < 1.5:
        return None
    return v, s.index[-1].strftime("%Y-%m-%d"), f"TCMB EVDS {code}"


def _haber(key: str, rss) -> tuple[float, str, str] | None:
    q, rx = HABER[key]
    for it in rss(q, days=45, limit=30):
        m = rx.search(it.get("baslik", ""))
        if m:
            v = float(m.group(1).replace(",", ".")) / 100
            if 0.02 < v < 1.0:
                return v, it.get("tarih", ""), f"haber: {it.get('kaynak', '')}"
    return None


def guncelle(root: Path, client=None, rss=None) -> dict:
    root = Path(root)
    old = oku(root)
    out = {"guncelleme": datetime.now(timezone.utc).isoformat(timespec="minutes"), "hatalar": []}
    if client is None:
        try:
            from .data.evds import EVDSClient
            client = EVDSClient()
        except Exception as e:  # noqa: BLE001
            out["hatalar"].append(f"EVDS: {e}")
    if rss is None:
        from .gundem import rss as _rss
        rss = _rss
    for key in VARSAYILAN:
        got = None
        if client is not None:
            try:
                got = _evds(client, key, old)
            except Exception as e:  # noqa: BLE001
                out["hatalar"].append(f"EVDS {key}: {e}")
        if got is None:
            try:
                got = _haber(key, rss)
            except Exception as e:  # noqa: BLE001
                out["hatalar"].append(f"haber {key}: {e}")
        if got is not None:
            v, t, src = got
            out[key] = {"deger": round(v, 4), "tarih": t, "kaynak": src}
            if src.startswith("TCMB EVDS"):
                out[key]["kod"] = src.split()[-1]
        elif old.get(key):
            out[key] = old[key]
    yol(root).parent.mkdir(parents=True, exist_ok=True)
    yol(root).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
