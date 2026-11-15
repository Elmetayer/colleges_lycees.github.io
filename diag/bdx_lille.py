import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
d = requests.get("https://data.lillemetropole.fr/geoserver/ogc/features/v1/collections", params={"f": "json"}, headers=H, timeout=120).json()
cols = d.get("collections", [])
print(len(cols), "collections")
for c in cols:
    t = (c.get("id", "") + " " + str(c.get("title", ""))).lower()
    if any(k in t for k in ("scol", "ecole", "école", "carte_sco", "secteur")):
        print(" ", c.get("id"), "|", c.get("title"))
u = "https://data.lillemetropole.fr/geoserver/ogc/features/v1/collections/ville_villeneuve_d_ascq:sectorisation_scolaire/items"
f = requests.get(u, params={"f": "json", "limit": 200}, headers=H, timeout=120).json()
print(f.get("numberMatched"), len(f.get("features", [])))
for x in f.get("features", [])[:80]:
    print("  ", json.dumps(x.get("properties"), ensure_ascii=False)[:300])
r = requests.get("https://www.data.gouv.fr/api/1/datasets/", params={"q": "sectorisation scolaire lille", "page_size": 20}, headers=H, timeout=60).json()
for ds in r.get("data", []):
    print("DG", ds["title"], "|", (ds.get("organization") or {}).get("name"), "|", ds.get("license"), "|", ds.get("last_modified"))
