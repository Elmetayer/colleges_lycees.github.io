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

print("######## Lille")
ds = get("https://www.data.gouv.fr/api/1/datasets/sectorisation-scolaire/")
print("dataset :", ds.get("title"), ds.get("organization", {}).get("name"), ds.get("license"), ds.get("last_modified"))
print(str(ds.get("description"))[:800])
for r in ds.get("resources", []):
    print("  ressource :", r.get("title"), r.get("format"), r.get("url"))

for r in ds.get("resources", []):
    u = r.get("url") or ""
    if "ogc" in (r.get("format") or "").lower() or "collections" in u or "features" in u:
        try:
            base = u.split("?")[0].rstrip("/")
            print("  essai", base)
            d = requests.get(base, headers=H, timeout=60, params={"f": "json"})
            print("   ", d.status_code, d.text[:1500])
        except Exception as e:
            print("   ", e)
