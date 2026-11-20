"""Şirketler arası bilgi grafiği: ilişki çıkarımı, etki yayılımı, benzer şirket ve araştırma önceliği.

Bir KAP bildirimi yalnızca açıklayan şirketi etkilemez: tedarikçisi, müşterisi, iştirakçisi,
rakibi ve aynı gruptaki şirketler de etkilenir. Analistlerin en sık kaçırdığı sinyal budur.

Bu modül:
1. Şirket ağını kurar (tedarikçi/müşteri, ortaklık payı, grup, rakip, sektör).
2. KAP metinlerinden ilişki çıkarır (kanıt cümlesiyle birlikte).
3. Bir olayın ağda nasıl yayıldığını hesaplar ve HER sonucu bir yol ile açıklar.
4. Yapısal gömme + finansal profil ile benzer şirket (peer) önerir.
5. Takip listesi için "araştırma önceliği" sıralaması üretir. Bu bir yatırım önerisi
   değildir; analistin önce neye bakması gerektiğini sıralar.
6. Sıralama modellerini standart bilgi-getirimi metrikleriyle (P@k, R@k, AP, nDCG, MRR)
   ve fiyat tepkisiyle (olay çalışması, CAR) değerlendirir.

Kendi sıralama modelinizi `Ranker` arayüzünü uygulayarak ekleyebilirsiniz.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol

import networkx as nx
import numpy as np
import pandas as pd

from .textutil import norm

# İlişki türü -> (kaynak→hedef iletim katsayısı, hedef→kaynak iletim katsayısı)
# İşaret: +1 aynı yönde etkiler, -1 ters yönde (rakip kazanırsa diğeri kaybeder).
# Kenar yönü: "kaynak, hedefin <tür>'üdür". Örn. supplier: A, B'nin tedarikçisi.
RELATION_TRANSMISSION: dict[str, tuple[float, float]] = {
    "supplier": (0.5, 0.6),    # tedarikçide sorun → müşteriye; müşteride talep → tedarikçiye (daha güçlü)
    "owner": (0.2, 1.0),       # ana ortak → iştirak zayıf; iştirak → ana ortak, pay oranıyla ölçeklenir
    "group": (0.25, 0.25),     # aynı holding grubu
    "competitor": (-0.4, -0.4),
    "peer": (0.15, 0.15),      # sektör okuması (read-across)
}
REL_TR = {"supplier": "tedarikçisi", "owner": "ortağı", "group": "grup şirketi", "competitor": "rakibi", "peer": "sektör benzeri"}


@dataclass
class Relation:
    source: str
    target: str
    kind: str
    weight: float = 1.0          # owner için pay oranı (0-1); diğerlerinde ilişki gücü
    evidence: str = ""           # ilişkiyi doğuran KAP cümlesi


@dataclass
class Impact:
    ticker: str
    score: float
    hops: int
    path: list[str]
    explanation: str


class CompanyGraph:
    def __init__(self):
        self.g = nx.MultiDiGraph()
        self.aliases: dict[str, str] = {}

    # --- kurulum -------------------------------------------------------------------------
    def add_company(self, ticker: str, name: str = "", sector: str = "", aliases: Iterable[str] = ()):
        self.g.add_node(ticker, name=name or ticker, sector=sector)
        for a in [ticker, name, *aliases]:
            if a:
                self.aliases[norm(a)] = ticker

    def add_relation(self, r: Relation):
        for t in (r.source, r.target):
            if t not in self.g:
                self.add_company(t)
        fwd, bwd = RELATION_TRANSMISSION[r.kind]
        w = r.weight
        self.g.add_edge(r.source, r.target, kind=r.kind, coef=fwd * (w if r.kind != "owner" else 1.0),
                        weight=w, evidence=r.evidence, direction="fwd")
        back = bwd * w
        self.g.add_edge(r.target, r.source, kind=r.kind, coef=back, weight=w, evidence=r.evidence, direction="bwd")

    def add_sector_peers(self, weight: float = 1.0):
        """Aynı sektördeki şirketler arasında zayıf 'peer' bağı kurar."""
        by_sector: dict[str, list[str]] = {}
        for n, d in self.g.nodes(data=True):
            if d.get("sector"):
                by_sector.setdefault(d["sector"], []).append(n)
        for members in by_sector.values():
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    if not self._has(a, b, "competitor") and not self._has(a, b, "peer"):
                        self.add_relation(Relation(a, b, "peer", weight))

    def _has(self, a, b, kind) -> bool:
        return any(d["kind"] == kind for d in self.g.get_edge_data(a, b, default={}).values())

    def resolve(self, name: str) -> str | None:
        return self.aliases.get(norm(name))

    @classmethod
    def from_json(cls, path: str | Path) -> "CompanyGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cg = cls()
        for c in data["companies"]:
            cg.add_company(c["ticker"], c.get("name", ""), c.get("sector", ""), c.get("aliases", []))
        for r in data.get("relations", []):
            cg.add_relation(Relation(**r))
        if data.get("sector_peers", True):
            cg.add_sector_peers()
        return cg

    def relations(self) -> pd.DataFrame:
        rows = [{"kaynak": u, "hedef": v, "tür": d["kind"], "ağırlık": d["weight"], "kanıt": d["evidence"]}
                for u, v, d in self.g.edges(data=True) if d["direction"] == "fwd"]
        return pd.DataFrame(rows)

    # --- etki yayılımı --------------------------------------------------------------------
    def propagate(self, ticker: str, shock: float, max_hops: int = 3, decay: float = 0.6,
                  min_abs: float = 0.01) -> list[Impact]:
        """`ticker`a gelen `shock` (+ olumlu / - olumsuz, büyüklük = önem) ağda nasıl yayılır?

        Her basit yol için katkı = şok × Π(kenar katsayısı) × decay^(adım-1).
        Bir şirketin toplam etkisi yollarının toplamıdır; açıklama en büyük katkılı yoldur.
        """
        total: dict[str, float] = {}
        best: dict[str, tuple[float, list[str], list[dict]]] = {}

        def walk(node, value, path, edges):
            if len(path) - 1 >= max_hops:
                return
            for _, nxt, d in self.g.out_edges(node, data=True):
                if nxt in path:
                    continue
                hop = len(path)
                v = value * d["coef"] * (decay ** (hop - 1))
                if abs(v) < min_abs * abs(shock):
                    continue
                total[nxt] = total.get(nxt, 0.0) + v
                if nxt not in best or abs(v) > abs(best[nxt][0]):
                    best[nxt] = (v, path + [nxt], edges + [d])
                walk(nxt, value * d["coef"], path + [nxt], edges + [d])

        walk(ticker, shock, [ticker], [])
        out = []
        for t, s in total.items():
            v, p, e = best[t]
            out.append(Impact(t, s, len(p) - 1, p, self._explain(p, e)))
        return sorted(out, key=lambda i: -abs(i.score))

    def _explain(self, path: list[str], edges: list[dict]) -> str:
        parts = [path[0]]
        for (a, b), d in zip(zip(path, path[1:]), edges):
            if d["direction"] == "fwd":
                rel = f"{a}, {b} şirketinin {REL_TR[d['kind']]}"
            else:
                rel = f"{b}, {a} şirketinin {REL_TR[d['kind']]}"
            if d["kind"] == "owner":
                rel += f" (%{d['weight']*100:.0f})"
            parts.append(f"→ {b} [{rel}]")
        return " ".join(parts)

    # --- benzer şirket -------------------------------------------------------------------
    def embed(self, dim: int = 4) -> pd.DataFrame:
        """Ağırlıklı, yönsüz komşuluk matrisinin normalize Laplasyen'inden spektral gömme."""
        nodes = list(self.g.nodes)
        idx = {n: i for i, n in enumerate(nodes)}
        a = np.zeros((len(nodes), len(nodes)))
        for u, v, d in self.g.edges(data=True):
            a[idx[u], idx[v]] += abs(d["coef"])
        a = (a + a.T) / 2
        deg = a.sum(1)
        dinv = np.where(deg > 0, 1 / np.sqrt(deg), 0)
        lap = np.eye(len(nodes)) - dinv[:, None] * a * dinv[None, :]
        vals, vecs = np.linalg.eigh(lap)
        k = min(dim, len(nodes) - 1)
        emb = vecs[:, 1:k + 1]
        return pd.DataFrame(emb, index=nodes, columns=[f"e{i+1}" for i in range(k)])

    def role_features(self) -> pd.DataFrame:
        """Şirketin ağdaki ROLÜ: kendi sektörü, ilişki türü × yön sayıları ve komşularının sektörleri.

        Benzer şirket (peer) için yakınlık değil rol benzerliği gerekir: aynı holdingin enerji
        şirketi yakındır ama benzer değildir; rakip yan sanayi şirketi uzaktır ama benzerdir.
        """
        rows = {}
        for n, d in self.g.nodes(data=True):
            f = {f"sektor:{d.get('sector', '')}": 2.0}
            for _, v, e in self.g.out_edges(n, data=True):
                if e["kind"] == "peer":
                    continue
                role = f"rol:{e['kind']}:{e['direction']}"
                f[role] = f.get(role, 0) + 1
                ns = f"komsu:{e['kind']}:{e['direction']}:{self.g.nodes[v].get('sector', '')}"
                f[ns] = f.get(ns, 0) + 1
            rows[n] = f
        return pd.DataFrame(rows).T.fillna(0.0)

    def similar(self, ticker: str, k: int = 5, features: pd.DataFrame | None = None, alpha: float = 0.6) -> pd.Series:
        """Rol benzerliği (ağ) ile finansal profil benzerliğinin (normalize KPI) ağırlıklı ortalaması; kosinüs."""
        def cos(df, standardize):
            x = df.fillna(0).to_numpy(float)
            if standardize:
                x = (x - x.mean(0)) / (x.std(0) + 1e-12)
            x = x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-12)
            return pd.DataFrame(x @ x.T, index=df.index, columns=df.index)
        s = cos(self.role_features(), standardize=False)[ticker]
        if features is not None and ticker in features.index and len(features) > 2:
            f = cos(features, standardize=True)[ticker].reindex(s.index)
            s = alpha * s + (1 - alpha) * f.fillna(s)
        return s.drop(ticker).sort_values(ascending=False).head(k)


# --- KAP metninden ilişki çıkarımı -----------------------------------------------------------
_PCT = re.compile(r"%\s?(\d{1,3}(?:,\d+)?)|(\d{1,3}(?:,\d+)?)\s?%")


def extract_relations(text: str, reporter: str, graph: CompanyGraph) -> list[Relation]:
    """Bildirim metninde geçen bilinen şirket adlarını bulur ve ilişki türünü sezgisel kurallarla belirler.

    Her ilişki, kanıt olarak ilgili cümleyi taşır; analist onaylamadan grafiğe kalıcı eklenmemelidir.
    """
    out = []
    protected = re.sub(r"\b(A\.Ş|A\.S|T\.A\.Ş|Ltd\.Şti|Ltd|Tic|San|Şti|Inc|Co)\.", lambda m: m.group(0).replace(".", "\u2024"), text)
    for sent in (x.replace("\u2024", ".") for x in re.split(r"(?<=[.!?])\s+", protected)):
        ns = norm(sent)
        for alias, ticker in sorted(graph.aliases.items(), key=lambda kv: -len(kv[0])):
            if ticker == reporter or len(alias) < 3 or f" {alias} " not in f" {ns} ":
                continue
            m = _PCT.search(sent)
            pct = float((m.group(1) or m.group(2)).replace(",", ".")) / 100 if m else None
            if any(k in ns for k in ["istirak", "pay devr", "pay satin al", "sermayesindeki", "oraninda pay"]) and pct:
                if "sirketimiz sermaye" in ns or "sirketimizin sermaye" in ns:
                    kind, src, dst, w = "owner", ticker, reporter, pct    # karşı taraf bizim ortağımız
                else:
                    kind, src, dst, w = "owner", reporter, ticker, pct    # biz karşı tarafın ortağıyız
            elif any(k in ns for k in ["tedarik sozlesmesi", "siparis", "satis sozlesmesi", "urun tedarik", "musterisi"]):
                kind, src, dst, w = "supplier", reporter, ticker, 1.0     # açıklayan şirket satıcı
            elif any(k in ns for k in ["hammadde alim", "satin alinmasi", "tedarikcisi", "alim sozlesmesi"]):
                kind, src, dst, w = "supplier", ticker, reporter, 1.0     # açıklayan şirket alıcı
            elif "rakip" in ns:
                kind, src, dst, w = "competitor", reporter, ticker, 1.0
            else:
                continue
            out.append(Relation(src, dst, kind, w, sent.strip()))
            break
    return out


# --- araştırma önceliği (sıralama) -----------------------------------------------------------
@dataclass
class Event:
    ticker: str
    shock: float                       # + olumlu, - olumsuz; büyüklük = önem (0-1)
    title: str = ""
    truth: set[str] = field(default_factory=set)   # değerlendirme için: gerçekten etkilenen şirketler


class Ranker(Protocol):
    name: str

    def rank(self, graph: CompanyGraph, event: Event) -> list[str]:
        ...


class DirectOnly:
    """Taban çizgisi: yalnızca bildirimi yapan şirkete bak (bugünkü pratik)."""
    name = "Yalnızca açıklayan şirket"

    def rank(self, graph, event):
        return [event.ticker]


class SectorOnly:
    """Taban çizgisi: açıklayan şirket + aynı sektör."""
    name = "Sektör okuması"

    def rank(self, graph, event):
        sec = graph.g.nodes[event.ticker].get("sector")
        same = [n for n, d in graph.g.nodes(data=True) if d.get("sector") == sec and n != event.ticker]
        return [event.ticker, *sorted(same)]


class Propagation:
    """KAPSAM: bilgi grafiği üzerinde açıklamalı etki yayılımı."""
    name = "KAPSAM ağ yayılımı"

    def __init__(self, max_hops=3, decay=0.6, threshold=0.05):
        self.max_hops, self.decay, self.threshold = max_hops, decay, threshold

    def rank(self, graph, event):
        imp = graph.propagate(event.ticker, event.shock, self.max_hops, self.decay)
        return [event.ticker] + [i.ticker for i in imp if abs(i.score) >= self.threshold * abs(event.shock)]


def research_queue(graph: CompanyGraph, events: list[Event], watchlist: list[str], **kw) -> pd.DataFrame:
    """Takip listesindeki şirketleri, son olayların doğrudan ve dolaylı etkisine göre sıralar."""
    score: dict[str, float] = {t: 0.0 for t in watchlist}
    why: dict[str, list[str]] = {t: [] for t in watchlist}
    for e in events:
        if e.ticker in score:
            score[e.ticker] += abs(e.shock)
            why[e.ticker].append(f"Doğrudan: {e.title}")
        for i in graph.propagate(e.ticker, e.shock, **kw):
            if i.ticker in score:
                score[i.ticker] += abs(i.score)
                why[i.ticker].append(f"{'+' if i.score > 0 else '-'} {e.title}: {i.explanation}")
    df = pd.DataFrame({"oncelik": score, "neden": {k: " | ".join(v) for k, v in why.items()}})
    return df.sort_values("oncelik", ascending=False)


# --- değerlendirme metrikleri ---------------------------------------------------------------
def precision_at_k(ranked: list[str], truth: set[str], k: int) -> float:
    return len([r for r in ranked[:k] if r in truth]) / k if k else 0.0


def recall_at_k(ranked: list[str], truth: set[str], k: int) -> float:
    return len([r for r in ranked[:k] if r in truth]) / len(truth) if truth else 0.0


def average_precision(ranked: list[str], truth: set[str]) -> float:
    hits, s = 0, 0.0
    for i, r in enumerate(ranked, 1):
        if r in truth:
            hits += 1
            s += hits / i
    return s / len(truth) if truth else 0.0


def ndcg_at_k(ranked: list[str], truth: set[str], k: int) -> float:
    dcg = sum(1 / math.log2(i + 1) for i, r in enumerate(ranked[:k], 1) if r in truth)
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(truth)) + 1))
    return dcg / idcg if idcg else 0.0


def mrr(ranked: list[str], truth: set[str]) -> float:
    for i, r in enumerate(ranked, 1):
        if r in truth:
            return 1 / i
    return 0.0


def evaluate(rankers: list[Ranker], graph: CompanyGraph, events: list[Event], k: int = 5) -> pd.DataFrame:
    rows = {}
    for rk in rankers:
        res = []
        for e in events:
            r = rk.rank(graph, e)
            res.append([precision_at_k(r, e.truth, k), recall_at_k(r, e.truth, k), average_precision(r, e.truth),
                        ndcg_at_k(r, e.truth, k), mrr(r, e.truth)])
        rows[rk.name] = np.mean(res, axis=0)
    return pd.DataFrame(rows, index=[f"P@{k}", f"R@{k}", "MAP", f"nDCG@{k}", "MRR"]).T


# --- olay çalışması (gerçek veriyle doğrulama için) -------------------------------------------
def event_study(returns: pd.DataFrame, market: pd.Series, event_date, tickers: list[str],
                est_window: int = 120, gap: int = 10, car_window: tuple[int, int] = (-1, 3)) -> pd.DataFrame:
    """Piyasa modeliyle anormal getiri ve kümülatif anormal getiri (CAR).

    returns: günlük getiriler (index tarih, sütun hisse), market: BIST endeks getirisi.
    Tahmin penceresi: olaydan önceki [-gap-est_window, -gap) gün. CAR penceresi: [a, b] gün.
    Ağın öngördüğü şirketlerde |CAR| anlamlı mı? Gerçek veride modelin doğrulama ölçütü budur.
    """
    dates = returns.index
    t0 = dates.get_indexer([pd.Timestamp(event_date)], method="bfill")[0]
    est = slice(max(0, t0 - gap - est_window), t0 - gap)
    win = slice(t0 + car_window[0], t0 + car_window[1] + 1)
    rows = {}
    for t in tickers:
        y, x = returns[t].iloc[est], market.iloc[est]
        beta = np.cov(y, x)[0, 1] / np.var(x, ddof=1)
        alpha = y.mean() - beta * x.mean()
        resid_sd = (y - alpha - beta * x).std(ddof=2)
        ar = returns[t].iloc[win] - (alpha + beta * market.iloc[win])
        car = ar.sum()
        n = len(ar)
        rows[t] = {"alfa": alpha, "beta": beta, "CAR": car, "t_istatistigi": car / (resid_sd * math.sqrt(n))}
    return pd.DataFrame(rows).T


def load_with_disclosures(path: str | Path) -> tuple[CompanyGraph, list[Event], list[Relation]]:
    """JSON'dan grafiği kurar, içindeki bildirimlerden ilişki çıkarıp ekler; olayları döner."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cg = CompanyGraph.from_json(path)
    found = []
    for d in data.get("disclosures", []):
        for r in extract_relations(d["metin"], d["reporter"], cg):
            cg.add_relation(r)
            found.append(r)
    events = [Event(e["ticker"], e["shock"], e.get("title", ""), set(e.get("truth", []))) for e in data.get("events", [])]
    return cg, events, found


def draw(graph: CompanyGraph, focus: str | None = None, impacts: list[Impact] | None = None, ax=None):
    """Ağ görseli: kenar rengi ilişki türü, düğüm rengi olay etkisi (kırmızı olumsuz, yeşil olumlu)."""
    import matplotlib.pyplot as plt
    ug = nx.Graph()
    for u, v, d in graph.g.edges(data=True):
        if d["direction"] == "fwd" and d["kind"] != "peer":
            ug.add_edge(u, v, kind=d["kind"])
    ug.add_nodes_from(graph.g.nodes)
    pos = nx.spring_layout(ug, seed=7, k=0.9)
    if ax is None:
        _, ax = plt.subplots(figsize=(7.5, 5.2))
    colors = {"supplier": "#1f5fbf", "owner": "#7a3fb0", "group": "#7a3fb0", "competitor": "#d0342c"}
    for kind, col in colors.items():
        es = [(u, v) for u, v, d in ug.edges(data=True) if d["kind"] == kind]
        nx.draw_networkx_edges(ug, pos, edgelist=es, edge_color=col, width=1.6, alpha=0.7, ax=ax,
                               style="dashed" if kind == "competitor" else "solid")
    score = {i.ticker: i.score for i in (impacts or [])}
    ncol = []
    for n in ug.nodes:
        if n == focus:
            ncol.append("#f2b705")
        elif n in score:
            s = max(-1, min(1, score[n] / 0.5))
            ncol.append(plt.cm.RdYlGn((s + 1) / 2))
        else:
            ncol.append("#dfe4ec")
    nx.draw_networkx_nodes(ug, pos, node_color=ncol, node_size=900, edgecolors="#4a5568", linewidths=0.8, ax=ax)
    nx.draw_networkx_labels(ug, pos, font_size=8, ax=ax)
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([0], [0], color=c, lw=2, ls="--" if k == "competitor" else "-", label=REL_TR[k])
                       for k, c in colors.items() if k != "group"], fontsize=7, frameon=False, loc="lower left")
    ax.axis("off")
    return ax
