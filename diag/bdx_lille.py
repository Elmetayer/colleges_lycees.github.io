import collections, json, requests
from shapely.geometry import Point, shape
H = {"User-Agent": "carte-scolaire-diag"}
ANN = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-annuaire-education/exports/json"
def get(url, **p):
    r = requests.get(url, params=p, headers=H, timeout=120); r.raise_for_status(); return r.json()
def annuaire(codes):
    a = get(ANN, where=f"code_commune in ({','.join(repr(c) for c in codes)}) and type_etablissement='Ecole'",
            select="identifiant_de_l_etablissement,nom_etablissement,statut_public_prive,ecole_maternelle,ecole_elementaire,latitude,longitude,etat,nom_commune")
    return [x for x in a if x.get("latitude") and x.get("statut_public_prive") == "Public" and (x.get("etat") or "OUVERT") == "OUVERT"]
def analyse(feats, ann, nomk):
    geoms = [shape(f["geometry"]).buffer(0) if f.get("geometry") else None for f in feats]
    c = collections.Counter(sum(1 for g in geoms if g and g.contains(Point(float(a["longitude"]), float(a["latitude"])))) for a in ann)
    print("  écoles publiques par nombre de zones :", dict(c))
    tailles = collections.Counter()
    for f, g in zip(feats, geoms):
        ins = [f"{a['nom_etablissement']} [{a.get('ecole_maternelle')}/{a.get('ecole_elementaire')}]" for a in ann if g and g.contains(Point(float(a["longitude"]), float(a["latitude"])))]
        tailles[len(ins)] += 1
        pr = {k: v for k, v in f["properties"].items() if k not in ("geo_shape", "geo_point_2d")}
        print("  -", json.dumps(pr, ensure_ascii=False)[:260], "=>", ins)
    print("  zones par nombre d'écoles dedans :", dict(sorted(tailles.items())))

print("######## Bordeaux")
B = "https://opendata.bordeaux-metropole.fr/api/explore/v2.1/catalog/datasets/se_ecole_s"
m = get(B); md = m.get("metas", {}).get("default", {}); print("META", {k: str(md.get(k))[:400] for k in ("title", "license", "publisher", "modified", "description")})
feats, off = [], 0
while True:
    d = get(B + "/records", limit=100, offset=off)
    for r in d["results"]:
        gs = r.pop("geo_shape", None); feats.append({"geometry": (gs or {}).get("geometry"), "properties": r})
    off += 100
    if len(d["results"]) < 100: break
print(len(feats), "zones ; insee :", collections.Counter(str(f["properties"].get("insee")) for f in feats).most_common(10))
ann = annuaire(["33063"]); print("annuaire Bordeaux :", len(ann))
analyse([f for f in feats if "33063" in str(f["properties"].get("insee"))], ann, "nom")
# autres jeux scolaires du portail
cat = get("https://opendata.bordeaux-metropole.fr/api/explore/v2.1/catalog/datasets", where="search('scolaire') or search('école')", limit=50, select="dataset_id,metas")
for x in cat.get("results", []):
    print("  jeu :", x["dataset_id"], "|", (x.get("metas") or {}).get("default", {}).get("title"), "|", (x.get("metas") or {}).get("default", {}).get("modified"))

print("######## Lille")
ds = get("https://www.data.gouv.fr/api/1/datasets/sectorisation-scolaire/")
print("dataset :", ds.get("title"), ds.get("organization", {}).get("name"), ds.get("license"), ds.get("last_modified"))
print(str(ds.get("description"))[:800])
for r in ds.get("resources", []):
    print("  ressource :", r.get("title"), r.get("format"), r.get("url"))
