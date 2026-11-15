import io, json, requests, pandas as pd
from urllib.parse import quote
H={"User-Agent":"carte-scolaire-diag"}
PA="https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
for i,cols in [("secteurs-scolaires-ecoles-elementaires","libelle,zone_commune,lib_etab_1,lib_etab_2,lib_etab_3,lib_etab_4,annee_scol,geo_shape"),
               ("etablissements-scolaires-maternelles","libelle,adresse,arr_insee,annee_scol,geo_point_2d")]:
    url=f"{PA}/{i}/exports/csv?delimiter=%3B&select={cols}&where={quote(chr(97)+'nnee_scol >= ' + chr(39)+'2025-2026'+chr(39))}"
    r=requests.get(url,headers=H,timeout=300); print(i, r.status_code, len(r.content)/1e6, "Mo")
    df=pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")),sep=";",dtype=str)
    print(list(df.columns), len(df), df["annee_scol"].value_counts().to_dict())
    print(df.iloc[0].to_dict().__repr__()[:500])
r=requests.get(f"{PA}/secteurs-scolaires-ecoles-elementaires/exports/csv?delimiter=%3B&select=annee_scol&where={quote(chr(39)+'x'+chr(39))}",headers=H,timeout=60); print("where invalide ->", r.status_code)
