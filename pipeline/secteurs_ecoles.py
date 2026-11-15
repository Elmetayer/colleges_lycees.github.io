"""Secteurs des écoles publiques publiés par les villes (jalon 7b : Paris ; 7c : autres villes).

Appelé par build.py après ecoles.py. Un fichier par ville : <out>/secteurs-ecoles/<id>.geojson, décrit dans
<out>/secteurs-ecoles/index.json (département, communes couvertes, source, année ou date de mise à jour, emprise).

Paris (opendata.paris.fr, Ville de Paris, licence ODbL) :
  - secteurs_paris_elementaires / secteurs_paris_maternelles : un polygone par secteur, avec les
    noms des écoles du secteur (lib_etab_1 à 4 ; « secteur commun » quand il y en a plusieurs) ;
  - ecoles_paris_elementaires / ecoles_paris_maternelles : les écoles (nom, adresse, position).
  Les fichiers de la Ville ne donnent pas le code UAI des écoles : chaque nom est rattaché à une école
  de l'annuaire national en croisant le numéro et la rue de l'adresse avec la distance (diagnostic du
  15/11/2026 : 33 écoles à plus de 50 m de leur point dans l'annuaire).
  Année montrée : la dernière publiée, sans dépasser la rentrée suivante (les familles préparent les
  inscriptions dès que la Ville publie les secteurs de la rentrée suivante, vers mars).

Autres villes (VILLES) : un polygone par secteur, nommé d'après son école (« L. DE VINCI », « Louis Pergaud »),
sans année scolaire (la date de mise à jour du jeu est montrée à la place). L'école est cherchée parmi les écoles
publiques de l'annuaire situées dans la zone (à 150 m près), du niveau de la zone, par les mots du nom ; à défaut
de nom reconnu, l'unique école du niveau située dans la zone (diagnostic du 15/11/2026 : à Strasbourg, chaque
école publique est dans une zone de chaque niveau, et l'école nommée y est toujours).

Propriétés des zones : niveau (maternelle | elementaire), uais (codes UAI séparés par des espaces),
commun (secteur de plusieurs écoles), noms (ceux de la ville).
Renvoie le bloc "secteurs" de meta.json ecoles (un bloc par fichier), avec les contrôles lus par tests/verifier_site.py :
  - rattachement : part des écoles nommées (Paris) ou des zones (autres villes) rattachées à un UAI
  - couverture : part des écoles publiques de la ville (du niveau) citées dans un secteur
  - coherence : Paris, part des secteurs à une seule école qui contiennent cette école (à 50 m près) ;
    autres villes, part des zones rattachées par le nom (et non par l'unique école de la zone)
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
    for vid, v in VILLES.items():
        for jeu in dict.fromkeys(v["jeux"].values()):
            out[cle_source(vid, jeu)] = {
                "titre": f"{v['titres'][jeu]} ({v['source']}, {v['licence']})",
                "explore_base": f"{v['portail']}/api/explore/v2.1/catalog/datasets", "explore_id": jeu, "datagouv": None,
                "page": f"{v['portail']}/explore/dataset/{jeu}/",
                "colonnes": ",".join([v["nom"]] + ([v["type"]] if v.get("type") else []) + ["geo_shape"]), "obligatoire": False,
            }
    return out


def cle_source(vid: str, jeu: str) -> str:
    return f"secteurs_{vid.split('-', 1)[1]}_{re.sub(r'[^a-z0-9]+', '_', jeu.lower())}"[:60]


# Autres villes. jeux : niveau -> jeu Explore ; "*" : un seul jeu pour les deux niveaux, la colonne type disant
# à quels niveaux s'applique chaque zone (types : valeur -> niveaux).
VILLES = {
    "67-strasbourg": {
        "dep": "67", "communes": ["Strasbourg"], "source": "Ville de Strasbourg", "licence": "Licence Ouverte",
        "portail": "https://data.strasbourg.eu", "nom": "nom_secteur",
        "jeux": {"elementaire": "secteurs_scolaires_ecoles_elementaires", "maternelle": "secteurs_scolaires_ecoles_maternelles"},
        "titres": {"secteurs_scolaires_ecoles_elementaires": "Secteurs scolaires des écoles élémentaires",
                   "secteurs_scolaires_ecoles_maternelles": "Secteurs scolaires des écoles maternelles"},
    },
    "44-nantes": {
        "dep": "44", "communes": ["Nantes"], "source": "Ville de Nantes", "licence": "Licence Ouverte",
        "portail": "https://data.nantesmetropole.fr", "nom": "lib", "type": "type",
        "jeux": {"*": "244400404_perimetres-scolaires-nantes"},
        "types": {"M": ["maternelle"], "E": ["elementaire"], "P": ["maternelle", "elementaire"]},
        "titres": {"244400404_perimetres-scolaires-nantes": "Périmètres scolaires de la ville de Nantes"},
    },
}
# Mots sans valeur pour reconnaître une école à son nom ; abréviations des noms de secteurs.
MOTS_ECOLE = {"ecole", "ecoles", "groupe", "scolaire", "gs", "maternelle", "mat", "elementaire", "elem", "elelentaire", "primaire",
              "publique", "public", "pu", "ep", "de", "du", "des", "la", "le", "les", "d", "l", "et", "a", "au", "aux", "en"}
ABREVIATIONS = {"st": "saint", "ste": "sainte", "sts": "saints"}
# Une école est cherchée dans sa zone à cette marge près (degrés, environ 150 m) : écoles en limite de secteur.
MARGE = 0.0015


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


def zone(g, props: dict) -> dict:
    g = g.simplify(TOLERANCE, preserve_topology=True)
    return {"type": "Feature", "geometry": {"type": g.geom_type, "coordinates": arrondir(mapping(g)["coordinates"])}, "properties": props}


def construire_paris(ecoles: pd.DataFrame, frames: dict, problemes: list) -> tuple[list, dict] | None:
    b = _outils()
    paris = ecoles[(ecoles["dep"] == "75") & (ecoles["secteur"] == "public")]
    features, meta = [], {}
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
        c_geo = b.pick(sec, r"geo_shape")
        cites, noms_cites, nb_rattaches, dedans, seuls = set(), 0, 0, 0, 0
        for s in sec.itertuples(index=False):
            r = s._asdict()
            libs = [r[c].strip() for c in c_libs if isinstance(r[c], str) and r[c].strip()]
            noms_cites += len(libs)
            nb_rattaches += sum(lib in lien for lib in libs)
            uais = list(dict.fromkeys(lien[lib][0] for lib in libs if lib in lien))
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
            features.append(zone(g, {"niveau": niv, "uais": " ".join(uais), "commun": len(libs) > 1, "noms": " / ".join(libs)}))
        attendues = set(paris[paris["niveau"].isin(COMPATIBLES[niv])]["uai"])
        meta[niv] = {
            "annee": annee, "secteurs": len(sec), "communs": int(sum(1 for f in features if f["properties"]["niveau"] == niv and f["properties"]["commun"])),
            "rattachement": round(nb_rattaches / noms_cites, 3) if noms_cites else 0,
            "couverture": round(len(cites & attendues) / len(attendues), 3) if attendues else 0,
            "coherence": round(dedans / seuls, 3) if seuls else 0,
            "non_rattachees": rates[:20], "absentes": sorted(attendues - cites)[:30],
        }
    meta["annee"] = meta["elementaire"]["annee"]
    return features, meta


def mots_nom(s: str) -> list[str]:
    """« ERC.CHATRIAN » -> [erc, chatrian] ; « Ecole maternelle Sainte-Aurèlie » -> [sainte, aurelie]."""
    return [ABREVIATIONS.get(w, w) for w in mots(s) if w not in MOTS_ECOLE and (len(w) > 1 or w.isdigit())]


def score_nom(nom_zone: list[str], nom_ecole: list[str]) -> float:
    """Part des mots du nom de la zone retrouvés dans le nom de l'école (un mot abrégé suffit : « erc » pour
    « erckmann ») ; les numéros (« Guynemer 1 & 2 ») comptent comme les autres mots."""
    if not nom_zone:
        return 0
    trouves = sum(1 for w in nom_zone if any(e == w or (len(w) >= 3 and not w.isdigit() and e.startswith(w)) for e in nom_ecole))
    return trouves / len(nom_zone)


def rattacher_zone(g, nom: str, cand: pd.DataFrame) -> tuple[list[str], str]:
    """Écoles d'une zone : celles du niveau situées dans la zone dont le nom correspond le mieux (ex aequo : secteur
    commun) ; sinon l'unique école du niveau située dans la zone. Renvoie (UAI, "nom" | "seule" | "")."""
    large = g.buffer(MARGE)
    ici = cand[[large.contains(Point(x, y)) for x, y in zip(cand["lon"], cand["lat"])]]
    mz = mots_nom(nom)
    scores = [(score_nom(mz, mots_nom(n)), u) for n, u in zip(ici["nom"], ici["uai"])]
    meilleur = max((s for s, _ in scores), default=0)
    if meilleur >= 0.5:
        return [u for s, u in scores if s == meilleur], "nom"
    strict = [u for u, x, y in zip(ici["uai"], ici["lon"], ici["lat"]) if g.contains(Point(x, y))]
    if len(strict) == 1:
        return strict, "seule"
    return [], ""


def construire_ville(vid: str, v: dict, ecoles: pd.DataFrame, frames: dict, resolved: dict, problemes: list) -> tuple[list, dict] | None:
    b = _outils()
    publiques = ecoles[(ecoles["dep"] == v["dep"]) & (ecoles["secteur"] == "public")]
    de_la_ville = publiques[publiques["commune"].isin(v["communes"])]
    features, meta = [], {}
    maj = max((str((resolved.get(cle_source(vid, j)) or {}).get("maj") or "")[:10] for j in v["jeux"].values()), default="") or None
    zones_par_niveau = {"maternelle": [], "elementaire": []}
    for niv_jeu, jeu in v["jeux"].items():
        k = cle_source(vid, jeu)
        if k not in frames:
            b.log(f"  ! {v['source']} : {jeu} indisponible")
            problemes.append(f"secteurs des écoles ({v['source']}) : {jeu} indisponible")
            return None
        df = frames[k]
        c_nom, c_geo = b.pick(df, rf"^{v['nom']}$"), b.pick(df, r"geo_shape")
        c_type = b.pick(df, rf"^{v['type']}$") if v.get("type") else None
        inconnus = set()
        for r in df.itertuples(index=False):
            r = r._asdict()
            niveaux = [niv_jeu] if niv_jeu != "*" else v["types"].get(str(r[c_type]).strip(), [])
            if not niveaux:
                inconnus.add(r[c_type])
            try:
                g = shape(json.loads(r[c_geo])).buffer(0)
            except (TypeError, ValueError):
                continue
            for niv in niveaux:
                zones_par_niveau[niv].append((str(r[c_nom] or "").strip(), g))
        if inconnus:
            b.log(f"  ! {v['source']} : types de zones inconnus {sorted(map(str, inconnus))}")
    for niv, zones in zones_par_niveau.items():
        cand = publiques[publiques["niveau"].isin(COMPATIBLES[niv])]
        cites, par_nom, rattachees, rates = set(), 0, 0, []
        for nom, g in zones:
            uais, comment = rattacher_zone(g, nom, cand)
            rattachees += bool(uais)
            par_nom += comment == "nom"
            if not uais:
                rates.append(nom)
            cites.update(uais)
            features.append(zone(g, {"niveau": niv, "uais": " ".join(uais), "commun": len(uais) > 1, "noms": nom}))
        attendues = set(de_la_ville[de_la_ville["niveau"].isin(COMPATIBLES[niv])]["uai"])
        absentes = de_la_ville[de_la_ville["uai"].isin(attendues - cites)]
        meta[niv] = {
            "annee": None, "maj": maj, "secteurs": len(zones), "communs": sum(1 for f in features if f["properties"]["niveau"] == niv and f["properties"]["commun"]),
            "rattachement": round(rattachees / len(zones), 3) if zones else 0,
            "couverture": round(len(cites & attendues) / len(attendues), 3) if attendues else 0,
            "coherence": round(par_nom / rattachees, 3) if rattachees else 0,
            "non_rattachees": rates[:20], "absentes": sorted(f"{u} {n}" for u, n in zip(absentes["uai"], absentes["nom"]))[:30],
        }
    meta["annee"], meta["maj"] = None, maj
    return features, meta


def construire(ecoles: pd.DataFrame, frames: dict, out_dir, problemes: list, resolved: dict | None = None) -> dict | None:
    b = _outils()
    dossier = out_dir / "secteurs-ecoles"
    dossier.mkdir(exist_ok=True)
    for f in dossier.glob("*"):
        f.unlink()
    index, metas = {}, {}
    fichiers = [("75", {"dep": "75", "communes": None, "source": "Ville de Paris", "licence": "ODbL"})] + list(VILLES.items())
    for fid, v in fichiers:
        b.log(f"  -- {v['source']}")
        res = (construire_paris(ecoles, frames, problemes) if fid == "75"
               else construire_ville(fid, v, ecoles, frames, resolved or {}, problemes))
        if not res:
            continue
        features, meta = res
        for niv in NIVEAUX:
            c = meta[niv]
            b.log(f"  contrôle {v['source']} {niv} : {json.dumps({k: x for k, x in c.items() if k not in ('non_rattachees', 'absentes')}, ensure_ascii=False)} ; "
                  f"zones non rattachées : {c['non_rattachees'][:10]} ; écoles publiques sans secteur : {len(c['absentes'])} {c['absentes'][:15]}")
        texte = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        (dossier / f"{fid}.geojson").write_text(texte, encoding="utf-8")
        # Emprise : bornes de chaque zone (l'arrondi des coordonnées peut rendre une union invalide).
        bornes = [shape(f["geometry"]).bounds for f in features]
        emprise = (min(x[0] for x in bornes), min(x[1] for x in bornes), max(x[2] for x in bornes), max(x[3] for x in bornes))
        index[fid] = {"dep": v["dep"], "communes": v["communes"], "bbox": [round(x, 4) for x in emprise], "annee": meta["annee"],
                      "maj": meta.get("maj"), "source": v["source"], "licence": v["licence"], "zones": len(features)}
        metas[fid] = dict(meta, source=v["source"], licence=v["licence"])
        b.log(f"  {v['source']} : {len(features)} zones, {len(texte) / 1e6:.2f} Mo")
    if not index:
        return None
    (dossier / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    return metas
