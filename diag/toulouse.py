import collections, json, requests
from shapely.geometry import Point, shape
H = {"User-Agent": "carte-scolaire-diag"}
ANN = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-annuaire-education/exports/json"
P = "https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets"
def get(url, **p):
    r = requests.get(url, params=p, headers=H, timeout=120); r.raise_for_status(); return r.json()
m = get(P + "/9121_bassin_scolaire"); md = m.get("metas", {}).get("default", {})
print("META", {k: str(md.get(k))[:600] for k in ("title", "license", "publisher", "modified", "description")})
d = get(P + "/9121_bassin_scolaire/records", limit=100)
feats = [{"geometry": (r.pop("geo_shape", None) or {}).get("geometry"), "properties": r} for r in d["results"]]
ann = get(ANN, where="code_commune='31555' and type_etablissement='Ecole'", select="identifiant_de_l_etablissement,nom_etablissement,statut_public_prive,ecole_maternelle,ecole_elementaire,latitude,longitude,etat")
ann = [a for a in ann if a.get("latitude") and a.get("statut_public_prive") == "Public" and (a.get("etat") or "OUVERT") == "OUVERT"]
print("annuaire :", len(ann))
for f in feats:
    g = shape(f["geometry"]).buffer(0)
    ins = [a["nom_etablissement"] for a in ann if g.contains(Point(float(a["longitude"]), float(a["latitude"])))]
    p = f["properties"]; p.pop("geo_point_2d", None)
    print("-", p.get("nom_bassin_scolaire"), "|", p.get("ecoles_du_bassin_scolaire"), "|", len(ins), "écoles dans la zone :", ins[:14])
for q in ["scolaire", "ecole", "école", "secteur", "carte scolaire", "périmètre"]:
    try:
        c = get(P, where=f'search("{q}")', limit=40, select="dataset_id")
        print("Q", q, [x["dataset_id"] for x in c.get("results", [])])
    except Exception as e:
        print("Q", q, str(e)[:150])
