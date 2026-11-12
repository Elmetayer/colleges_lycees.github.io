"""Construit les zones de secteur des collèges publics, département par département (France métropolitaine).

Source : fichier national « Carte scolaire des collèges publics » (DGESCO), décrit rue par rue.
  - Commune à un seul collège de secteur : la zone est le contour de la commune.
  - Commune à plusieurs collèges : chaque adresse est rattachée à son collège selon les règles du
    fichier (voie, parité, numéros), puis la commune est découpée en zones autour des adresses
    (polygones de Voronoï découpés au contour de la commune). Adresses : Base Adresse Nationale,
    à défaut export régional de la BAN (Île-de-France) ou BANO (adresses OpenStreetMap, ODbL).
  - Paris, Lyon et Marseille sont traités par arrondissement.
Contrôle : comparaison avec les zones officielles publiées par Paris et les Hauts-de-Seine.

Deux étapes :
  python pipeline/secteurs.py calculer --groupe 0 --groupes 12 --sortie secteurs-out
      calcule les départements du groupe et écrit <sortie>/<dep>.geojson et <sortie>/<dep>.json
      (empreinte, source des adresses, qualité). Un département dont l'empreinte (code + lignes de
      la carte scolaire) n'a pas changé n'est pas recalculé ; un département en échec garde ses
      fichiers précédents s'ils existent (cache de GitHub Actions).
  python pipeline/secteurs.py assembler --entree secteurs-out --out site/data
      écrit <out>/secteurs/<dep>.geojson (chargés par le site selon la zone affichée),
      <out>/secteurs/index.json (emprise, taille, source et qualité par département) et le bloc
      "secteurs" de meta.json.
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import shapely
import shapely.errors
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, shape
from shapely.ops import unary_union

L93 = 2154
METROPOLE = re.compile(r"\d{2}|2[AB]")
# Communes découpées en arrondissements municipaux (codes INSEE des arrondissements dans la BAN).
PLM = {"75": "75056", "69": "69123", "13": "13055"}
# Version du calcul des zones : à augmenter quand la méthode change, pour forcer le recalcul de
# tous les départements (une modification de l'assemblage ou des journaux ne le demande pas).
VERSION_CALCUL = "2"
H = requests.Session()
H.headers["User-Agent"] = "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"
# Les services publics (geo.api.gouv.fr, BAN) ont des coupures passagères : on réessaie avant d'abandonner.
H.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                                                  allowed_methods=["GET"], raise_on_status=False)))


def log(m):
    print(m, flush=True)


def norm_voie(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def valide(g):
    """Géométrie réparée (contour qui se recoupe...), réduite à ses parties surfaciques."""
    g = shapely.make_valid(g)
    if g.geom_type == "GeometryCollection":
        g = unary_union([x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
    return g


def union_sure(geoms):
    """Union qui répare les géométries si GEOS refuse l'union directe (TopologyException)."""
    try:
        return unary_union(geoms)
    except shapely.errors.GEOSException:
        return unary_union([valide(g).buffer(0) for g in geoms])


def telecharger(url: str, timeout: int = 900) -> requests.Response:
    """GET avec trois essais en cas de coupure en cours de transfert (gros fichiers d'adresses)."""
    for essai in range(3):
        try:
            return H.get(url, timeout=timeout)
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
            if essai == 2:
                raise
            log(f"  coupure pendant le téléchargement de {url} ({type(e).__name__}), nouvel essai")
            time.sleep(10 * (essai + 1))


def dep_de(insee: str) -> str:
    """Département d'une commune : '2A004' -> '2A', '75112' -> '75', '97411' -> '974'."""
    insee = str(insee).strip().upper()
    return insee[:3] if insee.startswith("97") else insee[:2]


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
    df["code_insee"] = df["code_insee"].str.strip().str.upper().str.zfill(5)
    # Département de rattachement : celui du collège (code_departement), à défaut celui de la commune.
    dep = df["code_departement"].str.strip().str.upper()
    dep = dep.map(lambda d: d.lstrip("0") if d.isdigit() else (d[1:] if len(d) == 3 and d[0] == "0" else d))
    dep = dep.map(lambda d: d.zfill(2) if d.isdigit() and len(d) < 3 else d)
    df["dep"] = dep.where(dep != "", df["code_insee"].map(dep_de))
    df["voie"] = df["type_et_libelle"].map(norm_voie)
    df["deb"] = df["No_de_voie_debut"].map(entier)
    df["fin"] = df["No_de_voie_fin"].map(entier)
    df["uai"] = df["code_rne"].str.strip().str.upper()
    log(f"  {len(df)} lignes, {df['code_insee'].nunique()} communes, {df['uai'].nunique()} collèges")
    return df


def contours(deps) -> gpd.GeoDataFrame:
    """Contours des communes des départements, plus les arrondissements de Paris, Lyon et Marseille."""
    feats = []
    for dep in sorted(set(deps)):
        urls = [f"https://geo.api.gouv.fr/departements/{dep}/communes?fields=code,nom&format=geojson&geometry=contour"]
        if dep in PLM:
            urls.append(f"https://geo.api.gouv.fr/communes?codeDepartement={dep}&type=arrondissement-municipal&fields=code,nom&format=geojson&geometry=contour")
        for url in urls:
            r = H.get(url, timeout=120)
            r.raise_for_status()
            fs = r.json().get("features", [])
            log(f"  contours {dep} : {len(fs)}{' arrondissements' if 'arrondissement' in url else ''}")
            feats += fs
    g = gpd.GeoDataFrame.from_features(feats, crs=4326).to_crs(L93)
    g["geometry"] = g.geometry.buffer(0)
    return g[["code", "nom", "geometry"]]


def contours_complementaires(codes: list[str]) -> gpd.GeoDataFrame | None:
    """Communes d'un autre département ou communes déléguées absentes de la liste."""
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


BAN = "https://adresse.data.gouv.fr/data/ban/adresses/"
_ban_dossiers: list[str] | None = None
_ban_liens: list[str] | None = None


def ban_urls(dep: str):
    """Adresses possibles du fichier BAN d'un département, de la plus probable à la moins probable.

    Le dossier « latest » a déjà disparu : on se rabat sur le millésime daté le plus récent
    de l'index, puis sur les ressources déclarées sur data.gouv.fr.
    """
    global _ban_dossiers
    nom = f"adresses-{dep}.csv.gz"
    yield f"{BAN}latest/csv/{nom}"
    if _ban_dossiers is None:
        _ban_dossiers = []
        try:
            r = H.get(BAN, timeout=60)
            r.raise_for_status()
            _ban_dossiers = sorted(set(re.findall(r'href="(\d{4}-\d{2}-\d{2}|weekly|latest)/"', r.text)), reverse=True)
            log(f"  dossiers BAN disponibles : {_ban_dossiers[:6]}")
        except Exception as e:  # noqa: BLE001
            log(f"  ! index BAN illisible : {e}")
    for d in _ban_dossiers:
        if d != "latest":
            yield f"{BAN}{d}/csv/{nom}"
    # La page « Données nationales » du site de la BAN donne les liens en vigueur.
    global _ban_liens
    if _ban_liens is None:
        _ban_liens = []
        try:
            r = H.get("https://adresse.data.gouv.fr/donnees-nationales", timeout=60)
            r.raise_for_status()
            texte = r.text.replace("\\/", "/")
            absolus = re.findall(r'https?://[^"\'\s<>]*?/data/ban/[^"\'\s<>]+', texte)
            relatifs = ["https://adresse.data.gouv.fr" + x for x in re.findall(r'(?<=["\'])/data/ban/[^"\'\s<>]+', texte)]
            _ban_liens = sorted(set(absolus + relatifs))
            log(f"  liens BAN de la page Données nationales : {_ban_liens[:12]}")
        except Exception as e:  # noqa: BLE001
            log(f"  ! page Données nationales illisible : {e}")
    for lien in _ban_liens:
        m = re.search(r"(.*/)adresses-(?:[0-9AB]{2,3}|france)\.csv\.gz$", lien)
        if m and "with-ids" not in lien:
            yield f"{m.group(1)}{nom}"
    try:
        r = H.get("https://www.data.gouv.fr/api/1/datasets/base-adresse-nationale/", timeout=60)
        r.raise_for_status()
        ressources = [res.get("url") or "" for res in r.json().get("resources", [])]
        log(f"  ressources data.gouv.fr de la BAN : {ressources[:12]}")
        for url in ressources:
            if url.endswith("/" + nom):
                yield url
    except Exception as e:  # noqa: BLE001
        log(f"  ! data.gouv.fr indisponible pour la BAN : {e}")


_ban_hs = False  # la BAN a déjà échoué dans ce passage : inutile de la réinterroger pour chaque département


_ban_ok: bool | None = None


def ban_disponible() -> bool:
    """La BAN nationale répond-elle ? (testé une fois par passage, sur le fichier de Paris)."""
    global _ban_ok
    if _ban_ok is None:
        try:
            r = H.head(f"{BAN}latest/csv/adresses-75.csv.gz", timeout=60, allow_redirects=True)
            _ban_ok = r.ok
        except requests.RequestException:
            _ban_ok = False
        log(f"  Base Adresse Nationale {'disponible' if _ban_ok else 'indisponible'}")
    return _ban_ok


def _lister(url: str) -> list[str]:
    r = H.get(url, timeout=60)
    r.raise_for_status()
    return re.findall(r'href="([^"?#]+)"', r.text)


# Exports de la BAN publiés par la région Île-de-France (même format que la BAN nationale).
BAN_IDF = {
    "75": "base-dadresses-nationale-ouverte-bano-paris", "77": "base-adresse-77", "78": "base-adresse-78",
    "91": "base-adresse-91", "92": "base-adresse-92", "93": "base-adresse-93", "94": "base-adresse-94", "95": "base-adresse-95",
}


def sources_secours(dep: str):
    """(nom de la source, URL, format) à essayer quand la BAN nationale ne répond pas."""
    if dep in BAN_IDF:
        yield ("Base Adresse Nationale (export Île-de-France)",
               f"https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/{BAN_IDF[dep]}/exports/csv", "ban")
    yield ("BANO (OpenStreetMap)", f"https://bano.openstreetmap.fr/data/bano-{dep}.csv", "bano")


def _lire_bano(contenu: bytes) -> pd.DataFrame:
    """BANO : CSV sans en-tête, id (commence par le code INSEE), numéro, voie, code postal, commune, source, lat, lon."""
    b = pd.read_csv(io.BytesIO(contenu), sep=",", header=None, dtype=str, keep_default_na=False,
                    names=["id", "numero", "nom_voie", "cp", "commune", "source", "lat", "lon"], usecols=range(8))
    b["code_insee"] = b["id"].str[:5].str.upper()
    return b


def _lire_adresses(contenu: bytes, fmt: str = "ban") -> pd.DataFrame:
    brut = gzip.decompress(contenu) if contenu[:2] == b"\x1f\x8b" else contenu
    b = _lire_bano(brut) if fmt == "bano" else pd.read_csv(io.BytesIO(brut), sep=";", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    col = lambda *noms: next((c for c in noms if c in b.columns), None)
    c_insee = col("code_insee", "commune_insee")
    c_num, c_voie, c_afnor = col("numero"), col("nom_voie", "voie_nom"), col("nom_afnor")
    c_lon, c_lat = col("lon", "long", "longitude"), col("lat", "latitude")
    if not (c_insee and c_num and c_voie and c_lon and c_lat):
        raise RuntimeError(f"colonnes d'adresses inattendues : {list(b.columns)[:15]}")
    out = pd.DataFrame({
        "code_insee": b[c_insee].str.strip().str.upper(),
        "num": b[c_num].map(entier),
        "voie": (b[c_afnor].where(b[c_afnor] != "", b[c_voie]) if c_afnor else b[c_voie]).map(norm_voie),
        "lon": pd.to_numeric(b[c_lon], errors="coerce"),
        "lat": pd.to_numeric(b[c_lat], errors="coerce"),
    }).dropna(subset=["lon", "lat"])
    pts = gpd.GeoSeries(gpd.points_from_xy(out["lon"], out["lat"]), crs=4326).to_crs(L93)
    out["x"], out["y"] = pts.x.to_numpy(), pts.y.to_numpy()
    return out


def adresses(dep: str, communes: set[str]) -> tuple[pd.DataFrame, str]:
    """Adresses des communes à découper : BAN nationale, sinon export régional de la BAN, sinon BANO.

    Renvoie aussi le nom de la source retenue.
    """
    global _ban_hs
    trouve = None
    if not _ban_hs:
        for url in ban_urls(dep):
            r = telecharger(url, timeout=600)
            if r.ok:
                trouve = ("Base Adresse Nationale", r.content, "ban")
                break
            log(f"  BAN {dep} : {r.status_code} pour {url}")
        else:
            _ban_hs = True
    if trouve is None:
        for nom, url, fmt in sources_secours(dep):
            r = telecharger(url, timeout=900)
            if r.ok and len(r.content) > 1000:
                log(f"  adresses {dep} : {nom} ({url}, {len(r.content) / 1e6:.0f} Mo)")
                trouve = (nom, r.content, fmt)
                break
            log(f"  {nom} {dep} : {r.status_code} pour {url}")
    if trouve is None:
        raise RuntimeError(f"aucune source d'adresses pour le département {dep}")
    source, contenu, fmt = trouve
    b = _lire_adresses(contenu, fmt)
    # Paris, Lyon, Marseille : si la carte scolaire décrit la commune entière, ramener les arrondissements à la commune.
    commune_plm = PLM.get(dep)
    if commune_plm and commune_plm in communes:
        arr = b["code_insee"].str[:2].eq(dep) & ~b["code_insee"].isin(communes) & b["code_insee"].ne(commune_plm)
        arr &= b["code_insee"].str[2:].astype(str).str.match(r"^(1\d\d|2\d\d|38\d)$")
        b.loc[arr, "code_insee"] = commune_plm
    b = b[b["code_insee"].isin(communes)].copy()
    return b, source


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
    region = valide(region)
    return {u: valide(union_sure(cs)).intersection(region) for u, cs in par_uai.items()}


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


# ---------------------------------------------------------------- calcul par département

def empreinte(lignes: pd.DataFrame) -> str:
    """Change quand le code ou les lignes de la carte scolaire du département changent."""
    cols = ["code_insee", "uai", "type_et_libelle", "parite", "No_de_voie_debut", "No_de_voie_fin"]
    texte = lignes[[c for c in cols if c in lignes.columns]].sort_values(cols[:3]).to_csv(index=False)
    return "v" + VERSION_CALCUL + "-" + hashlib.sha256(texte.encode()).hexdigest()[:16]


def calculer_departement(dep: str, lignes: pd.DataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    """Zones des collèges d'un département (Lambert 93) et rapport de qualité."""
    rapport = {"departement": dep, "colleges": int(lignes["uai"].nunique()), "communes": int(lignes["code_insee"].nunique())}
    com = contours({dep})  # communes d'autres départements : contours_complementaires
    geo_com = {c: valide(g) for c, g in zip(com["code"], com.geometry)}
    manquantes = sorted(set(lignes["code_insee"]) - set(geo_com))
    if manquantes:
        compl = contours_complementaires(manquantes)
        if compl is not None:
            geo_com.update({c: valide(g) for c, g in zip(compl["code"], compl.geometry)})
    sans_contour = sorted(set(lignes["code_insee"]) - set(geo_com))
    rapport["communes_sans_contour"] = sans_contour
    if sans_contour:
        log(f"  ! communes sans contour : {sans_contour[:15]}")

    nb = lignes.groupby("code_insee")["uai"].nunique()
    uniques, multiples = nb[nb == 1].index, nb[nb > 1].index
    log(f"  {len(uniques)} communes à un collège, {len(multiples)} à plusieurs")
    morceaux: dict[str, list] = {}
    for insee in uniques:
        if insee in geo_com:
            morceaux.setdefault(lignes.loc[lignes["code_insee"] == insee, "uai"].iat[0], []).append(geo_com[insee])

    if len(multiples):
        par_voie, defaut = regles(lignes[lignes["code_insee"].isin(multiples)])
        sources, n_adr, n_regle = set(), 0, 0
        for d_adr in sorted({dep_de(c) for c in multiples}):
            communes = {c for c in multiples if dep_de(c) == d_adr}
            b, source = adresses(d_adr, communes)
            sources.add(source)
            b["uai"] = rattacher(b, par_voie, defaut)
            n_adr, n_regle = n_adr + len(b), n_regle + int(b["uai"].notna().sum())
            b["uai"] = completer_par_voisins(b)
            for insee, g in b.groupby("code_insee"):
                g = g[g["uai"].notna()]
                if insee in geo_com and not g.empty:
                    for u, poly in decouper(geo_com[insee], g).items():
                        morceaux.setdefault(u, []).append(poly)
            sans_adresse = sorted(communes - set(b["code_insee"]))
            if sans_adresse:
                log(f"  ! communes à plusieurs collèges sans adresse : {sans_adresse[:15]}")
                rapport.setdefault("communes_sans_adresse", []).extend(sans_adresse)
        rapport["source_adresses"] = " + ".join(sorted(sources))
        rapport["adresses"] = n_adr
        rapport["rattachees_par_regle"] = round(n_regle / n_adr, 3) if n_adr else None
        log(f"  {n_adr} adresses ({rapport['source_adresses']}), "
            f"{(rapport['rattachees_par_regle'] or 0):.1%} rattachées par une règle du fichier, le reste par la plus proche voisine")
    rows = [{"uai": u, "geometry": union_sure(ps)} for u, ps in morceaux.items()]
    sect = gpd.GeoDataFrame(rows, columns=["uai", "geometry"], geometry="geometry", crs=L93)
    sect["geometry"] = sect.geometry.buffer(0)
    rapport["zones"] = len(sect)
    rapport["colleges_sans_zone"] = sorted(set(lignes["uai"]) - set(sect["uai"]))
    return sect, rapport


def en_geojson(sect: gpd.GeoDataFrame) -> dict:
    sortie = sect.copy()
    sortie["geometry"] = sortie.geometry.simplify(12, preserve_topology=True)
    sortie = sortie.to_crs(4326)
    feats = []
    for r in sortie.itertuples():
        g = shapely.make_valid(shapely.set_precision(r.geometry, 0.00001))
        if g.geom_type == "GeometryCollection":
            g = unary_union([x for x in g.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
        if g.is_empty:
            continue
        feats.append({"type": "Feature", "properties": {"uai": r.uai}, "geometry": shapely.geometry.mapping(g)})
    return {"type": "FeatureCollection", "features": feats}


def cmd_calculer(args) -> int:
    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    log("== carte scolaire")
    df = carte_scolaire()
    deps = sorted(d for d in df["dep"].unique() if METROPOLE.fullmatch(d))
    if args.deps:
        deps = [d for d in deps if d in args.deps.split(",")]
    else:
        deps = deps[args.groupe::args.groupes]
    log(f"  groupe {args.groupe + 1}/{args.groupes} : départements {deps}")
    bilan = {"recalcules": [], "inchanges": [], "echecs": []}
    for dep in deps:
        lignes = df[df["dep"] == dep]
        emp = empreinte(lignes)
        rapport_path = sortie / f"{dep}.json"
        ancien = json.loads(rapport_path.read_text(encoding="utf-8")) if rapport_path.exists() else {}
        # Secteurs calculés avec une source de secours : on les refait dès que la BAN nationale revient.
        secours = ancien.get("source_adresses", "Base Adresse Nationale") != "Base Adresse Nationale"
        if (ancien.get("empreinte") == emp and (sortie / f"{dep}.geojson").exists() and not args.forcer
                and not (secours and ban_disponible())):
            log(f"== {dep} : inchangé depuis le {ancien.get('date', '?')}, pas de recalcul")
            bilan["inchanges"].append(dep)
            continue
        log(f"== {dep} ({lignes['uai'].nunique()} collèges, {lignes['code_insee'].nunique()} communes)")
        try:
            sect, rapport = calculer_departement(dep, lignes)
            geo = en_geojson(sect)
            (sortie / f"{dep}.geojson").write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
            rapport.update({"empreinte": emp, "date": datetime.date.today().isoformat()})
            rapport_path.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  {len(geo['features'])} zones écrites ; collèges sans zone : {rapport['colleges_sans_zone'][:8]}")
            bilan["recalcules"].append(dep)
        except Exception as e:  # noqa: BLE001
            garde = (sortie / f"{dep}.geojson").exists()
            log(f"  ! échec {dep} : {type(e).__name__}: {e} ; {'derniers secteurs valides conservés' if garde else 'aucun secteur précédent'}")
            bilan["echecs"].append(dep)
    log(f"== bilan du groupe : {json.dumps(bilan)}")
    return 0


# ---------------------------------------------------------------- assemblage

def cmd_assembler(args) -> int:
    entree, out = Path(args.entree), Path(args.out)
    dossier = out / "secteurs"
    dossier.mkdir(parents=True, exist_ok=True)
    noms = {}
    try:
        cg = json.loads((out / "colleges.geojson").read_text(encoding="utf-8"))
        noms = {f["properties"]["uai"]: f["properties"]["nom"] for f in cg["features"]}
    except FileNotFoundError:
        log("  ! colleges.geojson absent : noms non renseignés")
    index, l93 = {}, {}
    for g_path in sorted(entree.glob("*.geojson")):
        dep = g_path.stem
        geo = json.loads(g_path.read_text(encoding="utf-8"))
        rapport = json.loads((entree / f"{dep}.json").read_text(encoding="utf-8")) if (entree / f"{dep}.json").exists() else {}
        for f in geo["features"]:
            if f["properties"]["uai"] in noms:
                f["properties"]["nom"] = noms[f["properties"]["uai"]]
        texte = json.dumps(geo, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        (dossier / f"{dep}.geojson").write_text(texte, encoding="utf-8")
        bornes = gpd.GeoDataFrame.from_features(geo["features"], crs=4326).total_bounds if geo["features"] else None
        index[dep] = {
            "zones": len(geo["features"]), "taille": len(texte.encode()), "date": rapport.get("date"),
            "bbox": [round(float(v), 4) for v in bornes] if bornes is not None else None,
            **{k: rapport[k] for k in ("source_adresses", "adresses", "rattachees_par_regle") if k in rapport},
            "colleges_sans_zone": len(rapport.get("colleges_sans_zone", [])),
            "communes_sans_contour": len(rapport.get("communes_sans_contour", [])),
        }
        if dep in ("75", "92") and geo["features"]:
            l93[dep] = gpd.GeoDataFrame.from_features(geo["features"], crs=4326).to_crs(L93)
    (dossier / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(v["taille"] for v in index.values())
    log(f"  {len(index)} départements, {sum(v['zones'] for v in index.values())} zones, {total / 1e6:.1f} Mo au total")
    for dep, v in sorted(index.items(), key=lambda kv: kv[1].get("rattachees_par_regle") or 1)[:8]:
        log(f"   {dep} : {v}")
    for v in (x for x in index.values() if x.get("bbox") is None):
        log(f"  ! département sans emprise (aucune zone) : {v}")

    log("== contrôle avec les zones officielles")
    controle = {}
    if l93:
        ours = pd.concat(l93.values(), ignore_index=True)
        for nom, off in officiels().items():
            try:
                c = concordance(nom, off, ours, noms)
                if c:
                    controle[nom] = c
            except Exception as e:  # noqa: BLE001
                log(f"  ! contrôle {nom} impossible : {e}")

    meta_path = out / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    sources = sorted({v.get("source_adresses") for v in index.values() if v.get("source_adresses")})
    meta["secteurs"] = {"departements": len(index), "zones": sum(v["zones"] for v in index.values()), "controle": controle,
                        "adresses": {d: {k: v[k] for k in ("source_adresses", "adresses", "rattachees_par_regle") if k in v} for d, v in index.items()},
                        "source": "Carte scolaire des collèges publics (DGESCO), " + (" ; ".join(sources) or "adresses") + ", contours geo.api.gouv.fr"}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"== terminé ; contrôle : {json.dumps(controle, ensure_ascii=False)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sous = ap.add_subparsers(dest="cmd", required=True)
    c = sous.add_parser("calculer")
    c.add_argument("--groupe", type=int, default=0)
    c.add_argument("--groupes", type=int, default=1)
    c.add_argument("--deps", default="", help="liste de départements, par ex. 75,92 (prioritaire sur --groupe)")
    c.add_argument("--sortie", default="secteurs-out")
    c.add_argument("--forcer", action="store_true", help="recalculer même si l'empreinte n'a pas changé")
    a = sous.add_parser("assembler")
    a.add_argument("--entree", default="secteurs-out")
    a.add_argument("--out", default="site/data")
    args = ap.parse_args()
    return cmd_calculer(args) if args.cmd == "calculer" else cmd_assembler(args)


if __name__ == "__main__":
    sys.exit(main())
