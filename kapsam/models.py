"""Bilgi grafiği üzerinde öğrenen modeller ve istatistiksel model karşılaştırması.

`graph.Propagation` ilişki katsayılarını elle belirlenmiş kurallarla kullanır. Bu modül:

1. **Kişiselleştirilmiş PageRank (PPR):** Olay şirketinden başlayan rastgele yürüyüşle
   etkilenme olasılığı; kural gerektirmeyen güçlü bir taban çizgisi.
2. **TransE:** Şirket ve ilişki gömmeleri (h + r ≈ t). Ağda henüz açıkça kayıtlı olmayan
   ama olası bağları da yakalayabilir (bağlantı tahmini).
3. **Katsayı kalibrasyonu:** İlişki türü × yön başına iletim katsayısını, geçmiş olaylarda
   gözlenen fiyat tepkilerinden (CAR) en küçük kareler ile öğrenir; kuralları veriyle değiştirir.
4. **Eşleştirilmiş bootstrap:** İki modelin metrik farkı için güven aralığı. "Model A daha
   iyi" demeden önce farkın şans eseri olmadığını gösterir.

Tüm modeller `graph.Ranker` arayüzünü uygular ve `graph.evaluate` ile karşılaştırılabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from . import graph as kg


# --- 1) Kişiselleştirilmiş PageRank ---------------------------------------------------------
class PersonalizedPageRank:
    name = "Kişiselleştirilmiş PageRank"

    def __init__(self, alpha: float = 0.85, top: int | None = None):
        self.alpha, self.top = alpha, top

    def scores(self, graph: kg.CompanyGraph, ticker: str) -> pd.Series:
        ug = nx.DiGraph()
        ug.add_nodes_from(graph.g.nodes)
        for u, v, d in graph.g.edges(data=True):
            w = abs(d["coef"])
            ug.add_edge(u, v, weight=ug.get_edge_data(u, v, {"weight": 0})["weight"] + w)
        pr = nx.pagerank(ug, alpha=self.alpha, personalization={ticker: 1.0}, weight="weight")
        return pd.Series(pr).drop(ticker).sort_values(ascending=False)

    def rank(self, graph, event):
        s = self.scores(graph, event.ticker)
        return [event.ticker] + list(s.index[: self.top] if self.top else s.index)


# --- 2) TransE --------------------------------------------------------------------------------
@dataclass
class TransE:
    dim: int = 16
    epochs: int = 400
    lr: float = 0.02
    margin: float = 1.0
    seed: int = 0
    name: str = "TransE gömme"

    def fit(self, graph: kg.CompanyGraph) -> "TransE":
        rng = np.random.default_rng(self.seed)
        self.ents = list(graph.g.nodes)
        self.e_idx = {e: i for i, e in enumerate(self.ents)}
        triples = [(u, f"{d['kind']}:{d['direction']}", v) for u, v, d in graph.g.edges(data=True) if d["kind"] != "peer"]
        self.rels = sorted({r for _, r, _ in triples})
        self.r_idx = {r: i for i, r in enumerate(self.rels)}
        b = 6 / np.sqrt(self.dim)
        E = rng.uniform(-b, b, (len(self.ents), self.dim))
        R = rng.uniform(-b, b, (len(self.rels), self.dim))
        R /= np.linalg.norm(R, axis=1, keepdims=True)
        T = np.array([(self.e_idx[h], self.r_idx[r], self.e_idx[t]) for h, r, t in triples])
        self.losses = []
        for _ in range(self.epochs):
            E /= np.maximum(1.0, np.linalg.norm(E, axis=1, keepdims=True))
            loss = 0.0
            for h, r, t in T[rng.permutation(len(T))]:
                tc = rng.integers(len(self.ents))           # bozulmuş kuyruk (negatif örnek)
                if tc == t:
                    continue
                pos = E[h] + R[r] - E[t]
                neg = E[h] + R[r] - E[tc]
                lp, ln = np.linalg.norm(pos), np.linalg.norm(neg)
                l_ = self.margin + lp - ln
                if l_ <= 0:
                    continue
                loss += l_
                gp = pos / (lp + 1e-9)
                gn = neg / (ln + 1e-9)
                E[h] -= self.lr * (gp - gn)
                R[r] -= self.lr * (gp - gn)
                E[t] += self.lr * gp
                E[tc] -= self.lr * gn
            self.losses.append(loss)
        self.E, self.R = E, R
        self._graph = graph
        return self

    def plausibility(self, head: str, tail: str) -> float:
        """En olası ilişki türü için -||h + r - t||; büyük değer daha olası bağ demektir."""
        h, t = self.E[self.e_idx[head]], self.E[self.e_idx[tail]]
        return float(-np.min(np.linalg.norm(h + self.R - t, axis=1)))

    def rank(self, graph, event):
        if getattr(self, "_graph", None) is not graph:
            self.fit(graph)
        s = {c: max(self.plausibility(event.ticker, c), self.plausibility(c, event.ticker))
             for c in self.ents if c != event.ticker}
        return [event.ticker] + sorted(s, key=s.get, reverse=True)

    def suggest_links(self, graph: kg.CompanyGraph, top: int = 5) -> pd.DataFrame:
        """Ağda kayıtlı olmayan ama gömmeye göre olası bağlar: analistin doğrulaması için aday listesi."""
        existing = {(u, v) for u, v in graph.g.edges()}
        rows = []
        for a in self.ents:
            for b in self.ents:
                if a != b and (a, b) not in existing:
                    h, t = self.E[self.e_idx[a]], self.E[self.e_idx[b]]
                    d = np.linalg.norm(h + self.R - t, axis=1)
                    rows.append({"kaynak": a, "hedef": b, "ilişki": self.rels[int(d.argmin())], "skor": -float(d.min())})
        return pd.DataFrame(rows).sort_values("skor", ascending=False).head(top)


# --- 3) Katsayı kalibrasyonu ------------------------------------------------------------------
@dataclass
class Reaction:
    """Geçmiş bir olayda bir komşu şirketin gözlenen tepkisi (ör. olay çalışmasından CAR)."""
    source: str        # olay şirketi
    target: str        # tepki veren komşu
    shock: float       # olay şoku (yön ve büyüklük)
    car: float         # gözlenen kümülatif anormal getiri


def calibrate(graph: kg.CompanyGraph, reactions: list[Reaction], min_obs: int = 3, ridge: float = 1e-6) -> pd.DataFrame:
    """Doğrudan komşu tepkilerinden ilişki türü × yön başına iletim katsayısını öğrenir.

    Model: CAR_c = β_(tür,yön) × şok × ağırlık + hata   (ortaklıkta ağırlık = pay oranı)
    Kapalı çözüm: β = Σ(x·y) / (Σx² + λ). Yeterli gözlemi olmayan türler değiştirilmez.
    Dönen tablo: öğrenilen katsayı, eski katsayı, gözlem sayısı, standart hata.
    """
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for r in reactions:
        for d in graph.g.get_edge_data(r.source, r.target, default={}).values():
            scale = d["weight"] if (d["kind"] == "owner" and d["direction"] == "bwd") or d["kind"] != "owner" else 1.0
            groups.setdefault((d["kind"], d["direction"]), []).append((r.shock * scale, r.car))
    rows = []
    for (kind, direction), obs in groups.items():
        x = np.array([o[0] for o in obs])
        y = np.array([o[1] for o in obs])
        fwd, bwd = kg.RELATION_TRANSMISSION[kind]
        old = fwd if direction == "fwd" else bwd
        if len(obs) < min_obs:
            rows.append({"tür": kind, "yön": direction, "eski": old, "öğrenilen": old, "n": len(obs), "std_hata": np.nan})
            continue
        beta = float(x @ y / (x @ x + ridge))
        resid = y - beta * x
        se = float(np.sqrt((resid @ resid) / max(1, len(x) - 1) / (x @ x + ridge)))
        rows.append({"tür": kind, "yön": direction, "eski": old, "öğrenilen": beta, "n": len(obs), "std_hata": se})
    return pd.DataFrame(rows).sort_values(["tür", "yön"]).reset_index(drop=True)


def apply_calibration(graph: kg.CompanyGraph, table: pd.DataFrame) -> kg.CompanyGraph:
    """Öğrenilen katsayıları grafiğin kenarlarına uygular (yerinde)."""
    learned = {(r["tür"], r["yön"]): r["öğrenilen"] for _, r in table.iterrows()}
    for _, _, d in graph.g.edges(data=True):
        key = (d["kind"], d["direction"])
        if key in learned:
            scale = d["weight"] if not (d["kind"] == "owner" and d["direction"] == "fwd") else 1.0
            d["coef"] = learned[key] * scale
    return graph


# --- 4) Eşleştirilmiş bootstrap ---------------------------------------------------------------
def per_event_metric(ranker, graph, events, metric: str = "ndcg", k: int = 5) -> np.ndarray:
    f = {"ndcg": lambda r, t: kg.ndcg_at_k(r, t, k), "recall": lambda r, t: kg.recall_at_k(r, t, k),
         "precision": lambda r, t: kg.precision_at_k(r, t, k), "ap": kg.average_precision, "mrr": kg.mrr}[metric]
    return np.array([f(ranker.rank(graph, e), e.truth) for e in events])


def paired_bootstrap(a, b, graph, events, metric: str = "ndcg", k: int = 5, n: int = 5000, seed: int = 0) -> dict:
    """Model A − Model B ortalama metrik farkı ve %95 güven aralığı (olaylar yeniden örneklenir)."""
    ma, mb = per_event_metric(a, graph, events, metric, k), per_event_metric(b, graph, events, metric, k)
    diff = ma - mb
    rng = np.random.default_rng(seed)
    boots = np.array([diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(n)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"A": a.name, "B": b.name, "metrik": f"{metric}@{k}", "fark": float(diff.mean()),
            "GA_alt": float(lo), "GA_üst": float(hi), "p(fark<=0)": float((boots <= 0).mean()), "olay_sayısı": len(diff)}
