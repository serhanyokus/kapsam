import json

import numpy as np
import pandas as pd
import pytest

from kapsam import graph as kg

from .test_core import DEMO

GJ = DEMO / "graph_SENTETIK.json"


@pytest.fixture()
def g():
    cg = kg.CompanyGraph.from_json(GJ)
    for d in json.loads(GJ.read_text(encoding="utf-8"))["disclosures"]:
        for r in kg.extract_relations(d["metin"], d["reporter"], cg):
            cg.add_relation(r)
    return cg


def small():
    cg = kg.CompanyGraph()
    for t, s in [("A", "x"), ("B", "y"), ("C", "z"), ("R", "y")]:
        cg.add_company(t, sector=s)
    cg.add_relation(kg.Relation("B", "A", "supplier"))      # B, A'nın tedarikçisi
    cg.add_relation(kg.Relation("C", "B", "supplier"))      # C, B'nin tedarikçisi
    cg.add_relation(kg.Relation("B", "R", "competitor"))
    return cg


# --- ilişki çıkarımı -----------------------------------------------------------------------
def test_extraction_handles_company_abbreviations(g):
    rel = g.relations()
    def has(s, t, k):
        return ((rel["kaynak"] == s) & (rel["hedef"] == t) & (rel["tür"] == k)).any()
    assert has("DEMO", "OTO1", "supplier")          # satış sözleşmesi: DEMO satıcı
    assert has("CLK1", "DEMO", "supplier")          # hammadde alımı: DEMO alıcı
    row = rel[(rel["kaynak"] == "HLD1") & (rel["hedef"] == "DEMO") & (rel["tür"] == "owner")]
    assert len(row) == 1 and row["ağırlık"].iloc[0] == pytest.approx(0.55)
    assert "%55" in row["kanıt"].iloc[0]           # kanıt cümlesi saklanır


def test_extraction_ignores_unknown_and_self():
    cg = small()
    assert kg.extract_relations("Bilinmeyen Ltd. ile tedarik sözleşmesi imzalanmıştır.", "A", cg) == []
    assert kg.extract_relations("A ile tedarik sözleşmesi imzalanmıştır.", "A", cg) == []


# --- yayılım --------------------------------------------------------------------------------
def test_propagation_signs_and_decay():
    cg = small()
    imp = {i.ticker: i for i in cg.propagate("A", -1.0)}
    assert imp["B"].score < 0                       # müşteri kötü → tedarikçi kötü
    assert imp["C"].score < 0 and abs(imp["C"].score) < abs(imp["B"].score)   # 2. adım daha zayıf
    assert imp["R"].score > 0                       # tedarikçi zarar görürse rakibi kazanır
    assert imp["C"].hops == 2 and imp["C"].path == ["A", "B", "C"]


def test_propagation_respects_max_hops():
    cg = small()
    assert "C" not in {i.ticker for i in cg.propagate("A", -1.0, max_hops=1)}


def test_ownership_scales_with_stake(g):
    imp = {i.ticker: i for i in g.propagate("DEMO", 1.0, max_hops=1)}
    assert imp["HLD1"].score == pytest.approx(0.55)
    assert "%55" in imp["HLD1"].explanation


def test_every_impact_is_explained(g):
    for i in g.propagate("OTO1", -0.8):
        assert i.path[0] == "OTO1" and i.path[-1] == i.ticker and "→" in i.explanation


# --- benzerlik -------------------------------------------------------------------------------
def test_similar_prefers_role_peers_over_ecosystem(g):
    assert g.similar("DEMO", 1).index[0] == "YAN2"
    assert g.similar("OTO1", 1).index[0] == "OTO2"


def test_embedding_shape(g):
    e = g.embed(3)
    assert e.shape == (len(g.g.nodes), 3) and np.isfinite(e.to_numpy()).all()


# --- sıralama ve metrikler -------------------------------------------------------------------
def test_metrics_known_values():
    r, t = ["a", "x", "b", "y"], {"a", "b"}
    assert kg.precision_at_k(r, t, 2) == 0.5
    assert kg.recall_at_k(r, t, 4) == 1.0
    assert kg.average_precision(r, t) == pytest.approx((1 / 1 + 2 / 3) / 2)
    assert kg.mrr(["x", "a"], t) == 0.5
    assert kg.ndcg_at_k(["a", "b"], t, 2) == pytest.approx(1.0)
    assert kg.ndcg_at_k(["x", "y"], t, 2) == 0.0


def test_propagation_beats_baselines_on_synthetic_cases(g):
    data = json.loads(GJ.read_text(encoding="utf-8"))
    ev = [kg.Event(e["ticker"], e["shock"], e["title"], set(e["truth"])) for e in data["events"]]
    res = kg.evaluate([kg.DirectOnly(), kg.SectorOnly(), kg.Propagation()], g, ev, k=5)
    assert res.loc["KAPSAM ağ yayılımı", "R@5"] > res.loc["Sektör okuması", "R@5"] > res.loc["Yalnızca açıklayan şirket", "R@5"]


def test_custom_ranker_plugs_in(g):
    class Mine:
        name = "Benim modelim"
        def rank(self, graph, event):
            return [event.ticker]
    ev = [kg.Event("DEMO", 1.0, "x", {"DEMO"})]
    assert kg.evaluate([Mine()], g, ev, k=1).loc["Benim modelim", "P@1"] == 1.0


def test_research_queue_orders_by_exposure(g):
    q = kg.research_queue(g, [kg.Event("OTO1", -0.8, "OTO1 üretime ara verdi")], ["PRK1", "DEMO", "HLD1"])
    assert list(q.index[:2]) == ["DEMO", "HLD1"] and q.loc["PRK1", "oncelik"] == 0
    assert "OTO1" in q.loc["DEMO", "neden"]


# --- olay çalışması --------------------------------------------------------------------------
def test_event_study_recovers_abnormal_return():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2025-01-01", periods=200)
    mkt = pd.Series(rng.normal(0, 0.01, 200), index=idx)
    r = pd.DataFrame({"A": 0.0002 + 1.2 * mkt + rng.normal(0, 0.005, 200),
                      "B": 0.8 * mkt + rng.normal(0, 0.005, 200)}, index=idx)
    t0 = 170
    r.iloc[t0, 0] += -0.08                          # A'ya olay günü -%8 şok
    es = kg.event_study(r, mkt, idx[t0], ["A", "B"])
    assert es.loc["A", "beta"] == pytest.approx(1.2, abs=0.15)
    assert es.loc["A", "CAR"] < -0.05 and es.loc["A", "t_istatistigi"] < -3
    assert abs(es.loc["B", "t_istatistigi"]) < 3
