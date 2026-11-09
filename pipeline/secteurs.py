"""Construit les zones de secteur des collèges publics (académies de Paris et de Versailles).

Source : fichier national « Carte scolaire des collèges publics » (DGESCO), décrit rue par rue.
  - Commune à un seul collège de secteur : la zone est le contour de la commune.
  - Commune à plusieurs collèges : chaque adresse de la Base Adresse Nationale est rattachée à son
    collège selon les règles du fichier (voie, parité, numéros), puis la commune est découpée en
    zones autour des adresses (polygones de Voronoï découpés au contour de la commune).
Contrôle : comparaison avec les zones officielles publiées par Paris et les Hauts-de-Seine.

Écrit <out>/secteurs.geojson et ajoute un bloc "secteurs" à <out>/meta.json.
Usage : python pipeline/secteurs.py --out site/data
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, shape
from shapely.ops import unary_union

DEPS = ["75", "78", "91", "92", "95"]
L93 = 2154
H = requests.Session()
H.headers["User-Agent"] = "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"


def log(m):
    print(m, flush=True)


def norm_voie(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def entier(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- sources

def carte_scolaire() -> pd.DataFrame:
    r = H.get("https://www.data.gouv.fr/api/1/datasets/carte-scolaire-des-colleges-publics/", timeout=60)
    r.raise_for_status()
    url = next(x["url"] for x in r.json()["resources"] if (x.get("format") or "").lower() == "csv")
    log(f"  téléchargement {url}")
    r = H.get(url, timeout=900)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), sep=";", dtype=str, keep_default_na=False)
    df = df[df["code_departement"].str.lstrip("0").isin(DEPS)].copy()
    df["voie"] = df["type_et_libelle"].map(norm_voie)
    df["deb"] = df["No_de_voie_debut"].map(entier)
    df["fin"] = df["No_de_voie_fin"].map(entier)
    df["uai"] = df["code_rne"].str.strip().str.upper()
    log(f"  {len(df)} lignes, {df['code_insee'].nunique()} communes, {df['uai'].nunique()} collèges")
    return df


def contours() -> gpd.GeoDataFrame:
    feats = []
    for dep in DEPS:
        if dep == "75":
            url = "https://geo.api.gouv.fr/communes?codeDepartement=75&type=arrondissement-municipal&fields=code,nom&format=geojson&geometry=contour"
        else:
            url = f"https://geo.api.gouv.fr/departements/{dep}/communes?fields=code,nom&format=geojson&geometry=contour"
        r = H.get(url, timeout=120)
        r.raise_for_status()
        fs = r.json().get("features", [])
        log(f"  contours {dep} : {len(fs)}")
        feats += fs
    g = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(L93)
    g["geometry"] = g.geometry.buffer(0)
    return g[["code", "nom", "geometry"]]


def contours_complementaires(codes: list[str]) -> gpd.GeoDataFrame | None:
    """Communes hors des 5 départements (Eure-et-Loir...) ou communes déléguées absentes de la liste."""
    feats = []
    for c in codes:
        trouve = None
        for url in (f"https://geo.api.gouv.fr/communes/{c}?fields=code,nom&format=geojson&geometry=contour",
                    f"https://geo.api.gouv.fr/communes?code={c}&type=commune-deleguee,commune-associee&fields=code,nom&format=geojson&geometry=contour"):
            try:
                r = H.get(url, timeout=60)
                if r.status_code != 200:
                    continue
                j = r.json()
                fs = j.get("features", [j] if j.get("type") == "Feature" else [])
                fs = [f for f in fs if f.get("geometry")]
                if fs:
                    trouve = fs[0]
                    trouve["properties"]["code"] = c
                    break
            except Exception:  # noqa: BLE001
                continue
        log(f"  contour {c} : {'trouvé' if trouve else 'introuvable'}")
        if trouve:
            feats.append(trouve)
    if not feats:
        return None
    g = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(L93)
    g["geometry"] = g.geometry.buffer(0)
    return g[["code", "nom", "geometry"]]


def ban(dep: str, communes: set[str]) -> pd.DataFrame:
    url = f"https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dep}.csv.gz"
    r = H.get(url, timeout=600)
    r.raise_for_status()
    b = pd.read_csv(io.BytesIO(gzip.decompress(r.content)), sep=";", dtype=str,
                    usecols=["numero", "nom_voie", "nom_afnor", "code_insee", "x", "y"])
    b = b[b["code_insee"].isin(communes)].copy()
    b["num"] = b["numero"].map(entier)
    b["voie"] = b["nom_afnor"].fillna(b["nom_voie"]).map(norm_voie)
    b["x"] = pd.to_numeric(b["x"], errors="coerce")
    b["y"] = pd.to_numeric(b["y"], errors="coerce")
    return b.dropna(subset=["x", "y"])


# ---------------------------------------------------------------- rattachement des adresses

def regles(df: pd.DataFrame) -> tuple[dict, dict]:
    """(insee, voie) -> [(deb, fin, parite, uai)] ; insee -> collège par défaut (ligne sans voie)."""
    par_voie, defaut = {}, {}
    for r in df.itertuples():
        if not r.voie:
            defaut.setdefault(r.code_insee, r.uai)
            continue
        par_voie.setdefault((r.code_insee, r.voie), []).append((r.deb, r.fin, (r.parite or "").strip().upper(), r.uai))
    return par_voie, defaut


def rattacher(b: pd.DataFrame, par_voie: dict, defaut: dict) -> pd.Series:
    out = []
    for insee, voie, num in zip(b["code_insee"], b["voie"], b["num"]):
        uai = None
        for deb, fin, par, u in par_voie.get((insee, voie), ()):
            if num is not None:
                if deb is not None and num < deb:
                    continue
                if fin is not None and fin < 9999 and num > fin:
                    continue
                if par == "P" and num % 2:
                    continue
                if par == "I" and not num % 2:
                    continue
            uai = u
            break
        out.append(uai or defaut.get(insee))
    return pd.Series(out, index=b.index)


def completer_par_voisins(b: pd.DataFrame) -> pd.Series:
    """Adresses sans règle : collège de l'adresse rattachée la plus proche, dans la même commune."""
    res = b["uai"].copy()
    for insee, g in b.groupby("code_insee"):
        ok = g[g["uai"].notna()]
        ko = g[g["uai"].isna()]
        if ko.empty or ok.empty:
            continue
        _, idx = cKDTree(ok[["x", "y"]].to_numpy()).query(ko[["x", "y"]].to_numpy(), k=1)
        res.loc[ko.index] = ok["uai"].to_numpy()[idx]
    return res


def decouper(region, pts: pd.DataFrame) -> dict:
    """Polygones de Voronoï autour des adresses, découpés à la commune et regroupés par collège."""
    pts = pts.groupby(["x", "y"], as_index=False)["uai"].agg(lambda s: s.mode().iat[0])
    if pts["uai"].nunique() == 1:
        return {pts["uai"].iat[0]: region}
    mp = MultiPoint(pts[["x", "y"]].to_numpy())
    cellules = shapely.voronoi_polygons(mp, extend_to=region.envelope.buffer(500))
    cellules = list(cellules.geoms)
    # associer chaque cellule à son point (la cellule contient le point)
    arbre = shapely.STRtree(cellules)
    points = shapely.points(pts[["x", "y"]].to_numpy())
    idx_pt, idx_cell = arbre.query(points, predicate="within")
    par_uai: dict[str, list] = {}
    for ip, ic in zip(idx_pt, idx_cell):
        par_uai.setdefault(pts["uai"].iat[ip], []).append(cellules[ic])
    return {u: unary_union(cs).intersection(region) for u, cs in par_uai.items()}


# ---------------------------------------------------------------- contrôle

def officiels() -> dict[str, gpd.GeoDataFrame]:
    res = {}
    try:
        r = H.get("https://opendata.hauts-de-seine.fr/api/explore/v2.1/catalog/datasets/fr-229200506-carte-scolaire-colleges-publics-secteurs/exports/geojson", timeout=300)
        r.raise_for_status()
        g = gpd.GeoDataFrame.from_features(r.json()["features"], crs=4326)
        col = next(c for c in ("rne", "code_coll") if c in g.columns)
        g["uai"] = g[col].str.strip().str.upper()
        res["Hauts-de-Seine"] = g.to_crs(L93)[["uai", "geometry"]]
    except Exception as e:  # noqa: BLE001
        log(f"  ! zones officielles 92 indisponibles : {e}")
    try:
        r = H.get("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/secteurs-scolaires-colleges/exports/geojson", timeout=300)
        r.raise_for_status()
        g = gpd.GeoDataFrame.from_features(r.json()["features"], crs=4326)
        log(f"  Paris : colonnes {list(g.columns)}")
        if "annee_scol" in g.columns:
            log(f"  Paris : années {g['annee_scol'].value_counts().to_dict()}")
            g = g[g["annee_scol"] == g["annee_scol"].max()]
        res["Paris"] = g.to_crs(L93)
    except Exception as e:  # noqa: BLE001
        log(f"  ! zones officielles Paris indisponibles : {e}")
    return res


def concordance(nom: str, off: gpd.GeoDataFrame, ours: gpd.GeoDataFrame, noms: dict) -> dict | None:
    if "uai" not in off.columns:
        # Paris : rattacher par le nom du collège
        cle = lambda s: norm_voie(s).replace("COLLEGE ", "").strip()
        par_nom = {cle(n): u for u, n in noms.items() if u.startswith("075")}
        col = next((c for c in ("lib_etab_1", "libelle") if c in off.columns), None)
        if not col:
            log(f"  ! {nom} : pas de colonne de nom")
            return None
        off = off.copy()
        off["uai"] = off[col].map(lambda s: par_nom.get(cle(s)))
        log(f"  {nom} : {off['uai'].notna().sum()} / {len(off)} zones rattachées par le nom")
        off = off[off["uai"].notna()]
    off = off.dissolve(by="uai").reset_index()
    zone = unary_union(off.geometry)
    ours_z = ours.copy()
    ours_z["geometry"] = ours_z.geometry.intersection(zone)
    inter = gpd.overlay(off[["uai", "geometry"]], ours_z[["uai", "geometry"]], how="intersection", keep_geom_type=True)
    accord = inter[inter["uai_1"] == inter["uai_2"]].area.sum()
    total = zone.area
    taux = accord / total if total else 0
    par_college = []
    for u, g in off.groupby("uai"):
        a = g.geometry.iat[0]
        m = ours.loc[ours["uai"] == u, "geometry"]
        iou = (a.intersection(m.iat[0]).area / a.union(m.iat[0]).area) if len(m) else 0
        par_college.append((u, iou))
    par_college.sort(key=lambda t: t[1])
    log(f"  {nom} : {taux:.1%} de la surface attribuée au même collège ; recouvrement médian par collège {np.median([i for _, i in par_college]):.2f}")
    log(f"  {nom} : collèges les moins concordants {[(noms.get(u, u), round(i, 2)) for u, i in par_college[:6]]}")
    return {"taux_surface": round(taux, 3), "recouvrement_median": round(float(np.median([i for _, i in par_college])), 3), "colleges": len(par_college)}


# ---------------------------------------------------------------- principal

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    args = ap.parse_args()
    out = Path(args.out)

    log("== carte scolaire")
    df = carte_scolaire()
    log("== contours des communes")
    com = contours()
    geo_com = dict(zip(com["code"], com.geometry))
    manquantes = sorted(set(df["code_insee"]) - set(geo_com))
    if manquantes:
        log(f"  communes sans contour dans la liste : {manquantes}")
        compl = contours_complementaires(manquantes)
        if compl is not None:
            geo_com.update(dict(zip(compl["code"], compl.geometry)))
        encore = sorted(set(df["code_insee"]) - set(geo_com))
        if encore:
            log(f"  ! communes toujours sans contour : {encore}")

    nb = df.groupby("code_insee")["uai"].nunique()
    uniques, multiples = nb[nb == 1].index, nb[nb > 1].index
    log(f"  {len(uniques)} communes à un collège, {len(multiples)} à plusieurs")

    morceaux: dict[str, list] = {}
    for insee in uniques:
        if insee in geo_com:
            morceaux.setdefault(df.loc[df["code_insee"] == insee, "uai"].iat[0], []).append(geo_com[insee])

    par_voie, defaut = regles(df[df["code_insee"].isin(multiples)])
    stats = {}
    for dep in DEPS:
        mult_dep = {c for c in multiples if c.startswith(dep)}
        if not mult_dep:
            continue
        log(f"== adresses {dep} ({len(mult_dep)} communes à découper)")
        b = ban(dep, mult_dep)
        b["uai"] = rattacher(b, par_voie, defaut)
        taux = b["uai"].notna().mean()
        b["uai"] = completer_par_voisins(b)
        stats[dep] = {"adresses": int(len(b)), "rattachees_par_regle": round(float(taux), 3)}
        log(f"  {len(b)} adresses, {taux:.1%} rattachées par une règle du fichier, le reste par la plus proche voisine")
        for insee, g in b.groupby("code_insee"):
            if insee not in geo_com:
                continue
            g = g[g["uai"].notna()]
            if g.empty:
                continue
            for u, poly in decouper(geo_com[insee], g).items():
                morceaux.setdefault(u, []).append(poly)

    log("== assemblage")
    rows = [{"uai": u, "geometry": unary_union(ps)} for u, ps in morceaux.items()]
    sect = gpd.GeoDataFrame(rows, crs=L93)
    sect["geometry"] = sect.geometry.buffer(0)

    noms = {}
    try:
        cg = json.loads((out / "colleges.geojson").read_text(encoding="utf-8"))
        noms = {f["properties"]["uai"]: f["properties"]["nom"] for f in cg["features"]}
    except FileNotFoundError:
        log("  ! colleges.geojson absent : noms non renseignés")
    sans_point = sorted(set(sect["uai"]) - set(noms))
    log(f"  {len(sect)} zones ; {len(sans_point)} collèges de secteur absents de la carte : {sans_point[:10]}")

    log("== contrôle avec les zones officielles")
    controle = {}
    for nom, off in officiels().items():
        try:
            c = concordance(nom, off, sect, noms)
            if c:
                controle[nom] = c
        except Exception as e:  # noqa: BLE001
            log(f"  ! contrôle {nom} impossible : {e}")

    sortie = sect.copy()
    sortie["geometry"] = sortie.geometry.simplify(12, preserve_topology=True)
    sortie = sortie.to_crs(4326)
    sortie["nom"] = sortie["uai"].map(noms)
    feats = []
    for r in sortie.itertuples():
        g = shapely.make_valid(shapely.set_precision(r.geometry, 0.00001))
        if g.geom_type == "GeometryCollection":
            g = unary_union([x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
        feats.append({"type": "Feature", "properties": {"uai": r.uai, **({"nom": r.nom} if isinstance(r.nom, str) else {})}, "geometry": shapely.geometry.mapping(g)})
    (out / "secteurs.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    taille = (out / "secteurs.geojson").stat().st_size
    log(f"  secteurs.geojson : {len(feats)} zones, {taille / 1e6:.1f} Mo")

    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["secteurs"] = {"zones": len(feats), "adresses": stats, "controle": controle,
                        "source": "Carte scolaire des collèges publics (DGESCO), Base Adresse Nationale, contours geo.api.gouv.fr"}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"== terminé ; contrôle : {json.dumps(controle, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
