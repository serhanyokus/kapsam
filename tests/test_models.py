import numpy as np
import pytest

from kapsam import graph as kg
from kapsam import models as md

from .test_core import DEMO

GJ = DEMO / "graph_SENTETIK.json"


@pytest.fixture()
def loaded():
    return kg.load_with_disclosures(GJ)


def test_ppr_ranks_direct_neighbours_first(loaded):
    g, _, _ = loaded
    s = md.PersonalizedPageRank().scores(g, "OTO1")
    assert set(s.index[:3]) & {"DEMO", "LOJ1", "OTO2"}
    assert "OTO1" not in s.index


def test_transe_training_reduces_loss_and_ranks(loaded):
    g, ev, _ = loaded
    te = md.TransE(epochs=300).fit(g)
    assert te.losses[-1] < te.losses[0] * 0.5
    r = te.rank(g, ev[0])
    assert r[0] == ev[0].ticker and len(r) == len(g.g.nodes)
    assert len(te.suggest_links(g, 3)) == 3


def test_learned_models_beat_naive_baselines(loaded):
    g, ev, _ = loaded
    res = kg.evaluate([kg.SectorOnly(), md.PersonalizedPageRank(), md.TransE()], g, ev, k=5)
    assert res.loc["Kişiselleştirilmiş PageRank", "nDCG@5"] > res.loc["Sektör okuması", "nDCG@5"]
    assert res.loc["TransE gömme", "nDCG@5"] > res.loc["Sektör okuması", "nDCG@5"]


def test_calibration_recovers_true_coefficients(loaded):
    """Bilinen katsayılarla üretilmiş gürültülü tepkilerden katsayılar geri bulunmalı."""
    g, _, _ = loaded
    true = {("supplier", "fwd"): 0.35, ("supplier", "bwd"): 0.80, ("competitor", "fwd"): -0.25,
            ("competitor", "bwd"): -0.25, ("owner", "bwd"): 0.90}
    rng = np.random.default_rng(1)
    reactions = []
    for u, v, d in g.g.edges(data=True):
        key = (d["kind"], d["direction"])
        if key not in true:
            continue
        scale = d["weight"] if not (d["kind"] == "owner" and d["direction"] == "fwd") else 1.0
        for _ in range(40):
            shock = rng.uniform(-1, 1)
            reactions.append(md.Reaction(u, v, shock, true[key] * shock * scale + rng.normal(0, 0.02)))
    tab = md.calibrate(g, reactions).set_index(["tür", "yön"])
    for key, beta in true.items():
        assert tab.loc[key, "öğrenilen"] == pytest.approx(beta, abs=0.02)
        assert tab.loc[key, "std_hata"] < 0.02
    md.apply_calibration(g, tab.reset_index())
    imp = {i.ticker: i.score for i in g.propagate("OTO1", -1.0, max_hops=1)}
    assert imp["DEMO"] == pytest.approx(-0.80, abs=0.03)          # öğrenilen müşteri→tedarikçi katsayısı


def test_calibration_keeps_rule_when_data_is_thin(loaded):
    g, _, _ = loaded
    tab = md.calibrate(g, [md.Reaction("OTO1", "DEMO", -1.0, -0.9)], min_obs=3)
    row = tab.iloc[0]
    assert row["öğrenilen"] == row["eski"] and row["n"] == 1


def test_paired_bootstrap(loaded):
    g, ev, _ = loaded
    res = md.paired_bootstrap(kg.Propagation(), kg.SectorOnly(), g, ev, n=2000)
    assert res["fark"] > 0 and res["GA_alt"] > 0 and res["p(fark<=0)"] < 0.05
    same = md.paired_bootstrap(kg.Propagation(), kg.Propagation(), g, ev, n=500)
    assert same["fark"] == 0 and same["GA_alt"] == 0 == same["GA_üst"]
