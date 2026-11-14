"""Diagnostic temporaire (jalon 7) : sources disponibles pour les écoles."""
import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
EX = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
def get(url, **p):
    try:
        r = requests.get(url, params=p, headers=H, timeout=60); r.raise_for_status(); return r.json()
    except Exception as e:
        print("  ERREUR", url, e); return None

print("=== 1. Catalogue data.education.gouv.fr : jeux contenant 'ecole' ou 'premier degre'")
for q in ['search("ecole")', 'search("premier degre")', 'search("CP")', 'search("evaluations")']:
    off = 0
    while True:
        d = get(EX, where=q, limit=100, offset=off, select="dataset_id")
        if not d: break
        for ds in d["results"]:
            print(" ", q, "|", ds["dataset_id"])
        off += 100
        if off >= d["total_count"] or off >= 300: break

def detail(i):
    d = get(f"{EX}/{i}")
    if not d: return
    m = d.get("metas", {}).get("default", {})
    print(f"\n--- {i} | {m.get('title')} | {m.get('records_count')} lignes | modifié {m.get('modified')}")
    print("   champs:", [f["name"] for f in d.get("fields", [])])
    r = get(f"{EX}/{i}/records", limit=2)
    if r:
        for x in r["results"]: print("   ex:", json.dumps(x, ensure_ascii=False)[:900])

print("\n=== 2. Détail de jeux candidats")
for i in ["fr-en-ips-ecoles-ap2022", "fr-en-ips_ecoles", "fr-en-ecoles-effectifs-nb_classes",
          "fr-en-annuaire-education", "fr-en-evaluations-nationales-cp-ce1-etablissement",
          "fr-en-reussite-evaluations-repere-cp-ce1", "fr-en-ips-ecoles-ap2023"]:
    detail(i)
# Annuaire : combien d'écoles, et quelles colonnes utiles
r = get(f"{EX}/fr-en-annuaire-education/records", limit=0, where="type_etablissement='Ecole'")
print("\nAnnuaire, écoles :", r and r.get("total_count"))
r = get(f"{EX}/fr-en-annuaire-education/records", select="type_etablissement, count(*) as n", group_by="type_etablissement", limit=50)
print("Annuaire par type :", r and r.get("results"))
r = get(f"{EX}/fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre/records", select="nature_uai_libe, count(*) as n", group_by="nature_uai_libe", limit=60)
print("Géolocalisation par nature :", r and r.get("results"))

print("\n=== 3. data.gouv.fr : secteurs scolaires des écoles publiés")
seen = set()
for q in ["secteurs scolaires ecoles", "carte scolaire ecoles", "perimetres scolaires", "secteurs scolaires maternelles elementaires", "sectorisation scolaire"]:
    d = get("https://www.data.gouv.fr/api/1/datasets/", q=q, page_size=40)
    if not d: continue
    for ds in d["data"]:
        if ds["id"] in seen: continue
        seen.add(ds["id"])
        fmts = sorted({(r.get("format") or "?").lower() for r in ds.get("resources", [])})
        org = (ds.get("organization") or {}).get("name")
        print(f"  {ds['title'][:90]} | {org} | {fmts} | maj {ds.get('last_update','')[:10]} | {ds['id']}")

print("\n=== 4. Paris : opendata.paris.fr")
d = get("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets", where='search("secteurs scolaires")', limit=30, select="dataset_id")
for ds in (d or {}).get("results", []):
    detail_url = f"https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/{ds['dataset_id']}"
    m = get(detail_url)
    if m:
        mm = m["metas"]["default"]
        print(f"  {ds['dataset_id']} | {mm.get('title')} | {mm.get('records_count')} | {mm.get('modified')}")
        print("    champs:", [f["name"] for f in m.get("fields", [])])
