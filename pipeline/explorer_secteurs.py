"""Exploration ponctuelle des données de sectorisation (jalon 3). Affiche des constats dans le journal."""

import gzip
import io
import json
import re

import pandas as pd
import requests

H = requests.Session()
H.headers["User-Agent"] = "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"
DEPS = ["75", "78", "91", "92", "95"]


def titre(t):
    print(f"\n{'=' * 10} {t}", flush=True)


def ressources(slug):
    r = H.get(f"https://www.data.gouv.fr/api/1/datasets/{slug}/", timeout=60)
    r.raise_for_status()
    j = r.json()
    print("titre :", j.get("title"), "| maj :", j.get("last_update"))
    for res in j.get("resources", []):
        print("  -", res.get("format"), res.get("filesize"), res.get("title"), res.get("url"))
    return j.get("resources", [])


def lire_csv(url):
    r = H.get(url, timeout=600)
    r.raise_for_status()
    texte = r.content.decode("utf-8-sig", errors="replace")
    sep = ";" if texte.split("\n", 1)[0].count(";") >= texte.split("\n", 1)[0].count(",") else ","
    return pd.read_csv(io.StringIO(texte), sep=sep, dtype=str, keep_default_na=False)


# 1. Fichier national de carte scolaire des collèges
titre("Carte scolaire des collèges publics (DGESCO)")
res = ressources("carte-scolaire-des-colleges-publics")
url = next((r["url"] for r in res if (r.get("format") or "").lower() == "csv"), None)
df = lire_csv(url)
print("lignes :", len(df))
print("colonnes :", list(df.columns))
print(df.head(5).to_string())
col_dep = next((c for c in df.columns if re.search(r"d[eé]partement|code_dep", c, re.I)), None)
col_insee = next((c for c in df.columns if re.search(r"insee|code_commune|code commune", c, re.I)), None)
print("colonne département :", col_dep, "| colonne commune :", col_insee)
if col_dep:
    print("exemples départements :", df[col_dep].drop_duplicates().head(10).tolist())
    d = df[df[col_dep].astype(str).str.lstrip("0").isin(DEPS)]
else:
    d = df[df[col_insee].astype(str).str[:2].isin(DEPS)]
print("lignes dans les 5 départements :", len(d))
for c in d.columns:
    n = d[c].nunique()
    print(f"  {c}: {n} valeurs distinctes, ex. {d[c].drop_duplicates().head(4).tolist()}")
col_uai = next((c for c in d.columns if re.search(r"uai|rne|code_etab", c, re.I)), None)
if col_insee and col_uai:
    par_commune = d.groupby(col_insee)[col_uai].nunique()
    print("communes :", len(par_commune), "| à un seul collège :", int((par_commune == 1).sum()),
          "| à plusieurs :", int((par_commune > 1).sum()), "| collèges distincts :", d[col_uai].nunique())
    dep_de = d[col_insee].astype(str).str[:2]
    for dep in DEPS:
        sub = d[dep_de == dep]
        pc = sub.groupby(col_insee)[col_uai].nunique()
        print(f"  {dep}: {len(sub)} lignes, {len(pc)} communes, {int((pc > 1).sum())} à plusieurs collèges, {sub[col_uai].nunique()} collèges")
print("échantillon d'une commune à plusieurs collèges :")
if col_insee and col_uai:
    multi = par_commune[par_commune > 1].index[:1]
    print(d[d[col_insee].isin(multi)].head(15).to_string())

# 2. Polygones existants
titre("Paris : secteurs scolaires collèges")
for slug in ("secteurs-scolaires-colleges-de-paris", "secteurs-scolaires-colleges"):
    try:
        ressources(slug)
    except Exception as e:  # noqa: BLE001
        print(slug, "indisponible :", e)
try:
    r = H.get("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/secteurs-scolaires-colleges/records?limit=2", timeout=60)
    print("opendata.paris.fr :", r.status_code, r.text[:1200])
except Exception as e:  # noqa: BLE001
    print("opendata.paris.fr indisponible :", e)

titre("Hauts-de-Seine : carte scolaire des collèges (secteurs)")
try:
    res92 = ressources("carte-scolaire-des-colleges-publics-secteurs")
    js = next((r["url"] for r in res92 if (r.get("format") or "").lower() in ("geojson", "json")), None)
    if js:
        r = H.get(js, timeout=120)
        print("statut", r.status_code, "taille", len(r.content))
        try:
            j = r.json()
            if isinstance(j, dict) and "features" in j:
                print("features :", len(j["features"]), "| propriétés :", list(j["features"][0]["properties"].keys()), "| géométrie :", j["features"][0]["geometry"]["type"])
            else:
                print(str(j)[:600])
        except Exception:  # noqa: BLE001
            print(r.text[:600])
except Exception as e:  # noqa: BLE001
    print("indisponible :", e)

# 3. Base Adresse Nationale
titre("Base Adresse Nationale (adresses par département)")
for dep in DEPS:
    u = f"https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dep}.csv.gz"
    try:
        r = H.head(u, timeout=60, allow_redirects=True)
        print(dep, r.status_code, r.headers.get("content-length"))
    except Exception as e:  # noqa: BLE001
        print(dep, "indisponible :", e)
try:
    r = H.get("https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-92.csv.gz", timeout=300)
    ban = pd.read_csv(io.BytesIO(gzip.decompress(r.content)), sep=";", dtype=str, nrows=5)
    print("colonnes BAN :", list(ban.columns))
    print(ban.head(3).to_string())
except Exception as e:  # noqa: BLE001
    print("lecture BAN impossible :", e)

# 4. Contours des communes
titre("Contours des communes (geo.api.gouv.fr)")
try:
    r = H.get("https://geo.api.gouv.fr/departements/92/communes?fields=nom,code&format=geojson&geometry=contour", timeout=120)
    j = r.json()
    print("statut", r.status_code, "| communes :", len(j.get("features", [])))
except Exception as e:  # noqa: BLE001
    print("indisponible :", e)
