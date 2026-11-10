"""Yatırım tezi takip motoru.

Analist tezini ölçülebilir KPI kurallarına bağlar. Her yeni çeyrek/bildirimde kurallar
normalize edilmiş metriklerle değerlendirilir ve tezin durumu raporlanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Rule:
    metric: str            # tms29.metrics() satır adı, ör. 'gross_margin'
    op: str                # '>', '<', 'up', 'down'  (up/down: önceki çeyreğe göre)
    threshold: float = 0.0
    weight: float = 1.0
    label: str = ""


@dataclass
class Thesis:
    ticker: str
    title: str
    rules: list[Rule] = field(default_factory=list)

    def evaluate(self, m: pd.DataFrame, period: pd.Period | None = None) -> dict:
        period = period or max(m.columns)
        cols = list(m.columns)
        prev = cols[cols.index(period) - 1] if cols.index(period) > 0 else None
        results, score, wsum = [], 0.0, 0.0
        for r in self.rules:
            v = m.at[r.metric, period]
            if r.op == ">":
                ok = v > r.threshold
            elif r.op == "<":
                ok = v < r.threshold
            elif r.op in {"up", "down"} and prev is not None:
                d = v - m.at[r.metric, prev]
                ok = d > r.threshold if r.op == "up" else d < -r.threshold
            else:
                ok = None
            if ok is not None:
                score += r.weight * (1 if ok else -1)
                wsum += r.weight
            results.append({"kural": r.label or f"{r.metric} {r.op} {r.threshold}", "deger": v, "saglandi": ok})
        s = score / wsum if wsum else 0.0
        status = "GÜÇLENDİ" if s > 0.33 else "ZAYIFLADI" if s < -0.33 else "KARIŞIK"
        return {"ticker": self.ticker, "tez": self.title, "donem": str(period), "skor": round(s, 2), "durum": status, "kurallar": results}
