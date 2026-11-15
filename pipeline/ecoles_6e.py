"""Entrée en 6e des écoles : évaluations de 6e du collège de secteur, pour colorer le calque Écoles.

  python pipeline/ecoles_6e.py --out site/data

Lancé dans le workflow après l'assemblage des secteurs des collèges (pipeline/secteurs.py assembler), qui vient
lui-même après build.py. Pour chaque école publique, cherche la zone de collège public qui la contient
(data/secteurs/<dep>.geojson), et recopie dans data/ecoles/<dep>.geojson les dernières évaluations de 6e de ce
collège (colleges.geojson : eval_fr, eval_ma) sous les clés e6_fr et e6_ma.

Les couleurs de ces deux indicateurs reprennent l'échelle du calque Collèges (quantiles calculés sur tous les
collèges, comme dans app.js) : une école a la couleur de son collège de secteur. Elles sont écrites dans meta.json
(ecoles.couleurs.e6_fr / e6_ma), avec la couverture (ecoles.couverture) et l'année des évaluations.

Restent sans valeur : les écoles privées (pas de collège de secteur), celles des départements sans carte scolaire
nationale, celles dont le collège n'a pas d'évaluations publiées. Sans secteurs (assemblage en échec), le script
ne change rien : le calque garde ses deux autres indicateurs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
CLES = {"e6_fr": "eval_fr", "e6_ma": "eval_ma"}


def compact(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    out = Path(ap.parse_args().out)
    try:
        colleges = json.loads((out / "colleges.geojson").read_text(encoding="utf-8"))["features"]
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"entrée en 6e : données absentes ({e}), rien à faire")
        return 0
    evals = {f["properties"]["uai"]: f["properties"] for f in colleges}
    secteurs = sorted((out / "secteurs").glob("*.geojson"))
    if not secteurs:
        print("entrée en 6e : pas de secteurs des collèges, rien à faire")
        return 0
    zones = {}
    for f in secteurs:
        try:
            fs = json.loads(f.read_text(encoding="utf-8"))["features"]
        except (OSError, ValueError):
            continue
        geoms = [shape(z["geometry"]) for z in fs]
        zones[f.stem] = (STRtree(geoms), geoms, [z["properties"].get("uai") for z in fs])

    compte = {k: 0 for k in CLES}
    publiques, sans_zone = 0, 0
    for f in sorted((out / "ecoles").glob("*.geojson")):
        dep = f.stem
        doc = json.loads(f.read_text(encoding="utf-8"))
        arbre = zones.get(dep)
        modifie = False
        for e in doc["features"]:
            p = e["properties"]
            for k in CLES:
                p.pop(k, None)
            if p.get("secteur") != "public":
                continue
            publiques += 1
            if not arbre:
                continue
            pt = Point(e["geometry"]["coordinates"])
            uai = next((arbre[2][i] for i in arbre[0].query(pt) if arbre[1][i].covers(pt)), None)
            if not uai:
                sans_zone += 1
                continue
            c = evals.get(uai) or {}
            for k, src in CLES.items():
                if isinstance(c.get(src), (int, float)):
                    p[k] = c[src]
                    compte[k] += 1
                    modifie = True
        if modifie:
            f.write_text(compact(doc), encoding="utf-8")

    eco = meta.setdefault("ecoles", {})
    couleurs = eco.setdefault("couleurs", {})
    for k, src in CLES.items():
        v = pd.Series([f["properties"][src] for f in colleges if isinstance(f["properties"].get(src), (int, float))], dtype=float)
        if len(v) and compte[k]:
            couleurs[k] = {"stops": [round(float(v.quantile(q)), 2) for q in QUANTILES], "n": compte[k], "echelle": "colleges"}
    eco.setdefault("couverture", {}).update(compte)
    annees = sorted({str(f["properties"].get("annee_eval")) for f in colleges if f["properties"].get("annee_eval")})
    eco["entree6e"] = {"annee": annees[-1] if annees else None, "ecoles_publiques": publiques, "hors_secteur": sans_zone}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"entrée en 6e : {publiques} écoles publiques, {compte} avec les évaluations de leur collège de secteur, "
          f"{sans_zone} hors de toute zone dans un département qui a des secteurs ; {len(zones)} départements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
