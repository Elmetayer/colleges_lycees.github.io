"""Données des écoles (France métropolitaine).

Appelé par build.py. Lit quatre jeux open data déjà téléchargés :
  - ips_ecoles       : indices de position sociale des écoles (à partir de la rentrée 2022)
  - effectifs_ecoles : effectifs d'élèves et nombre de classes par école
  - taille_classes   : taille moyenne des classes, comparée à la commune, la circonscription,
                       l'académie et la France
  - annuaire_education : type de contrat des écoles privées, maternelle ou élémentaire,
                       éducation prioritaire, circonscription
Aucun résultat d'évaluation nationale n'est publié école par école (diagnostic du 14/11/2026) :
la fiche décrit l'école et ses élèves, pas leur niveau. Les privées hors contrat n'ont ni
effectifs, ni IPS, ni taille des classes publiés.

Les écoles sont trop nombreuses (environ 46 000) pour un seul fichier : elles sont écrites par
département et chargées par la carte à partir du zoom ZOOM_ECOLES (app.js).
  - <out>/ecoles/<dep>.geojson       : points légers (dernière valeur de chaque indicateur)
  - <out>/ecoles/index.json          : emprise et nombre d'écoles de chaque département
  - <out>/ecoles/recherche.json      : nom, commune et position de chaque école, pour la recherche
  - <out>/fiches/ecoles-<dep>.json   : IPS par année avec rangs, taille des classes, effectifs
Renvoie le bloc "ecoles" de meta.json (effectifs, périodes, couleurs, médianes).
"""

from __future__ import annotations

import json
import re

import pandas as pd

# Natures de l'annuaire retenues (normalisées) : maternelles, élémentaires et primaires,
# y compris d'application et spécialisées. Écartées : écoles sans effectifs permanents,
# écoles régionales du premier degré, écoles secondaires et professionnelles spécialisées.
NATURES = re.compile(r"^ecole_(maternelle|de_niveau_elementaire|elementaire_d_application)")

# Noms abrégés (surtout à Paris) : « E.E.PU DE LA SAIDA 20 rue de la Saïda ».
ABREGE = re.compile(r"^E\.(E|M|P)\.(?:A\.)?(?:PU|PR)\b", re.IGNORECASE)
BASE = {"E": "École élémentaire", "M": "École maternelle", "P": "École primaire"}
PETITS_MOTS = {"de", "du", "des", "la", "le", "les", "et", "d", "l", "aux", "au", "en", "sur", "sous", "a", "à"}

# Quantiles des couleurs de la carte (comme domaine() dans app.js), calculés sur toute la
# France métropolitaine : les écoles étant chargées par département, les couleurs ne doivent
# pas dépendre des départements chargés.
QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]

# Index de recherche : début de nom remplacé par un numéro (fichier plus léger), repris par app.js.
PREFIXES = ["", "École élémentaire ", "École maternelle ", "École primaire "]


def _outils():
    # Import tardif : build.py importe ce module.
    import build
    return build


def joli(s: str) -> str:
    """« DE LA SAIDA » -> « de la Saida », « JEAN-BAPTISTE LEBAS » -> « Jean-Baptiste Lebas »."""
    mots = []
    for m in str(s or "").lower().split():
        if m in PETITS_MOTS:
            mots.append(m)
        else:
            mots.append("-".join(p[:1].upper() + p[1:] for p in m.split("-")))
    return " ".join(mots)


def nom_ecole(nom: str, patronyme: str) -> str:
    nom = re.sub(r"\s+", " ", str(nom or "")).strip()
    m = ABREGE.match(nom)
    if m:
        # Le patronyme est sans accents (« DE LA SAIDA ») ; l'adresse qui suit le nom les a souvent
        # (« 20 rue de la Saïda ») : chaque mot retrouvé dans l'adresse reprend son orthographe.
        b = _outils()
        accents = {b.norm(w): w for w in re.findall(r"[^\W\d_]+", nom) if not w.isascii()}
        mots = [accents.get(b.norm(w), w) if accents.get(b.norm(w)) else w for w in joli(patronyme).split(" ")]
        mots = [w if w in PETITS_MOTS else w[:1].upper() + w[1:] for w in mots]
        nom = f"{BASE[m.group(1).upper()]} {' '.join(mots)}".strip()
    elif nom.isupper():
        nom = joli(nom)
    nom = re.sub(r"^ecole\b", "École", nom, flags=re.IGNORECASE)
    # « École Primaire Saint Erwan », « Ecole Elementaire » : type en minuscules, avec ses accents.
    nom = re.sub(r"^École (primaire|[ée]l[ée]mentaire|maternelle)\b",
                 lambda m: "École " + {"primaire": "primaire", "maternelle": "maternelle"}.get(m.group(1).lower(), "élémentaire"),
                 nom, flags=re.IGNORECASE)
    # « École élémentaire Publique Graveson » -> « École élémentaire publique Graveson ».
    nom = re.sub(r"^(École (?:primaire|élémentaire|maternelle)) (Publique|Privée|Privee)\b",
                 lambda m: f"{m.group(1)} {'publique' if m.group(2).lower() == 'publique' else 'privée'}", nom)
    return nom[:1].upper() + nom[1:]


# ---------------------------------------------------------------- lecture

def lire_annuaire(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    """Colonnes facultatives : la dernière version valide du cache peut n'en avoir que trois."""
    b = _outils()
    c_uai = b.pick(df, r"identifiant_de_l_etablissement|^uai$|numero_uai")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    col = lambda motif: b.pick(d, motif, required=False)
    c_contrat, c_mat, c_elem = col(r"^type_contrat_prive$|type_contrat"), col(r"^ecole_maternelle$"), col(r"^ecole_elementaire$")
    c_ep, c_cantine, c_circo = col(r"appartenance_education_prioritaire"), col(r"^restauration$"), col(r"nom_circonscription")
    vide = pd.Series("", index=d.index)
    txt = lambda c: d[c].fillna("").astype(str).str.strip() if c else vide
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "hors_contrat": txt(c_contrat).map(b.norm).str.startswith("hors_contrat"),
        "mat": b.num(txt(c_mat)) == 1,
        "elem": b.num(txt(c_elem)) == 1,
        "flags": (txt(c_mat) != "") & (txt(c_elem) != ""),
        "ep": txt(c_ep).str.upper().str.replace(" ", "", regex=False),
        "cantine": b.num(txt(c_cantine)) == 1 if c_cantine else False,
        # « Circonscription d'inspection du 1er degré de Paris 15C Convention » -> « Circonscription de Paris 15C Convention »
        "circo": txt(c_circo).str.replace(r"(?i)^circonscription d'inspection du (1er|premier) degr[ée] ", "Circonscription ", regex=True),
    }).drop_duplicates("uai")
    out.loc[~out["ep"].isin(["REP", "REP+"]), "ep"] = ""
    b.log(f"  {len(out)} écoles dans l'annuaire : {int(out['hors_contrat'].sum())} privées hors contrat, "
          f"{int((out['ep'] == 'REP').sum())} en REP, {int((out['ep'] == 'REP+').sum())} en REP+ ; "
          f"colonnes : contrat={c_contrat} maternelle={c_mat} élémentaire={c_elem} EP={c_ep} cantine={c_cantine} circo={c_circo}")
    return out


def lire_ips(df: pd.DataFrame, uais: set[str], academies: dict[str, str]) -> pd.DataFrame:
    """IPS par année, avec rang en France métropolitaine et dans l'académie (rang 1 = IPS le plus élevé),
    comme le rang du score des collèges et des lycées."""
    b = _outils()
    c_uai = b.pick(df, r"^uai$|numero_uai")
    c_an = b.pick(df, r"rentree|^annee")
    c_ips = b.pick(df, r"^ips$")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({"uai": d[c_uai].str.strip().str.upper(), "annee": d[c_an].str.strip(), "ips": b.num(d[c_ips])})
    out = out.dropna(subset=["ips"]).drop_duplicates(["uai", "annee"])
    out["academie"] = out["uai"].map(academies)
    out["rang"] = out.groupby("annee")["ips"].rank(ascending=False, method="min")
    out["nb"] = out.groupby("annee")["ips"].transform("count")
    out["rang_acad"] = out.groupby(["annee", "academie"])["ips"].rank(ascending=False, method="min")
    out["nb_acad"] = out.groupby(["annee", "academie"])["ips"].transform("count")
    b.log(f"  IPS : {len(out)} lignes, {out['uai'].nunique()} écoles, années {sorted(out['annee'].unique())}")
    return out


def lire_effectifs(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    """Dernière rentrée connue de chaque école : élèves et classes."""
    b = _outils()
    c_uai = b.pick(df, r"^numero_ecole$|^uai$|numero_uai")
    c_an = b.pick(df, r"rentree|^annee")
    c_el = b.pick(df, r"nombre_total_eleves|total_eleves")
    c_cl = b.pick(df, r"nombre_total_classes|total_classes", required=False)
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "rentree": d[c_an].astype(str).str.strip().str[:4],
        "eleves": b.num(d[c_el]),
        "classes": b.num(d[c_cl]) if c_cl else float("nan"),
    }).dropna(subset=["eleves"])
    out = out.sort_values("rentree").drop_duplicates("uai", keep="last")
    b.log(f"  effectifs : {len(out)} écoles, rentrées {out['rentree'].value_counts().sort_index().to_dict()}")
    return out


TAILLE = [("ecole", "école"), ("commune", "commune"), ("circo", "circonscription"), ("acad", "académie"), ("fr", "France")]


def lire_taille(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    """Dernière année de chaque école : élèves par classe en préélémentaire et en élémentaire."""
    b = _outils()
    c_uai = b.pick(df, r"^uai$|numero_uai")
    c_an = b.pick(df, r"^annee$|rentree")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({"uai": d[c_uai].str.strip().str.upper(), "annee": d[c_an].astype(str).str.strip().str[:4]})
    for niv in ("elem", "preel"):
        for cle, _ in TAILLE:
            c = b.pick(d, rf"^esurc_{cle}_{niv}$", required=False)
            out[f"{niv}_{cle}"] = b.num(d[c]) if c else float("nan")
    out = out.sort_values("annee").drop_duplicates("uai", keep="last")
    b.log(f"  taille des classes : {len(out)} écoles, années {out['annee'].value_counts().sort_index().to_dict()}")
    return out


# ---------------------------------------------------------------- export

def r(x, nd=0):
    return _outils().round_or_none(x, nd)


def couleurs(valeurs: list) -> dict | None:
    v = pd.Series([x for x in valeurs if x is not None], dtype=float)
    if not len(v):
        return None
    return {"stops": [round(float(v.quantile(q)), 2) for q in QUANTILES], "n": int(len(v))}


def construire(tous: pd.DataFrame, frames: dict, out_dir, problemes: list) -> dict:
    b = _outils()
    ec = tous[tous["nature"].str.match(NATURES)].copy()
    uais = set(ec["uai"])
    academies = dict(zip(ec["uai"], ec["academie"]))
    b.log(f"  {len(ec)} écoles géolocalisées ({(ec['secteur'] == 'public').sum()} publiques, "
          f"{(ec['secteur'] == 'privé').sum()} privées), {ec['dep'].nunique()} départements ; "
          f"natures : {ec['nature'].value_counts().to_dict()}")

    lus = {}
    for key, fn in (("annuaire_education", lire_annuaire), ("ips_ecoles", lire_ips),
                    ("effectifs_ecoles", lire_effectifs), ("taille_classes", lire_taille)):
        lus[key] = None
        if key not in frames:
            continue
        try:
            lus[key] = fn(frames[key], uais, academies) if key == "ips_ecoles" else fn(frames[key], uais)
        except b.ColonneIntrouvable as exc:
            b.log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : {exc}")
    ann, ips, eff, tai = lus["annuaire_education"], lus["ips_ecoles"], lus["effectifs_ecoles"], lus["taille_classes"]
    ann_by = ann.set_index("uai").to_dict("index") if ann is not None and len(ann) else {}
    ips_by = {k: g.sort_values("annee") for k, g in ips.groupby("uai")} if ips is not None and len(ips) else {}
    eff_by = eff.set_index("uai").to_dict("index") if eff is not None and len(eff) else {}
    tai_by = tai.set_index("uai").to_dict("index") if tai is not None and len(tai) else {}

    feats, fiches, recherche, communes = {}, {}, [], {}
    niveaux = {"maternelle": 0, "elementaire": 0, "primaire": 0}
    for e in ec.itertuples():
        a = ann_by.get(e.uai, {})
        if a.get("flags"):
            niveau = "primaire" if a["mat"] and a["elem"] else "maternelle" if a["mat"] else "elementaire"
        else:
            niveau = "maternelle" if "maternelle" in e.nature else "primaire" if "primaire" in b.norm(e.denomination) else "elementaire"
        niveaux[niveau] += 1
        p = {"uai": e.uai, "nom": nom_ecole(e.nom, e.patronyme), "niveau": niveau, "secteur": e.secteur,
             "commune": e.commune, "dep": e.dep}
        if e.secteur == "privé" and a.get("hors_contrat"):
            p["contrat"] = "hors"
        if a.get("ep"):
            p["ep"] = a["ep"]
        fiche = {"adresse": f"{e.adresse}, {e.cp} {e.commune}".strip(", ")}
        if a.get("circo"):
            fiche["circo"] = a["circo"]
        if a.get("cantine"):
            fiche["cantine"] = True
        hist = {}
        g = ips_by.get(e.uai)
        if g is not None:
            hist["ips"] = [{"annee": x.annee, "ips": r(x.ips, 1), "rang": r(x.rang), "nb": r(x.nb),
                            "rang_acad": r(x.rang_acad), "nb_acad": r(x.nb_acad)} for x in g.itertuples()]
            last = hist["ips"][-1]
            p.update({"ips": last["ips"], "rang": last["rang"], "nb": last["nb"]})
        f = eff_by.get(e.uai)
        if f:
            p["eleves"], p["rentree"] = r(f["eleves"]), f["rentree"]
            if r(f["classes"]):
                fiche["classes"] = r(f["classes"])
        t = tai_by.get(e.uai)
        if t:
            cl = {"annee": t["annee"]}
            for niv in ("elem", "preel"):
                vals = [r(t[f"{niv}_{cle}"], 1) for cle, _ in TAILLE]
                if vals[0] is not None:
                    cl[niv] = vals
            if len(cl) > 1:
                hist["classes"] = cl
                p["classe"] = (cl.get("elem") or cl.get("preel"))[0]
        if hist:
            fiche["hist"] = hist
        fiches.setdefault(e.dep, {})[e.uai] = fiche
        feats.setdefault(e.dep, []).append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e.lon, 5), round(e.lat, 5)]},
                                            "properties": b.sans_nan(p)})
        ic = communes.setdefault((e.commune, e.dep), len(communes))
        t = next((i for i in range(len(PREFIXES) - 1, 0, -1) if p["nom"].startswith(PREFIXES[i])), 0)
        recherche.append([e.uai, t, p["nom"][len(PREFIXES[t]):], ic, round(e.lon, 4), round(e.lat, 4)])

    # Rentrée des effectifs : écrite seulement quand ce n'est pas la plus récente (fichiers plus légers).
    tous_points = [f["properties"] for fs in feats.values() for f in fs]
    derniere = max((p["rentree"] for p in tous_points if "rentree" in p), default=None)
    for p in tous_points:
        if p.get("rentree") == derniere:
            del p["rentree"]

    compact = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    dossier = out_dir / "ecoles"
    dossier.mkdir(exist_ok=True)
    for f in dossier.glob("*.json"):
        f.unlink()
    for f in dossier.glob("*.geojson"):
        f.unlink()
    infos = ec.groupby("dep").agg(departement=("departement", "first"), academie=("academie", "first"),
                                  lon0=("lon", "min"), lat0=("lat", "min"), lon1=("lon", "max"), lat1=("lat", "max"))
    index = {}
    for dep, fs in feats.items():
        i = infos.loc[dep]
        (dossier / f"{dep}.geojson").write_text(compact({"type": "FeatureCollection", "departement": i.departement,
                                                         "academie": i.academie, "features": fs}), encoding="utf-8")
        index[dep] = {"bbox": [round(i.lon0, 4), round(i.lat0, 4), round(i.lon1, 4), round(i.lat1, 4)], "n": len(fs),
                      "departement": i.departement}
    (dossier / "index.json").write_text(compact(index), encoding="utf-8")
    liste_communes = [None] * len(communes)
    for (nom, dep), i in communes.items():
        liste_communes[i] = [nom, dep]
    (dossier / "recherche.json").write_text(compact({"prefixes": PREFIXES, "communes": liste_communes, "ecoles": recherche}), encoding="utf-8")
    fdos = out_dir / "fiches"
    fdos.mkdir(exist_ok=True)
    for f in fdos.glob("ecoles-*.json"):
        f.unlink()
    for dep, contenu in fiches.items():
        (fdos / f"ecoles-{dep}.json").write_text(compact(contenu), encoding="utf-8")
    taille = lambda motif, d=dossier: sum(f.stat().st_size for f in d.glob(motif)) / 1e6
    plus_gros = sorted(((f.stat().st_size, f.name) for f in dossier.glob("*.geojson")), reverse=True)[:3]
    b.log(f"  tailles : points {taille('*.geojson'):.2f} Mo en {len(feats)} fichiers (plus gros : "
          f"{', '.join(f'{n} {s / 1e3:.0f} ko' for s, n in plus_gros)}) ; recherche {taille('recherche.json'):.2f} Mo ; "
          f"fiches {taille('ecoles-*.json', fdos):.2f} Mo")

    couverture = {k: sum(1 for p in tous_points if k in p) for k in ("ips", "eleves", "classe", "ep", "contrat")}
    med = lambda df, cle: {an: r(g["ips"].median(), 1) for an, g in df.groupby(cle)} if df is not None and len(df) else {}
    meta = {
        "total": len(tous_points),
        "publics": int((ec["secteur"] == "public").sum()),
        "prives": int((ec["secteur"] == "privé").sum()),
        "hors_contrat": couverture["contrat"],
        "niveaux": niveaux,
        "couverture": couverture,
        "periodes": {"ips": sorted(ips["annee"].unique().tolist()) if ips is not None and len(ips) else [],
                     "effectifs": max(eff["rentree"]) if eff is not None and len(eff) else None,
                     "classes": max(tai["annee"]) if tai is not None and len(tai) else None},
        "couleurs": {k: c for k in ("ips", "classe") if (c := couleurs([p.get(k) for p in tous_points]))},
        "medianes": {"ips": med(ips, "annee")},
        "medianes_academies": {acad: {"ips": med(g, "annee")} for acad, g in ips.groupby("academie")} if ips is not None and len(ips) else {},
    }
    b.log(f"  {len(tous_points)} écoles écrites ; niveaux : {niveaux} ; couverture : {couverture}")
    b.log(f"  couleurs : {meta['couleurs']} ; médianes IPS : {meta['medianes']}")
    for uai in ("0750602X", "0753258J", "0921106C", "0755913V"):
        dep = next((d for d, fs in fiches.items() if uai in fs), None)
        if dep:
            pt = next(f["properties"] for f in feats[dep] if f["properties"]["uai"] == uai)
            b.log(f"   exemple {uai} : {json.dumps(pt, ensure_ascii=False)} ; fiche : {json.dumps(fiches[dep][uai], ensure_ascii=False)}")
    noms = pd.Series([p["nom"] for p in tous_points])
    b.log(f"   noms : {noms.sample(min(15, len(noms)), random_state=2).tolist()}")
    return meta
