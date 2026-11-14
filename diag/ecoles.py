"""Diagnostic temporaire (jalon 7), 4e passage : rangs IPS, médianes, collège de secteur, école hors contrat."""
import io, json, requests, pandas as pd
from shapely.geometry import shape, Point
H = {"User-Agent": "carte-scolaire-diag"}
EX = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
r = requests.get(f"{EX}/fr-en-ips-ecoles-ap2022/exports/csv", params={"delimiter": ";", "select": "rentree_scolaire,code_du_departement,academie,uai,secteur,ips"}, headers=H, timeout=300)
df = pd.read_csv(io.StringIO(r.text), sep=";", dtype=str)
df["ips"] = pd.to_numeric(df["ips"], errors="coerce")
df = df[df.ips.notna()]
print("lignes", len(df), "départements exemples", sorted(df.code_du_departement.unique())[:5], sorted(df.code_du_departement.unique())[-12:])
met = df[~df.code_du_departement.str.lstrip("0").str[:2].isin(["97", "98"]) & ~df.code_du_departement.str.startswith("97")].copy()
print("métropole", len(met), "par année", met.groupby("rentree_scolaire").size().to_dict())
met["rang"] = met.groupby("rentree_scolaire")["ips"].rank(ascending=False, method="min")
met["nb"] = met.groupby("rentree_scolaire")["ips"].transform("count")
met["rang_acad"] = met.groupby(["rentree_scolaire", "academie"])["ips"].rank(ascending=False, method="min")
met["nb_acad"] = met.groupby(["rentree_scolaire", "academie"])["ips"].transform("count")
med = met.groupby(["rentree_scolaire", "academie"])["ips"].median()
for u in ["0750602X", "0921106C"]:
    s = met[met.uai == u].sort_values("rentree_scolaire")
    for _, x in s.iterrows():
        print(u, x.rentree_scolaire, x.academie, x.ips, "rang", int(x.rang), "/", int(x.nb), "acad", int(x.rang_acad), "/", int(x.nb_acad), "médiane acad", med[(x.rentree_scolaire, x.academie)])
print("médianes France métro", met.groupby("rentree_scolaire")["ips"].median().to_dict())

# Collège de secteur (Paris, 2026-2027) pour l'école de la Saïda
PA = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/secteurs-scolaires-colleges"
g = requests.get(f"{PA}/exports/geojson", params={"where": "annee_scol='2026-2027'"}, headers=H, timeout=120).json()
pt = Point(2.2955289233016583, 48.831997287153136)
for f in g["features"]:
    if f["geometry"] and shape(f["geometry"]).buffer(0).contains(pt):
        print("collège de secteur Saïda :", {k: f["properties"].get(k) for k in ["libelle", "lib_etab_1", "lib_etab_2", "adr_etab_1", "annee_scol"]})
an = requests.get(f"{EX}/fr-en-annuaire-education/records", params={"where": "type_etablissement='Collège' and code_postal='75015' and statut_public_prive='Public'", "select": "identifiant_de_l_etablissement,nom_etablissement,adresse_1", "limit": 40}, headers=H, timeout=60).json()
for x in an["results"]: print("  collège 15e :", x)

# Écoles hors contrat : exemples
hc = requests.get(f"{EX}/fr-en-annuaire-education/records", params={"where": "type_etablissement='Ecole' and type_contrat_prive='HORS CONTRAT' and code_departement='075'", "select": "identifiant_de_l_etablissement,nom_etablissement,adresse_1,code_postal,nom_commune,ecole_maternelle,ecole_elementaire,date_ouverture", "limit": 15}, headers=H, timeout=60).json()
for x in hc["results"]: print("HC", x)
