import requests
H={"User-Agent":"carte-scolaire-diag"}; EX="https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
def n(i,w): r=requests.get(f"{EX}/{i}/records",params={"where":w,"limit":0},headers=H,timeout=60).json(); return r.get("total_count")
print("Lily effectifs", n("fr-en-ecoles-effectifs-nb_classes","numero_ecole='0755913V'"), "taille", n("fr-en-taille-moyenne-classes-premier-degre","uai='0755913V'"), "ips", n("fr-en-ips-ecoles-ap2022","uai='0755913V'"))
for i,c in [("fr-en-ecoles-effectifs-nb_classes","secteur"),("fr-en-taille-moyenne-classes-premier-degre","libelle_secteur")]:
    r=requests.get(f"{EX}/{i}/records",params={"select":f"{c}, count(*) as n","group_by":c,"limit":20},headers=H,timeout=60).json(); print(i, r.get("results"))
