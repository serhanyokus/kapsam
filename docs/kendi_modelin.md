# Kendi sıralama modelini KAPSAM'a eklemek

KAPSAM'daki bilgi grafiği katmanı, farklı sıralama modellerini aynı vakalar ve aynı metriklerle karşılaştırmak için tasarlandı. Bir model eklemek için tek bir metot yazman yeterli:

```python
from kapsam import graph as kg

class BenimModelim:
    name = "KG gömme + benzerlik"

    def rank(self, graph: kg.CompanyGraph, event: kg.Event) -> list[str]:
        """Olaydan etkilenmesi en olası şirketleri, en olasıdan başlayarak döndür."""
        emb = graph.embed(dim=4)                       # ya da kendi gömme yöntemin (TransE, node2vec, GNN…)
        sims = emb @ emb.loc[event.ticker]
        return [event.ticker] + list(sims.drop(event.ticker).sort_values(ascending=False).index)

g, events, _ = kg.load_with_disclosures("data/demo/graph_SENTETIK.json")
print(kg.evaluate([kg.DirectOnly(), kg.SectorOnly(), kg.Propagation(), BenimModelim()], g, events, k=5))
```

## Kullanılabilir yapı taşları

| İşlev | Ne verir |
|---|---|
| `graph.g` | `networkx.MultiDiGraph`; kenarlarda `kind`, `coef` (iletim katsayısı), `weight`, `evidence` |
| `graph.propagate(ticker, shock)` | Açıklamalı etki yayılımı |
| `graph.embed(dim)` | Spektral gömme (yakınlık) |
| `graph.role_features()` | Rol özellikleri (benzer şirket için) |
| `graph.similar(ticker, k, features)` | Rol + finansal profil benzerliği |
| `kg.evaluate(...)` | P@k, R@k, MAP, nDCG@k, MRR |
| `kg.event_study(...)` | Piyasa modeli, anormal getiri, CAR, t istatistiği |

## Kendi ağını yüklemek

`data/demo/graph_SENTETIK.json` ile aynı yapıda bir JSON hazırla (`companies`, `relations`, isteğe bağlı `disclosures` ve `events`). Panodaki "İlişki ağı" sekmesinden yükleyebilir ya da komut satırında `--graph dosya.json` ile verebilirsin.

İlişki türleri: `supplier` (kaynak, hedefin tedarikçisi), `owner` (kaynak, hedefin ortağı; `weight` = pay oranı), `group`, `competitor`, `peer`.

## Hazır modeller ve istatistiksel karşılaştırma

`kapsam/models.py` içinde kişiselleştirilmiş PageRank ve TransE hazır. İki modeli karşılaştırırken tek bir ortalama yetmez; farkın şans eseri olmadığını göster:

```python
from kapsam import models as md
md.paired_bootstrap(BenimModelim(), md.PersonalizedPageRank(), g, events, metric="ndcg", k=5)
# {'fark': ..., 'GA_alt': ..., 'GA_üst': ..., 'p(fark<=0)': ...}
```

Güven aralığının alt sınırı sıfırın üstündeyse modelin daha iyi olduğunu söyleyebilirsin.

## Katsayıları veriden öğrenmek

Geçmiş olaylarda komşu şirketlerin CAR değerlerini `md.Reaction(kaynak, hedef, şok, car)` olarak topla, sonra şunu çalıştır:

```python
tab = md.calibrate(g, reactions)      # ilişki türü × yön başına katsayı, standart hata, gözlem sayısı
md.apply_calibration(g, tab)          # yayılım modeli artık öğrenilen katsayılarla çalışır
```

## Gerçek veride doğrulama

1. Geçmiş KAP olaylarını (tarih, şirket, yön) listele.
2. Her olay için modelin önerdiği ilk k şirketi al.
3. `kg.event_study` ile bu şirketlerin olay çevresindeki CAR değerlerini hesapla.
4. Önerilen şirketlerde ortalama |CAR| ve anlamlılık oranı, rastgele seçilen şirketlerden yüksekse model işe yarıyor demektir.

Yatırım tavsiyesi değildir: sıralama, analistin önce hangi şirkete bakması gerektiğini gösterir.
