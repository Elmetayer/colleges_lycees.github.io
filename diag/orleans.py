import json, requests
H = {"User-Agent": "carte-scolaire-diag"}
ANN = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-annuaire-education/exports/json"
for q in ["ROLLAND", "GUERNAZELLES", "Rolland", "Guernazelles"]:
    try:
        r = requests.get(ANN, params={"where": f"code_departement='045' and nom_etablissement like '%{q}%'",
                                      "select": "identifiant_de_l_etablissement,nom_etablissement,type_etablissement,statut_public_prive,nom_commune,adresse_1,etat,date_fermeture,latitude,longitude"}, headers=H, timeout=90)
        print(q, r.status_code, json.dumps(r.json(), ensure_ascii=False)[:1500])
    except Exception as e:
        print(q, e)
B = "https://data.orleans-metropole.fr/api/explore/v2.1/catalog/datasets/"
for jeu in ["administratifscol_sect_mater", "administratifscol_sect_elem"]:
    d = requests.get(B + jeu + "/records", params={"where": "si_numero in ('0231','0262')", "limit": 10}, headers=H, timeout=90).json()
    for x in d.get("results", []):
        x.pop("geo_shape", None)
        print(jeu, json.dumps(x, ensure_ascii=False))
for base, jeu in [("https://data.orleans-metropole.fr", "administratifscol_sect_mater"), ("https://data.orleans-metropole.fr", "administratifscol_sect_elem"),
                  ("https://opendata.clermontmetropole.eu", "secteurs-scolaires-des-ecoles-vcf"), ("https://data.nantesmetropole.fr", "244400404_perimetres-scolaires-nantes")]:
    m = requests.get(f"{base}/api/explore/v2.1/catalog/datasets/{jeu}", headers=H, timeout=90).json()
    meta = (m.get("metas") or {}).get("default", {})
    print(jeu, {k: meta.get(k) for k in ("title", "license", "license_url", "publisher", "modified", "data_processed", "description")})
