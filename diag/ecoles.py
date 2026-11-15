"""Diagnostic 7c : secteurs des écoles publiés par les villes (portails Explore et data.gouv.fr)."""
import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
def get(url, **p):
    try:
        r = requests.get(url, params=p, headers=H, timeout=60); r.raise_for_status(); return r.json()
    except Exception as e:
        return {"_erreur": str(e)[:120]}
PORTAILS = {
    "Toulouse": "https://data.toulouse-metropole.fr", "Bordeaux": "https://opendata.bordeaux-metropole.fr",
    "Rennes": "https://data.rennesmetropole.fr", "Nantes": "https://data.nantesmetropole.fr",
    "Strasbourg": "https://data.strasbourg.eu", "Montpellier": "https://data.montpellier3m.fr",
    "Lille MEL": "https://opendata.lillemetropole.fr", "Angers": "https://data.angers.fr",
    "Orléans": "https://data.orleans-metropole.fr", "Clermont": "https://opendata.clermontmetropole.eu",
    "Nice": "https://opendata.nicecotedazur.org", "Grenoble": "https://data.metropolegrenoble.fr",
    "Saint-Nazaire": "https://data.agglo-carene.fr", "Hauts-de-Seine": "https://opendata.hauts-de-seine.fr",
    "Seine-Saint-Denis": "https://data.seine-saint-denis.fr", "Brest": "https://data.brest-metropole.fr",
    "Le Mans": "https://data.lemans-metropole.fr", "Tours": "https://data.tours-metropole.fr",
    "Metz": "https://data.eurometropolemetz.eu", "Dijon": "https://data.metropole-dijon.fr",
    "Lyon": "https://data.grandlyon.com", "Marseille": "https://data.ampmetropole.fr",
    "Reims": "https://data.grandreims.fr", "Le Havre": "https://data.lehavreseinemetropole.fr",
}
for ville, base in PORTAILS.items():
    vus = set()
    for q in ["secteur scolaire", "carte scolaire", "périmètre scolaire", "sectorisation"]:
        d = get(f"{base}/api/explore/v2.1/catalog/datasets", where=f'search("{q}")', limit=20, select="dataset_id")
        if "_erreur" in d:
            print(f"{ville:18} | portail : {d['_erreur']}"); break
        for ds in d.get("results", []):
            i = ds["dataset_id"]
            if i in vus: continue
            vus.add(i)
            m = get(f"{base}/api/explore/v2.1/catalog/datasets/{i}")
            mm = (m.get("metas") or {}).get("default", {})
            champs = [f["name"] for f in m.get("fields", [])]
            geo = any(f.get("type") == "geo_shape" for f in m.get("fields", []))
            ex = get(f"{base}/api/explore/v2.1/catalog/datasets/{i}/records", limit=1)
            r0 = (ex.get("results") or [{}])[0]
            r0 = {k: (v if not isinstance(v, dict) else "…") for k, v in r0.items()}
            print(f"{ville:18} | {i} | {mm.get('title')} | {mm.get('records_count')} | maj {str(mm.get('modified'))[:10]} | polygones={geo} | licence {mm.get('license')}")
            print(f"{'':18}   champs {champs[:25]}")
            print(f"{'':18}   ex {json.dumps(r0, ensure_ascii=False)[:400]}")
        else:
            continue
        break
    if not vus: print(f"{ville:18} | rien trouvé")

print("\n=== data.gouv.fr")
vus = set()
for q in ["secteurs scolaires ecoles", "carte scolaire ecoles", "perimetres scolaires", "sectorisation scolaire", "secteurs scolaires maternelles elementaires", "secteur scolaire 1er degre", "zones de recrutement ecoles"]:
    d = get("https://www.data.gouv.fr/api/1/datasets/", q=q, page_size=50)
    for ds in d.get("data", []):
        if ds["id"] in vus: continue
        vus.add(ds["id"])
        fm = sorted({(r.get("format") or "?").lower() for r in ds.get("resources", [])})
        org = (ds.get("organization") or {}).get("name")
        print(f"  {ds['title'][:80]} | {org} | {fm} | maj {ds.get('last_update', '')[:10]} | {ds.get('page')}")
