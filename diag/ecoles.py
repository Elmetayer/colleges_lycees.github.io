"""Diagnostic 7c (2) : contenu des secteurs des villes et écoles de l'annuaire contenues dans chaque zone."""
import collections, json, requests
from shapely.geometry import Point, shape

H = {"User-Agent": "carte-scolaire-diag"}
ANNUAIRE = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-annuaire-education/exports/json"
JEUX = {
    "Nantes": ("https://data.nantesmetropole.fr", ["244400404_perimetres-scolaires-nantes"], ["44109"]),
}


def get(url, **p):
    r = requests.get(url, params=p, headers=H, timeout=180)
    r.raise_for_status()
    return r.json()


for ville, (base, jeux, communes) in JEUX.items():
    print(f"\n######## {ville}")
    try:
        ann = get(ANNUAIRE, where=f"code_commune in ({','.join(repr(c) for c in communes)}) and type_etablissement='Ecole'",
                  select="identifiant_de_l_etablissement,nom_etablissement,statut_public_prive,ecole_maternelle,ecole_elementaire,latitude,longitude,adresse_1,etat")
    except Exception as e:
        print("annuaire :", str(e)[:200]); continue
    ann = [a for a in ann if a.get("latitude") and a.get("statut_public_prive") == "Public" and (a.get("etat") or "OUVERT") == "OUVERT"]
    print(f"annuaire : {len(ann)} écoles publiques ouvertes")
    for jeu in jeux:
        try:
            feats, off = [], 0
            while True:
                d = get(f"{base}/api/explore/v2.1/catalog/datasets/{jeu}/records", limit=100, offset=off)
                rs = d["results"]
                for r in rs:
                    gs = r.pop("geo_shape", None); r.pop("geo_point_2d", None)
                    feats.append({"type": "Feature", "geometry": (gs or {}).get("geometry"), "properties": r})
                off += 100
                if len(rs) < 100: break
            gj = {"features": feats}
        except Exception as e:
            print(jeu, ":", str(e)[:200]); continue
        feats = gj["features"]
        print(f"\n=== {jeu} : {len(feats)} zones")
        for k in feats[0]["properties"]:
            vals = collections.Counter(str(f["properties"].get(k))[:40] for f in feats)
            if len(vals) <= 12:
                print(f"  {k}: {dict(vals)}")
        dans_aucune, compte = [], collections.Counter()
        geoms = []
        for f in feats:
            try:
                geoms.append(shape(f["geometry"]).buffer(0))
            except Exception:
                geoms.append(None)
        for a in ann:
            p = Point(float(a["longitude"]), float(a["latitude"]))
            n = sum(1 for g in geoms if g is not None and g.contains(p))
            compte[n] += 1
            if n == 0:
                dans_aucune.append(a["nom_etablissement"])
        print(f"  écoles publiques par nombre de zones contenantes : {dict(compte)} ; hors zones : {dans_aucune[:12]}")
        for f, g in list(zip(feats, geoms)):
            pr = {k: v for k, v in f["properties"].items() if not isinstance(v, (dict, list)) or k == "type"}
            dedans = [f"{a['nom_etablissement']} [{'M' if a['ecole_maternelle']=='1' else ''}{'E' if a['ecole_elementaire']=='1' else ''}]"
                      for a in ann if g is not None and g.contains(Point(float(a["longitude"]), float(a["latitude"])))]
            print(f"  - {json.dumps(pr, ensure_ascii=False)[:230]}  =>  {dedans}")
