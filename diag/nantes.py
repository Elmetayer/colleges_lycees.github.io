import requests, time, json, collections
H = {"User-Agent": "carte-scolaire-diag"}
B = "https://data.nantesmetropole.fr/api/explore/v2.1/catalog/datasets/244400404_perimetres-scolaires-nantes"
def t(url, **p):
    t0 = time.time()
    try:
        r = requests.get(url, params=p, headers=H, timeout=300); 
        print(f"{r.status_code} {len(r.content)} o {time.time()-t0:.0f}s {url.split('/')[-1]} {p}")
        return r
    except Exception as e:
        print("ERR", str(e)[:150], f"{time.time()-t0:.0f}s", p)
r = t(B + "/records", limit=100, select="gid,idobj,lib,type,codcom,libcom")
if r is not None and r.ok:
    rs = r.json()["results"]; print(collections.Counter(x["type"] for x in rs))
    for x in rs: print("  ", json.dumps(x, ensure_ascii=False))
t(B + "/records", limit=5)
t(B + "/exports/csv", select="lib")
t(B + "/exports/geojson")
t(B + "/exports/shp")
d = requests.get("https://www.data.gouv.fr/api/1/datasets/", params={"q": "perimetres scolaires nantes"}, headers=H, timeout=60).json()
for ds in d.get("data", [])[:5]:
    print(ds["title"], [(x.get("format"), x.get("url")) for x in ds.get("resources", [])][:6])
