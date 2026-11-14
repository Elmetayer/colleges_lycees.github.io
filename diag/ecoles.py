import io, requests, pandas as pd, re
H={"User-Agent":"carte-scolaire-diag"}; EX="https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
r=requests.get(f"{EX}/fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre/exports/csv",params={"delimiter":";","where":"nature_uai_libe like 'ECOLE%'"},headers=H,timeout=600)
df=pd.read_csv(io.StringIO(r.text),sep=";",dtype=str)
print(len(df), list(df.columns))
print(df["nature_uai_libe"].value_counts().to_dict())
for c in ["etat_etablissement_libe","secteur_public_prive_libe"]:
    if c in df: print(c, df[c].value_counts().to_dict())
pd.set_option("display.width",250); pd.set_option("display.max_colwidth",70)
cols=[c for c in ["numero_uai","appellation_officielle","denomination_principale","patronyme_uai","nature_uai_libe","libelle_commune","code_departement"] if c in df]
print(df[cols].sample(40,random_state=1).to_string())
print(df[df["code_departement"].astype(str).str.contains("75")][cols].head(25).to_string())
print(df[df["numero_uai"].isin(["0750602X","0753258J","0921106C","0755913V"])][cols].to_string())
a=df["appellation_officielle"].fillna("")
for pat in [r"^E\.E\.", r"^E\.M\.", r"^E\.P\.", r"^Ecole", r"^ECOLE", r"\d+ (rue|avenue|bd|boulevard|place)", r"^$"]:
    print(pat, int(a.str.contains(pat, regex=True).sum()))
print("denomination values", df["denomination_principale"].value_counts().head(25).to_dict())
