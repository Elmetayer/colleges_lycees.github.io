"""Zones des écoles déduites de l'annuaire : la « règle de la commune » (jalon 7d, choix de Bruno du 16/11/2026).

Appelé par build.py après secteurs_ecoles.py. Les secteurs des écoles sont fixés par chaque commune et rares sont
celles qui les publient (secteurs_ecoles.py). Mais quand une commune n'a qu'une seule école publique d'un niveau,
tous les enfants de la commune y sont inscrits : la zone de l'école est la commune entière. Et les communes qui
ont regroupé leurs écoles (regroupement pédagogique intercommunal dispersé, RPI) partagent leurs écoles : chaque
école accueille certaines classes pour les enfants de toutes les communes du regroupement.

Sources (toutes déjà lues par build.py, sauf les contours) :
  - annuaire_education : code INSEE de la commune de chaque école (code_commune), rpi_concentre (0/1 : l'école
    accueille aussi les enfants de communes voisines, sur un seul site) et rpi_disperse (code du regroupement,
    partagé par ses écoles) ;
  - effectifs_ecoles : élèves par niveau (préélémentaire, CP à CM2) de la dernière rentrée, pour dire quelle école
    d'un RPI dispersé accueille quelles classes ;
  - contours des communes : geo.api.gouv.fr (découpage administratif, Licence Ouverte), un appel par département,
    gardés dans le cache des sources (--cache-dir) et repris si le service ne répond pas.

Règles, niveau par niveau (élémentaire : écoles élémentaires et primaires ; maternelle : maternelles et primaires ;
écoles publiques, hors écoles spécialisées) :
  1. RPI dispersé : ses communes sont celles de ses écoles (les communes membres sans école ne sont dans aucune donnée
     nationale). Si, dans chacune de ces communes, toutes les écoles publiques du niveau appartiennent au RPI, la zone
     du niveau est la réunion de ces communes, rattachée aux écoles du RPI qui ont ce niveau. Sinon (une commune garde
     une autre école), le RPI n'a pas de zone.
  2. Commune hors RPI dispersé avec une seule école publique du niveau : la zone est la commune.
  3. Paris, Lyon, Marseille et les communes dont la ville publie ses secteurs (secteurs_ecoles.py) sont écartées.

Sortie : <out>/zones-communes/<dep>.geojson (un fichier par département, chargé par la carte avec les écoles) et
index.json (emprise, zones). Propriétés : niveau, uais, regle (commune | rpi), noms (commune ou communes du RPI),
rpi (code), concentre (école en RPI concentré), classes (« UAI:CP,CE1;UAI:CE2,CM1,CM2 », RPI seulement), rentree.
Renvoie le bloc "zones_communes" de meta.json (chiffres par niveau, exemples), lu par la vérification, la page de
suivi et la documentation.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict

import pandas as pd
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

GEO = "https://geo.api.gouv.fr"
PAGE_CONTOURS = "https://geo.api.gouv.fr/decoupage-administratif/communes"
# Contours simplifiés à environ 20 m (zones affichées à partir du zoom 12, à l'échelle d'une commune) et coordonnées
# à 5 décimales : un département pèse quelques centaines de kilo-octets.
TOLERANCE = 0.0002
NIVEAUX = ("elementaire", "maternelle")
COMPATIBLES = {"elementaire": {"elementaire", "primaire"}, "maternelle": {"maternelle", "primaire"}}
# Codes INSEE des arrondissements de Paris, Lyon et Marseille (l'annuaire les donne à la place de la commune) et des
# trois communes : beaucoup d'écoles, et Paris publie ses secteurs.
PLM = ("751", "6938", "132", "75056", "69123", "13055")
CLASSES = [("preelementaire", "maternelle"), ("cp", "CP"), ("ce1", "CE1"), ("ce2", "CE2"), ("cm1", "CM1"), ("cm2", "CM2")]


def _outils():
    import build
    return build


def dep_geo(dep: str) -> str:
    """Département de l'annuaire (« 1 », « 2A ») -> code de geo.api.gouv.fr (« 01 », « 2A »)."""
    return dep.zfill(2) if dep.isdigit() else dep


def contours(deps, cache_dir, problemes: list) -> tuple[dict, dict]:
    """Contours des communes : {code INSEE: (nom, géométrie)} et le compte rendu (départements lus, repris, absents)."""
    b = _outils()
    res, bilan = {}, {"lus": 0, "repris": [], "absents": []}
    dossier = (cache_dir / "contours-communes") if cache_dir else None
    for dep in sorted(set(deps)):
        d = dep_geo(dep)
        brut = None
        try:
            r = b.HTTP.get(f"{GEO}/departements/{d}/communes", params={"fields": "code,nom", "format": "geojson", "geometry": "contour"}, timeout=120)
            r.raise_for_status()
            brut = r.content
            json.loads(brut)
            bilan["lus"] += 1
            if dossier:
                dossier.mkdir(parents=True, exist_ok=True)
                (dossier / f"{d}.geojson.gz").write_bytes(gzip.compress(brut, compresslevel=6))
        except Exception as exc:  # noqa: BLE001
            f = dossier / f"{d}.geojson.gz" if dossier else None
            if f and f.exists():
                brut = gzip.decompress(f.read_bytes())
                bilan["repris"].append(d)
                b.log(f"  ! contours {d} : {exc} ; version précédente reprise")
            else:
                bilan["absents"].append(d)
                b.log(f"  ! contours {d} : {exc} ; aucune version à reprendre")
                continue
        for f in json.loads(brut).get("features", []):
            if f.get("geometry"):
                try:
                    res[f["properties"]["code"]] = (f["properties"].get("nom") or "", shape(f["geometry"]).buffer(0))
                except Exception:  # noqa: BLE001
                    pass
    if bilan["repris"]:
        problemes.append(f"contours des communes : geo.api.gouv.fr injoignable pour {', '.join(bilan['repris'])}, versions précédentes reprises")
    if bilan["absents"]:
        problemes.append(f"contours des communes indisponibles pour {', '.join(bilan['absents'])} : pas de zones de communes dans ces départements")
    return res, bilan


def lire_annuaire(df: pd.DataFrame) -> pd.DataFrame | None:
    b = _outils()
    c_uai = b.pick(df, r"identifiant_de_l_etablissement|^uai$|numero_uai")
    c_com = b.pick(df, r"^code_commune$", required=False)
    if not c_com:
        b.log("  ! annuaire sans code_commune (version du cache antérieure au 16/11/2026 ?) : zones des communes non calculées")
        return None
    c_rc, c_rd = b.pick(df, r"^rpi_concentre$", required=False), b.pick(df, r"^rpi_disperse$", required=False)
    txt = lambda c: df[c].fillna("").astype(str).str.strip() if c else pd.Series("", index=df.index)
    out = pd.DataFrame({"uai": txt(c_uai).str.upper(), "insee": txt(c_com).str.zfill(5),
                        "concentre": b.num(txt(c_rc)) == 1, "rpi": txt(c_rd)})
    out.loc[out["rpi"].isin(["0", "nan", "None"]), "rpi"] = ""
    b.log(f"  annuaire : {len(out)} lignes ; colonnes commune={c_com} rpi_concentre={c_rc} rpi_disperse={c_rd}")
    return out.drop_duplicates("uai")


def lire_classes(df: pd.DataFrame | None) -> tuple[dict, dict, str | None]:
    """Dernière rentrée publiée : {UAI: [« maternelle », « CP », …]} (niveaux qui ont des élèves) et
    {UAI: (élèves de maternelle, élèves d'élémentaire)}."""
    if df is None:
        return {}, {}, None
    b = _outils()
    c_uai = b.pick(df, r"^numero_ecole$|^uai$|numero_uai")
    c_an = b.pick(df, r"rentree|^annee")
    rentrees = df[c_an].astype(str).str[:4]
    derniere = rentrees.max()
    d = df[rentrees == derniere]
    uais = d[c_uai].astype(str).str.strip().str.upper()
    cols = {lib: b.pick(d, rf"nombre_eleves_{cle}_hors_ulis|nombre_eleves_{cle}$", required=False) for cle, lib in CLASSES}
    c_elem = b.pick(d, r"nombre_eleves_elementaire_hors_ulis", required=False)
    c_ulis = b.pick(d, r"nombre_eleves_ulis", required=False)
    zero = pd.Series(0.0, index=d.index)
    val = lambda c: b.num(d[c]).fillna(0) if c else zero
    mat = val(cols["maternelle"])
    elem = (val(c_elem) + val(c_ulis)) if c_elem else sum(val(cols[l]) for l in ("CP", "CE1", "CE2", "CM1", "CM2"))
    eleves = {u: (float(m), float(e)) for u, m, e in zip(uais, mat, elem)}
    if not any(cols.values()):
        b.log("  ! effectifs sans détail par niveau : répartition des classes des RPI non connue")
        return {}, eleves, derniere
    presents = {lib: val(c) > 0 for lib, c in cols.items() if c}
    classes = {u: [lib for lib in presents if presents[lib].iloc[i]] for i, u in enumerate(uais)}
    b.log(f"  effectifs par niveau : {len(classes)} écoles, rentrée {derniere} ; colonnes {cols}")
    return classes, eleves, derniere


def arrondir(g):
    if isinstance(g, (list, tuple)):
        return [arrondir(x) for x in g] if g and isinstance(g[0], (list, tuple)) else [round(g[0], 5), round(g[1], 5)]
    return g


def feature(g, props: dict) -> dict:
    g = g.simplify(TOLERANCE, preserve_topology=True)
    return {"type": "Feature", "geometry": {"type": g.geom_type, "coordinates": arrondir(mapping(g)["coordinates"])},
            "properties": {k: v for k, v in props.items() if v not in (None, "", False)}}


def construire(ecoles: pd.DataFrame, frames: dict, out_dir, problemes: list, cache_dir=None, villes: dict | None = None) -> dict | None:
    """ecoles : tableau des écoles d'ecoles.py (uai, nom, nature, niveau, secteur, dep, commune) ; villes : index des
    secteurs publiés par les villes (pour écarter leurs communes)."""
    b = _outils()
    dossier = out_dir / "zones-communes"
    dossier.mkdir(exist_ok=True)
    for f in dossier.glob("*"):
        f.unlink()
    if "annuaire_education" not in frames:
        b.log("  ! annuaire de l'éducation indisponible : zones des communes non calculées")
        problemes.append("zones des communes : annuaire de l'éducation indisponible")
        return None
    ann = lire_annuaire(frames["annuaire_education"])
    if ann is None:
        problemes.append("zones des communes : annuaire sans code commune")
        return None
    classes, eleves, rentree = lire_classes(frames.get("effectifs_ecoles"))

    pub = ecoles[(ecoles["secteur"] == "public")].copy()
    pub = pub[~pub["nature"].str.contains("specialis", na=False)]
    pub = pub.merge(ann, on="uai", how="left")
    sans_code = pub["insee"].isna() | (pub["insee"] == "")
    if sans_code.any():
        b.log(f"  ! {int(sans_code.sum())} écoles publiques sans code commune dans l'annuaire : {pub.loc[sans_code, 'uai'].tolist()[:10]}")
    pub = pub[~sans_code]
    pub["rpi"] = pub["rpi"].fillna("")
    pub["concentre"] = pub["concentre"].fillna(False).astype(bool)
    # Communes écartées : Paris, Lyon, Marseille et villes qui publient leurs secteurs.
    villes_noms = {(v.get("dep"), c) for v in (villes or {}).values() for c in (v.get("communes") or [])}
    ecartee = pub["insee"].str.startswith(PLM) | pd.Series([(d, c) in villes_noms for d, c in zip(pub["dep"], pub["commune"])], index=pub.index)
    communes_ecartees = sorted(set(pub.loc[ecartee, "insee"]))
    communes_avec_ecole = set(pub["insee"])
    idx_el = {"maternelle": 0, "elementaire": 1}
    total_eleves = {niv: sum(eleves.get(u, (0, 0))[idx_el[niv]] for u, n in zip(pub["uai"], pub["niveau"]) if n in COMPATIBLES[niv]) for niv in NIVEAUX}
    pub = pub[~ecartee]
    b.log(f"  {len(pub)} écoles publiques ordinaires, {pub['insee'].nunique()} communes ; "
          f"{int((pub['rpi'] != '').sum())} écoles en RPI dispersé ({pub.loc[pub['rpi'] != '', 'rpi'].nunique()} regroupements), "
          f"{int(pub['concentre'].sum())} en RPI concentré ; communes écartées (PLM, villes à secteurs) : {len(communes_ecartees)}")

    geo, bilan_contours = contours(pub["dep"].unique(), cache_dir, problemes)
    b.log(f"  contours : {len(geo)} communes, {bilan_contours['lus']} départements lus, repris {bilan_contours['repris']}, absents {bilan_contours['absents']}")

    par_commune = {niv: defaultdict(list) for niv in NIVEAUX}
    for e in pub.itertuples():
        for niv in NIVEAUX:
            if e.niveau in COMPATIBLES[niv]:
                par_commune[niv][e.insee].append(e)
    rpis = defaultdict(list)
    for e in pub[pub["rpi"] != ""].itertuples():
        rpis[e.rpi].append(e)
    nom_commune = lambda c: geo[c][0] if c in geo else next((e.commune for niv in NIVEAUX for e in par_commune[niv].get(c, [])), c)

    features = defaultdict(list)  # département -> zones
    meta = {"rentree_classes": rentree, "contours": {**bilan_contours, "communes": len(geo), "page": PAGE_CONTOURS},
            "communes_ecartees": len(communes_ecartees), "exemples": {}}
    inconnues = set()
    for niv in NIVEAUX:
        couvertes, n_rpi, communes_rpi, ecoles_zone, rpi_refuses = set(), 0, 0, set(), []
        for code, membres in sorted(rpis.items()):
            du_niveau = [e for e in membres if e.niveau in COMPATIBLES[niv]]
            if not du_niveau:
                continue
            communes = sorted({e.insee for e in membres})
            uais = {e.uai for e in membres}
            autres = [c for c in communes if any(e.uai not in uais for e in par_commune[niv].get(c, []))]
            if autres:
                rpi_refuses.append(f"{code} ({', '.join(nom_commune(c) for c in autres)})")
                continue
            geoms = [geo[c][1] for c in communes if c in geo]
            inconnues.update(c for c in communes if c not in geo)
            if not geoms:
                continue
            g = unary_union(geoms).buffer(0)
            repartition = ";".join(f"{e.uai}:{','.join(classes.get(e.uai, []))}" for e in sorted(du_niveau, key=lambda e: e.uai))
            features[du_niveau[0].dep].append(feature(g, {
                "niveau": niv, "regle": "rpi", "rpi": code, "uais": " ".join(sorted(e.uai for e in du_niveau)),
                "noms": " / ".join(nom_commune(c) for c in communes), "classes": repartition if classes else None}))
            couvertes.update(communes)
            ecoles_zone.update(e.uai for e in du_niveau)
            n_rpi += 1
            communes_rpi += len(communes)
            if niv == "elementaire" and len(communes) >= 2 and "rpi" not in meta["exemples"]:
                meta["exemples"]["rpi"] = du_niveau[0].uai
        n_commune, concentres = 0, 0
        for c, liste in sorted(par_commune[niv].items()):
            if c in couvertes or len(liste) != 1 or liste[0].rpi:
                continue
            if c not in geo:
                inconnues.add(c)
                continue
            e = liste[0]
            features[e.dep].append(feature(geo[c][1], {"niveau": niv, "regle": "commune", "uais": e.uai, "noms": nom_commune(c), "concentre": bool(e.concentre)}))
            ecoles_zone.add(e.uai)
            n_commune += 1
            concentres += bool(e.concentre)
            if niv == "elementaire" and not e.concentre and "commune" not in meta["exemples"]:
                meta["exemples"]["commune"] = e.uai
        plusieurs = sum(1 for c, l in par_commune[niv].items() if len(l) >= 2 and c not in couvertes)
        n_el = sum(eleves.get(u, (0, 0))[idx_el[niv]] for u in ecoles_zone)
        meta[niv] = {"eleves": int(n_el), "eleves_public": int(total_eleves[niv]), "part_eleves": round(n_el / total_eleves[niv], 3) if total_eleves[niv] else None,
                     "zones_commune": n_commune, "dont_concentre": concentres, "zones_rpi": n_rpi, "communes_rpi": communes_rpi,
                     "communes": n_commune + communes_rpi, "ecoles": len(ecoles_zone), "rpi_sans_zone": len(rpi_refuses),
                     "communes_plusieurs_ecoles": plusieurs}
        b.log(f"  {niv} : {n_commune} communes à une seule école ({concentres} en RPI concentré), {n_rpi} RPI dispersés sur {communes_rpi} communes, "
              f"{len(ecoles_zone)} écoles ; {len(rpi_refuses)} RPI sans zone (une commune garde une autre école) : {rpi_refuses[:8]} ; "
              f"{plusieurs} communes à plusieurs écoles (hors de cette règle)")
    meta["communes_sans_ecole"] = len(set(geo) - communes_avec_ecole)
    meta["codes_inconnus"] = sorted(inconnues)[:30]
    meta["nb_codes_inconnus"] = len(inconnues)
    if inconnues:
        b.log(f"  ! {len(inconnues)} codes commune de l'annuaire absents des contours (communes fusionnées ?) : {sorted(inconnues)[:15]}")

    index = {}
    compact = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for dep, fs in sorted(features.items()):
        texte = compact({"type": "FeatureCollection", "features": fs})
        (dossier / f"{dep}.geojson").write_text(texte, encoding="utf-8")
        bornes = [shape(f["geometry"]).bounds for f in fs]
        index[dep] = {"dep": dep, "bbox": [round(min(x[0] for x in bornes), 4), round(min(x[1] for x in bornes), 4),
                                           round(max(x[2] for x in bornes), 4), round(max(x[3] for x in bornes), 4)],
                      "zones": len(fs)}
    if not index:
        return None
    (dossier / "index.json").write_text(compact(index), encoding="utf-8")
    tailles = sorted(((f.stat().st_size, f.name) for f in dossier.glob("*.geojson")), reverse=True)
    meta["taille_mo"] = round(sum(s for s, _ in tailles) / 1e6, 2)
    meta["departements"] = len(index)
    b.log(f"  {len(index)} départements, {sum(v['zones'] for v in index.values())} zones, {meta['taille_mo']} Mo "
          f"(plus gros : {', '.join(f'{n} {s / 1e3:.0f} ko' for s, n in tailles[:3])}) ; exemples {meta['exemples']}")
    return meta
