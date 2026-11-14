"""Diagnostic temporaire (jalon 7), 2e passage."""
import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
EX = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
PA = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
def get(url, **p):
    try:
        r = requests.get(url, params=p, headers=H, timeout=90); r.raise_for_status(); return r.json()
    except Exception as e:
        print("  ERREUR", url, e); return None
def grp(base, i, champ, where=None):
    p = dict(select=f"{champ}, count(*) as n", group_by=champ, limit=100)
    if where: p["where"] = where
    r = get(f"{base}/{i}/records", **p)
    print(f"  {i} par {champ}{' ('+where+')' if where else ''} :", r and [(x[champ], x["n"]) for x in r["results"]])
def detail(base, i, n=1, **p):
    d = get(f"{base}/{i}")
    if d:
        m = d["metas"]["default"]
        print(f"\n--- {i} | {m.get('title')} | {m.get('records_count')} | {m.get('modified')}")
        print("   champs:", [f["name"] for f in d.get("fields", [])])
    r = get(f"{base}/{i}/records", limit=n, **p)
    for x in (r or {}).get("results", []):
        s = {k: (v if k not in ("geo_shape",) else str(v)[:200]) for k, v in x.items()}
        print("   ex:", json.dumps(s, ensure_ascii=False)[:1500])

print("=== IPS écoles")
grp(EX, "fr-en-ips-ecoles-ap2022", "rentree_scolaire")
grp(EX, "fr-en-ips-ecoles-ap2022", "secteur", "rentree_scolaire='2024-2025'")
for i in ["fr-en-ips_ecoles_v2", "donnees-ips-ecoles"]:
    detail(EX, i)
print("\n=== Effectifs par école")
grp(EX, "fr-en-ecoles-effectifs-nb_classes", "rentree_scolaire")
grp(EX, "fr-en-ecoles-effectifs-nb_classes", "secteur", "rentree_scolaire='2025'")
print("\n=== Éducation prioritaire / autres")
detail(EX, "fr-en-ecoles-ep")
detail(EX, "fr-en-evaluations_nationales_ce1_departement")
detail(EX, "fr-en-taille-moyenne-classes-premier-degre")
grp(EX, "fr-en-annuaire-education", "statut_public_prive", "type_etablissement='Ecole'")
grp(EX, "fr-en-annuaire-education", "type_contrat_prive", "type_etablissement='Ecole'")
grp(EX, "fr-en-annuaire-education", "etat", "type_etablissement='Ecole'")
r = get(f"{EX}/fr-en-annuaire-education/records", where="type_etablissement='Ecole' and ecole_maternelle=1 and ecole_elementaire=1", limit=0)
print("  écoles primaires (maternelle+élémentaire) :", r and r["total_count"])
r = get(f"{EX}/fr-en-annuaire-education/records", where="type_etablissement='Ecole' and ecole_maternelle=1 and ecole_elementaire=0", limit=0)
print("  maternelles seules :", r and r["total_count"])

print("\n=== Paris")
for i in ["secteurs-scolaires-ecoles-elementaires", "secteurs-scolaires-maternelles", "etablissements-scolaires-ecoles-elementaires", "etablissements-scolaires-maternelles"]:
    grp(PA, i, "annee_scol")
    grp(PA, i, "type_etabl")
detail(PA, "secteurs-scolaires-ecoles-elementaires", 3, order_by="annee_scol desc")
detail(PA, "etablissements-scolaires-ecoles-elementaires", 3, order_by="annee_scol desc")
r = get(f"{PA}/secteurs-scolaires-ecoles-elementaires/records", limit=0, where="lib_etab_2 is not null", order_by="annee_scol desc")
print("  secteurs élémentaires avec 2+ écoles :", r and r["total_count"])
