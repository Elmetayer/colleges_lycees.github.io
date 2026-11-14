"""Diagnostic temporaire (jalon 7), 3e passage : données réelles pour la maquette de fiche école."""
import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
EX = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
def get(url, **p):
    try:
        r = requests.get(url, params=p, headers=H, timeout=90); r.raise_for_status(); return r.json()
    except Exception as e:
        print("  ERREUR", url, e); return None
def rec(i, **p):
    r = get(f"{EX}/{i}/records", **p); return (r or {}).get("results", [])
cands = rec("fr-en-annuaire-education", where="type_etablissement='Ecole' and code_commune='75115' and search(adresse_1, 'Saida')", limit=10)
cands += rec("fr-en-annuaire-education", where="type_etablissement='Ecole' and code_departement='092' and nom_commune='Meudon' and statut_public_prive='Privé'", limit=3)
for a in cands:
    u = a["identifiant_de_l_etablissement"]
    print("\n==========", u)
    print(json.dumps({k: a.get(k) for k in ["nom_etablissement","statut_public_prive","type_contrat_prive","adresse_1","code_postal","nom_commune","ecole_maternelle","ecole_elementaire","appartenance_education_prioritaire","restauration","ulis","nom_circonscription","date_ouverture","web","telephone","latitude","longitude"]}, ensure_ascii=False))
    for r in rec("fr-en-ips-ecoles-ap2022", where=f"uai='{u}'", order_by="rentree_scolaire", limit=10):
        print("  IPS", r["rentree_scolaire"], r["ips"], "dep", r["ips_departemental_public"], r["ips_departemental_prive"], r["ips_departemental"], "acad", r["ips_academique"], "nat", r["ips_national_public"], r["ips_national_prive"], r["ips_national"])
    for r in rec("fr-en-ips_ecoles_v2", where=f"uai='{u}'", order_by="rentree_scolaire", limit=10):
        print("  IPS ancien", r["rentree_scolaire"], r["ips"])
    for r in rec("fr-en-ecoles-effectifs-nb_classes", where=f"numero_ecole='{u}'", order_by="rentree_scolaire", limit=20):
        print("  EFF", r["rentree_scolaire"][:4], "classes", r["nombre_total_classes"], "élèves", r["nombre_total_eleves"], "pre", r["nombre_eleves_preelementaire_hors_ulis"], "elem", r["nombre_eleves_elementaire_hors_ulis"], "CP-CM2", [r[f"nombre_eleves_{n}_hors_ulis"] for n in ["cp","ce1","ce2","cm1","cm2"]], "ulis", r["nombre_eleves_ulis"], "rep", r["rep"], r["rep_plus"])
    for r in rec("fr-en-taille-moyenne-classes-premier-degre", where=f"uai='{u}'", order_by="annee", limit=10):
        print("  TAILLE", r["annee"], {k: (round(v,1) if isinstance(v,(int,float)) else v) for k,v in r.items() if k.startswith("esurc")}, r["code_circonscription"])
# distribution IPS des écoles de Paris (publiques) 2024-2025 pour la médiane et un rang
r = rec("fr-en-ips-ecoles-ap2022", where="code_du_departement='075' and rentree_scolaire='2024-2025'", select="ips, secteur", limit=100, offset=0)
vals=[]; off=0
while True:
    rr = rec("fr-en-ips-ecoles-ap2022", where="code_du_departement='075' and rentree_scolaire='2024-2025'", select="ips,secteur", limit=100, offset=off)
    if not rr: break
    vals += rr; off += 100
    if off > 2000: break
pub = sorted(float(x["ips"]) for x in vals if x["secteur"]=="public" and x["ips"])
print("\nParis 2024-2025 : écoles avec IPS", len(vals), "publiques", len(pub), "médiane publique", pub[len(pub)//2] if pub else None, "min/max", pub[:1], pub[-1:])
print("déciles publics", [pub[int(len(pub)*k/10)] for k in range(1,10)] if pub else None)
