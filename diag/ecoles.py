import io, json, requests, pandas as pd
from urllib.parse import quote
H={"User-Agent":"carte-scolaire-diag"}
PA="https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
w = "annee_scol in ('2025-2026', '2026-2027', '2027-2028')"
for i,cols in [("secteurs-scolaires-ecoles-elementaires","libelle,zone_commune,lib_etab_1,lib_etab_2,lib_etab_3,lib_etab_4,annee_scol,geo_shape"),
               ("etablissements-scolaires-maternelles","libelle,adresse,arr_insee,annee_scol,geo_point_2d")]:
    url=f"{PA}/{i}/exports/csv?delimiter=%3B&select={cols}&where={quote(w)}"
    r=requests.get(url,headers=H,timeout=300); print(i, r.status_code, len(r.content)/1e6, "Mo")
    if r.status_code != 200: print(r.text[:500]); continue
    df=pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")),sep=";",dtype=str)
    print(list(df.columns), len(df), df.iloc[:, list(df.columns).index([c for c in df.columns if "nn" in c.lower()][0])].value_counts().to_dict())
    print(repr(df.iloc[0].to_dict())[:500])
