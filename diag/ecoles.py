"""Diagnostic temporaire (jalon 7b) : secteurs des écoles de Paris."""
import io, json, requests, pandas as pd
from shapely.geometry import shape, Point
from shapely.ops import unary_union
H = {"User-Agent": "carte-scolaire-diag"}
PA = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
EX = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
AN = "2026-2027"
def geo(i, where):
    return requests.get(f"{PA}/{i}/exports/geojson", params={"where": where}, headers=H, timeout=180).json()

# Écoles de Paris de l'annuaire national (UAI, nom, position, niveau)
r = requests.get(f"{EX}/fr-en-annuaire-education/exports/csv", params={"delimiter": ";", "where": "type_etablissement='Ecole' and code_departement='075'",
    "select": "identifiant_de_l_etablissement,nom_etablissement,statut_public_prive,adresse_1,ecole_maternelle,ecole_elementaire,latitude,longitude,etat"}, headers=H, timeout=180)
an = pd.read_csv(io.StringIO(r.text), sep=";", dtype=str)
an = an[(an.statut_public_prive == "Public")]
an["pt"] = [Point(float(x), float(y)) if isinstance(x, str) and isinstance(y, str) else None for x, y in zip(an.longitude, an.latitude)]
print("annuaire Paris public :", len(an), "maternelle seule", int(((an.ecole_maternelle == "1") & (an.ecole_elementaire == "0")).sum()),
      "élémentaire seule", int(((an.ecole_maternelle == "0") & (an.ecole_elementaire == "1")).sum()), "primaires", int(((an.ecole_maternelle == "1") & (an.ecole_elementaire == "1")).sum()))

paris = None
for niv in ("ecoles-elementaires", "maternelles"):
    print(f"\n######## {niv}")
    meta = requests.get(f"{PA}/secteurs-scolaires-{niv}", headers=H, timeout=60).json()
    print("champs secteurs :", [(f["name"], f["type"]) for f in meta["fields"]])
    print("licence :", meta["metas"]["default"].get("license"), "| modifié", meta["metas"]["default"].get("modified"))
    g = geo(f"secteurs-scolaires-{niv}", f"annee_scol='{AN}'")
    fs = g["features"]
    print("secteurs", AN, ":", len(fs))
    for f in fs[:3]:
        print("  ex :", json.dumps({k: v for k, v in f["properties"].items()}, ensure_ascii=False)[:600], "| géométrie", f["geometry"]["type"])
    props = pd.DataFrame([f["properties"] for f in fs])
    n_etab = props[[c for c in props.columns if c.startswith("lib_etab")]].notna().sum(axis=1)
    print("  écoles citées par secteur :", n_etab.value_counts().sort_index().to_dict())
    print("  exemples à 2+ écoles :", props[n_etab >= 2].head(5).to_dict("records"))
    geoms = [shape(f["geometry"]).buffer(0) for f in fs]
    u = unary_union(geoms)
    somme = sum(x.area for x in geoms)
    print(f"  surface union {u.area:.6f}, somme {somme:.6f} (chevauchements {100 * (somme - u.area) / u.area:.2f} %)")
    if paris is None:
        c = requests.get(f"{PA}/arrondissements/exports/geojson", headers=H, timeout=60).json()
        paris = unary_union([shape(f["geometry"]) for f in c["features"]])
    print(f"  couverture de Paris : {100 * u.intersection(paris).area / paris.area:.2f} %")
    # établissements (points) de la même année
    meta2 = requests.get(f"{PA}/etablissements-scolaires-{niv}", headers=H, timeout=60).json()
    print("champs établissements :", [f["name"] for f in meta2["fields"]])
    e = geo(f"etablissements-scolaires-{niv}", f"annee_scol='{AN}'")["features"]
    print("établissements", AN, ":", len(e), "ex :", json.dumps(e[0]["properties"], ensure_ascii=False)[:500] if e else None)
    # rattachement par proximité à l'annuaire
    mat = niv == "maternelles"
    cand = an[an.ecole_maternelle.eq("1") if mat else an.ecole_elementaire.eq("1")]
    dists = []
    for f in e:
        if not f.get("geometry"): continue
        p = shape(f["geometry"])
        d = cand.pt.map(lambda q: p.distance(q) * 111000 if q is not None else 1e9)
        i = d.idxmin()
        dists.append((d[i], f["properties"].get("libelle") or f["properties"].get("lib_etab"), cand.loc[i, "nom_etablissement"], cand.loc[i, "identifiant_de_l_etablissement"]))
    dd = pd.Series([x[0] for x in dists])
    print("  distance au plus proche (m) : quantiles", dd.quantile([.5, .9, .95, .99]).round(1).to_dict(), "max", round(dd.max(), 1), "| > 50 m :", int((dd > 50).sum()))
    for x in sorted(dists, reverse=True)[:6]: print("   loin :", x)
    # Les noms des secteurs se retrouvent-ils dans les établissements ?
    noms_e = {(f["properties"].get("libelle") or "") for f in e}
    noms_s = set(props[[c for c in props.columns if c.startswith("lib_etab")]].stack().dropna())
    print("  noms des secteurs absents des établissements :", len(noms_s - noms_e), list(noms_s - noms_e)[:8])
