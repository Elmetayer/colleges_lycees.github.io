"""Secteurs des écoles publiques (jalon 7b : Paris).

Appelé par build.py après ecoles.py. Sources (opendata.paris.fr, Ville de Paris, licence ODbL) :
  - secteurs_paris_elementaires / secteurs_paris_maternelles : un polygone par secteur, avec les
    noms des écoles du secteur (lib_etab_1 à 4 ; « secteur commun » quand il y en a plusieurs) ;
  - ecoles_paris_elementaires / ecoles_paris_maternelles : les écoles (nom, adresse, position).
Les fichiers de la Ville ne donnent pas le code UAI des écoles : chaque nom est rattaché à une école
de l'annuaire national en croisant le numéro et la rue de l'adresse avec la distance (diagnostic du
15/11/2026 : 33 écoles à plus de 50 m de leur point dans l'annuaire).

Année montrée : la dernière publiée, sans dépasser la rentrée suivante (les familles préparent les
inscriptions dès que la Ville publie les secteurs de la rentrée suivante, vers mars).

Écrit :
  - <out>/secteurs-ecoles/75.geojson : les zones, propriétés niveau (maternelle | elementaire),
    uais (codes UAI séparés par des espaces), commun (secteur de plusieurs écoles), noms (ceux de la Ville)
  - <out>/secteurs-ecoles/index.json : emprise, année et source de chaque département
Renvoie le bloc "secteurs" de meta.json ecoles, avec les contrôles lus par tests/verifier_site.py :
  - rattachement : part des noms d'écoles des secteurs rattachés à un UAI
  - couverture : part des écoles publiques de Paris (du niveau) citées dans un secteur
  - coherence : part des secteurs à une seule école qui contiennent cette école (à 50 m près)
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

import pandas as pd
from shapely.geometry import Point, mapping, shape

PARIS = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
NIVEAUX = {"elementaire": "elementaires", "maternelle": "maternelles"}
COMPATIBLES = {"elementaire": {"elementaire", "primaire"}, "maternelle": {"maternelle", "primaire"}}
# Simplification des contours (degrés, environ 2,5 m) et coordonnées au mètre : les fichiers de la Ville sont
# très détaillés (3,8 Mo à 1 m de tolérance le 15/11/2026, pour un fichier chargé sur téléphone).
TOLERANCE = 0.000025
MOTS_VIDES = {"rue", "avenue", "av", "boulevard", "bd", "place", "pl", "square", "villa", "passage", "impasse", "allee",
              "cite", "quai", "places", "cours", "chemin", "sentier", "hameau", "rond", "point", "porte", "de", "du", "des", "la",
              "le", "les", "d", "l", "et", "a", "au", "aux", "bis", "ter", "b", "t", "elem", "mat", "poly"}


def annees_scolaires(jour: date | None = None) -> list[str]:
    """L'année précédente, l'année en cours et la suivante (une année scolaire commence en septembre)."""
    j = jour or date.today()
    s = j.year if j.month >= 9 else j.year - 1
    return [f"{a}-{a + 1}" for a in (s - 1, s, s + 1)]


def annee_montree(disponibles, jour: date | None = None) -> str | None:
    """Dernière année publiée sans dépasser la rentrée suivante ; à défaut, la plus récente."""
    precedente, courante, suivante = annees_scolaires(jour)
    for a in (suivante, courante, precedente):
        if a in disponibles:
            return a
    return max(disponibles) if len(disponibles) else None


def sources() -> dict:
    """Entrées à ajouter à SOURCES dans build.py (filtre sur trois années : une source ne perd jamais
    plus d'un tiers de ses lignes au changement d'année, ce qui déclencherait la reprise du cache)."""
    annees = ", ".join(f"'{a}'" for a in annees_scolaires())
    out = {}
    for niv, pluriel in NIVEAUX.items():
        jeu = "ecoles-elementaires" if niv == "elementaire" else "maternelles"
        out[f"secteurs_paris_{pluriel}"] = {
            "titre": f"Secteurs scolaires des écoles {'élémentaires' if niv == 'elementaire' else 'maternelles'} (Ville de Paris, ODbL)",
            "explore_base": PARIS, "explore_id": f"secteurs-scolaires-{jeu}", "datagouv": None,
            "page": f"https://opendata.paris.fr/explore/dataset/secteurs-scolaires-{jeu}/",
            "colonnes": "libelle,zone_commune,lib_etab_1,lib_etab_2,lib_etab_3,lib_etab_4,annee_scol,geo_shape",
            "filtre": f"annee_scol in ({annees})", "obligatoire": False,
        }
        out[f"ecoles_paris_{pluriel}"] = {
            "titre": f"Établissements scolaires : écoles {'élémentaires' if niv == 'elementaire' else 'maternelles'} (Ville de Paris, ODbL)",
            "explore_base": PARIS, "explore_id": f"etablissements-scolaires-{jeu}", "datagouv": None,
            "page": f"https://opendata.paris.fr/explore/dataset/etablissements-scolaires-{jeu}/",
            "colonnes": "libelle,adresse,annee_scol,geo_point_2d",
            "filtre": f"annee_scol in ({annees})", "obligatoire": False,
        }
    return out


def _outils():
    import build
    return build


def mots(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", s)


def cle_adresse(adresse: str) -> tuple[str | None, set[str]]:
    """« 41 bis rue la Fontaine » -> ("41", {"fontaine"}) ; « 24 RUE DU RETRAIT » -> ("24", {"retrait"})."""
    m = mots(adresse)
    num = m[0] if m and m[0].isdigit() else None
    return num, {w for w in m if not w.isdigit() and w not in MOTS_VIDES and len(w) > 1}


def rattacher(points: pd.DataFrame, ecoles: pd.DataFrame, niveau: str) -> tuple[dict, list]:
    """Nom de la Ville -> UAI : numéro et rue de l'adresse, puis distance (à moins de 1,5 km). À défaut,
    le nom de la Ville (« TOURNELLES (21) POLY ») retrouvé dans le nom et l'adresse de l'école de
    l'annuaire (« E.P.PU VOSGES-TOURNELLES 12 places des Vosges »), à moins de 400 m."""
    cand = ecoles[ecoles["niveau"].isin(COMPATIBLES[niveau])]
    cles = [cle_adresse(a) for a in cand["adresse"]]
    mots_cand = [set(mots(f"{n} {a}")) for n, a in zip(cand["nom"], cand["adresse"])]
    res, rates = {}, []
    for p in points.itertuples():
        num, rue = cle_adresse(p.adresse)
        nom_ville = {w for w in mots(p.libelle.split("(")[0]) if w not in MOTS_VIDES and len(w) > 1}
        meilleur = None
        for (cnum, crue), mc, e in zip(cles, mots_cand, cand.itertuples()):
            d = ((e.lon - p.lon) * 73000) ** 2 + ((e.lat - p.lat) * 111000) ** 2
            d = d ** 0.5
            if d > 1500:
                continue
            jac = len(rue & crue) / len(rue | crue) if rue | crue else 0
            par_nom = bool(nom_ville) and nom_ville <= mc and d < 400
            ok = (num and num == cnum and jac >= 0.5) or (jac >= 0.6 and d < 600) or d < 25 or par_nom
            if not ok:
                continue
            score = 3 * jac + (2 if num and num == cnum else 0) + (1 if par_nom else 0) - d / 400
            if not meilleur or score > meilleur[0]:
                meilleur = (score, e.uai, round(d))
        if meilleur:
            res[p.libelle] = (meilleur[1], meilleur[2])
        else:
            rates.append(f"{p.libelle} ({p.adresse})")
    return res, rates


def lire_points(df: pd.DataFrame, annee: str) -> pd.DataFrame:
    b = _outils()
    c_lib, c_adr = b.pick(df, r"^libelle$"), b.pick(df, r"^adresse$")
    c_an, c_pt = b.pick(df, r"annee_scol"), b.pick(df, r"geo_point")
    d = df[df[c_an] == annee]
    latlon = d[c_pt].fillna("").str.split(",", expand=True)
    out = pd.DataFrame({"libelle": d[c_lib].str.strip(), "adresse": d[c_adr].fillna(""),
                        "lat": pd.to_numeric(latlon[0], errors="coerce"), "lon": pd.to_numeric(latlon[1], errors="coerce")})
    return out.dropna(subset=["lat", "lon"]).drop_duplicates("libelle")


def arrondir(g):
    if isinstance(g, (list, tuple)):
        return [arrondir(x) for x in g] if g and isinstance(g[0], (list, tuple)) else [round(g[0], 5), round(g[1], 5)]
    return g


def construire(ecoles: pd.DataFrame, frames: dict, out_dir, problemes: list) -> dict | None:
    b = _outils()
    paris = ecoles[(ecoles["dep"] == "75") & (ecoles["secteur"] == "public")]
    features, meta = [], {"source": "Ville de Paris", "licence": "ODbL"}
    for niv, pluriel in NIVEAUX.items():
        ks, kp = f"secteurs_paris_{pluriel}", f"ecoles_paris_{pluriel}"
        if ks not in frames or kp not in frames:
            b.log(f"  ! secteurs des écoles {pluriel} de Paris indisponibles")
            problemes.append(f"secteurs des écoles {pluriel} de Paris indisponibles")
            return None
        sec = frames[ks]
        c_an = b.pick(sec, r"annee_scol")
        annee = annee_montree(set(sec[c_an].dropna()))
        sec = sec[sec[c_an] == annee]
        pts = lire_points(frames[kp], annee)
        lien, rates = rattacher(pts, paris, niv)
        loin = sorted(((d, lib) for lib, (_, d) in lien.items() if d > 50), reverse=True)
        b.log(f"  {pluriel} {annee} : {len(sec)} secteurs, {len(pts)} écoles de la Ville, {len(lien)} rattachées à un UAI "
              f"({len(loin)} à plus de 50 m : {loin[:6]}) ; non rattachées : {rates[:10]}")
        c_libs = [b.pick(sec, rf"^lib_etab_{i}$") for i in range(1, 5)]
        c_geo, c_lib = b.pick(sec, r"geo_shape"), b.pick(sec, r"^libelle$")
        cites, noms_cites, ok_commun, dedans, seuls = set(), 0, 0, 0, 0
        for s in sec.itertuples(index=False):
            r = s._asdict()
            libs = [r[c] for c in c_libs if isinstance(r[c], str) and r[c].strip()]
            uais = []
            for lib in libs:
                noms_cites += 1
                if lib.strip() in lien:
                    uais.append(lien[lib.strip()][0])
            uais = list(dict.fromkeys(uais))
            ok_commun += len(uais) == len(libs)
            cites.update(uais)
            try:
                g = shape(json.loads(r[c_geo])).buffer(0)
            except (TypeError, ValueError):
                continue
            if len(libs) == 1 and uais:
                seuls += 1
                e = paris[paris["uai"] == uais[0]]
                if len(e) and g.buffer(0.0005).contains(Point(e.iloc[0]["lon"], e.iloc[0]["lat"])):
                    dedans += 1
            g = g.simplify(TOLERANCE, preserve_topology=True)
            features.append({"type": "Feature", "geometry": {"type": g.geom_type, "coordinates": arrondir(mapping(g)["coordinates"])},
                             "properties": {"niveau": niv, "uais": " ".join(uais), "commun": len(libs) > 1, "noms": " / ".join(libs)}})
        attendues = set(paris[paris["niveau"].isin(COMPATIBLES[niv])]["uai"])
        nb_rattaches = sum(1 for s in sec.itertuples(index=False) for c in c_libs
                           if isinstance(s._asdict()[c], str) and s._asdict()[c].strip() in lien)
        meta[niv] = {
            "annee": annee, "secteurs": len(sec), "communs": int(sum(1 for f in features if f["properties"]["niveau"] == niv and f["properties"]["commun"])),
            "rattachement": round(nb_rattaches / noms_cites, 3) if noms_cites else 0,
            "couverture": round(len(cites & attendues) / len(attendues), 3) if attendues else 0,
            "coherence": round(dedans / seuls, 3) if seuls else 0,
            "non_rattachees": rates[:20], "absentes": sorted(attendues - cites)[:30],
        }
        b.log(f"  contrôle {pluriel} : {json.dumps({k: v for k, v in meta[niv].items() if k not in ('non_rattachees', 'absentes')}, ensure_ascii=False)} ; "
              f"écoles publiques sans secteur : {len(attendues - cites)} {sorted(attendues - cites)[:15]}")
    meta["annee"] = meta["elementaire"]["annee"]
    dossier = out_dir / "secteurs-ecoles"
    dossier.mkdir(exist_ok=True)
    for f in dossier.glob("*"):
        f.unlink()
    texte = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    (dossier / "75.geojson").write_text(texte, encoding="utf-8")
    # Emprise : bornes de chaque zone (l'arrondi des coordonnées peut rendre une union invalide).
    bornes = [shape(f["geometry"]).bounds for f in features]
    emprise = (min(x[0] for x in bornes), min(x[1] for x in bornes), max(x[2] for x in bornes), max(x[3] for x in bornes))
    (dossier / "index.json").write_text(json.dumps({"75": {
        "bbox": [round(x, 4) for x in emprise], "annee": meta["annee"], "source": "Ville de Paris", "zones": len(features)}},
        ensure_ascii=False), encoding="utf-8")
    b.log(f"  secteurs des écoles de Paris : {len(features)} zones, {len(texte) / 1e6:.2f} Mo")
    return {"75": meta}
