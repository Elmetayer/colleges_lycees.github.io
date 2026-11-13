"""Données des collèges (France métropolitaine).

Appelé par build.py. Lit quatre jeux open data déjà téléchargés :
  - ivac   : indicateurs de valeur ajoutée des collèges (brevet)
  - ips    : indices de position sociale des collèges
  - eval6e : évaluations nationales de début de sixième
  - annuaire_education : type de contrat et date d'ouverture, pour expliquer l'absence de
    résultats au brevet (diagnostic du 13/11/2026 : privés hors contrat, collèges ouverts
    récemment, sites annexes, petits collèges absents du fichier ivac, qui ne contient aucun
    collège de moins de 20 candidats)
et écrit <out>/colleges.geojson (points légers, dernière valeur de chaque indicateur)
et <out>/fiches/colleges-<dep>.json (historiques, chargés à l'ouverture d'une fiche).
Renvoie les blocs de meta.json propres aux collèges (effectifs, périodes, médianes
nationales et par académie).
"""

from __future__ import annotations

import json
import re

import pandas as pd


def _outils():
    # Import tardif : build.py importe ce module.
    import build
    return build


# ---------------------------------------------------------------- lecture des indicateurs

def colleges_de(etabs: pd.DataFrame) -> pd.DataFrame:
    b = _outils()
    out = etabs[etabs["nature"].str.contains("college")]
    b.log(f"  {len(out)} collèges géolocalisés en France métropolitaine "
        f"({(out['secteur'] == 'public').sum()} publics, {(out['secteur'] == 'privé').sum()} privés), "
        f"{out['dep'].nunique()} départements, {out['academie'].nunique()} académies")
    b.log(f"  collèges par académie : {out['academie'].value_counts().to_dict()}")
    return out


def load_ivac(df: pd.DataFrame, uais: set[str], academies: dict[str, str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$|numero_uai|^code_uai")
    c_session = b.pick(df, r"^session$|^annee|session")
    c_reussite = b.pick(df, r"taux_de_reussite.*_g$|taux_reussite.*_g$", exclude=r"attendu|^va|valeur|ecart")
    c_cand = b.pick(df, r"^nb_candidats.*_g$|^nombre_de_candidats.*_g$|candidats.*_g$")
    c_mentions = b.pick(df, r"^nb_mentions_global.*_g$|mentions_global.*_g$|^nb_mentions.*_g$", exclude=r"_tb|_b_|_ab|tres_bien|assez|attendu")
    c_tb = b.pick(df, r"mentions_tb.*_g$|mentions_tres_bien.*_g$", exclude=r"attendu")
    c_va = b.pick(df, r"(^va_|valeur_ajoutee).*reussite.*_g$", required=False)
    c_note = b.pick(df, r"note.*ecrit.*_g$", exclude=r"attendu|^va|valeur", required=False)
    c_va_note = b.pick(df, r"(^va_|valeur_ajoutee).*note.*_g$", required=False)
    b.log(f"  colonnes retenues : session={c_session} réussite={c_reussite} candidats={c_cand} "
        f"mentions={c_mentions} TB={c_tb} VA réussite={c_va} note écrit={c_note} VA note={c_va_note}")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    cand = b.num(d[c_cand])
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "session": d[c_session].str.strip(),
        "candidats": cand,
        "taux_reussite": b.num(d[c_reussite]),
        "taux_mentions": b.num(d[c_mentions]) / cand * 100,
        "taux_tb": b.num(d[c_tb]) / cand * 100,
        "va_reussite": b.num(d[c_va]) if c_va else float("nan"),
        "note_ecrit": b.num(d[c_note]) if c_note else float("nan"),
        "va_note": b.num(d[c_va_note]) if c_va_note else float("nan"),
    })
    out = out.dropna(subset=["taux_reussite"]).drop_duplicates(["uai", "session"])
    # Score optionnel : moyenne des trois taux bruts. Rang national (France métropolitaine)
    # et rang dans l'académie, pour la même session.
    out["score"] = out[["taux_reussite", "taux_mentions", "taux_tb"]].mean(axis=1, skipna=False)
    out["academie"] = out["uai"].map(academies)
    out["rang"] = out.groupby("session")["score"].rank(ascending=False, method="min")
    out["nb_classes"] = out.groupby("session")["score"].transform("count")
    out["rang_acad"] = out.groupby(["session", "academie"])["score"].rank(ascending=False, method="min")
    out["nb_acad"] = out.groupby(["session", "academie"])["score"].transform("count")
    b.log(f"  {len(out)} lignes brevet, sessions {sorted(out['session'].unique())}")
    return out


def load_ips(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$|numero_uai|^code_uai")
    c_annee = b.pick(df, r"rentree|^annee")
    c_ips = b.pick(df, r"^ips$|^ips_|indice_de_position_sociale|indice_position_sociale", exclude=r"ecart|academ|depart|national")
    c_et = b.pick(df, r"ecart_type", exclude=r"academ|depart|national", required=False)
    b.log(f"  colonnes retenues : année={c_annee} IPS={c_ips} écart-type={c_et}")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "annee": d[c_annee].str.strip(),
        "ips": b.num(d[c_ips]),
        "ips_et": b.num(d[c_et]) if c_et else float("nan"),
    }).dropna(subset=["ips"]).drop_duplicates(["uai", "annee"])
    b.log(f"  {len(out)} lignes IPS, années {sorted(out['annee'].unique())}")
    return out


def load_eval6e(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$|numero_uai|^code_uai")
    c_annee = b.pick(df, r"rentree|^annee|session")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    c_matiere = b.pick(df, r"matiere|discipline|^domaine", required=False)
    for c in (b.pick(df, r"caracteristique", required=False), c_matiere, b.pick(df, r"libelle_secteur", required=False)):
        if c:
            b.log(f"  valeurs de {c} : {d[c].value_counts().head(15).to_dict()}")
    c_carac = b.pick(df, r"caracteristique", required=False)
    if c_carac:
        d = d[d[c_carac].fillna("").map(b.norm).isin(["ensemble", "total", "tous"])]
    if c_matiere:
        c_score = b.pick(df, r"score_moyen|moyenne", exclude=r"ecart|academ|depart|national|france")
        b.log(f"  format long : matière={c_matiere} score={c_score}")
        d["m"] = d[c_matiere].map(b.norm).map(lambda s: "fr" if s.startswith("fr") else ("ma" if s.startswith("math") else None))
        d = d.dropna(subset=["m"])
        d["v"] = b.num(d[c_score])
        wide = d.pivot_table(index=[c_uai, c_annee], columns="m", values="v", aggfunc="mean").reset_index()
        wide.columns.name = None
        wide = wide.rename(columns={c_uai: "uai", c_annee: "annee"})
    else:
        c_fr = b.pick(df, r"(score|moyenne).*fran|fran.*(score|moyenne)", exclude=r"ecart|academ|depart|national|france")
        c_ma = b.pick(df, r"(score|moyenne).*math|math.*(score|moyenne)", exclude=r"ecart|academ|depart|national|france")
        b.log(f"  format large : français={c_fr} maths={c_ma}")
        wide = pd.DataFrame({"uai": d[c_uai], "annee": d[c_annee], "fr": b.num(d[c_fr]), "ma": b.num(d[c_ma])})
    wide["uai"] = wide["uai"].str.strip().str.upper()
    wide["annee"] = wide["annee"].str.strip()
    for c in ("fr", "ma"):
        if c not in wide:
            wide[c] = float("nan")
    wide = wide.dropna(subset=["fr", "ma"], how="all").drop_duplicates(["uai", "annee"])
    b.log(f"  {len(wide)} lignes évaluations 6e, années {sorted(wide['annee'].unique())}")
    return wide[["uai", "annee", "fr", "ma"]]


def load_annuaire(df: pd.DataFrame, uais: set[str], quoi: str = "collèges") -> pd.DataFrame:
    """UAI, privé hors contrat (booléen) et année d'ouverture."""
    b = _outils()
    c_uai = b.pick(df, r"identifiant_de_l_etablissement|^uai$|numero_uai")
    c_contrat = b.pick(df, r"^type_contrat_prive$|type_contrat")
    c_ouv = b.pick(df, r"^date_ouverture$|ouverture")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "hors_contrat": d[c_contrat].fillna("").map(b.norm).str.startswith("hors_contrat"),
        "ouverture": pd.to_datetime(d[c_ouv], errors="coerce").dt.year,
    }).drop_duplicates("uai")
    b.log(f"  {len(out)} {quoi} dans l'annuaire, dont {int(out['hors_contrat'].sum())} privés hors contrat")
    return out


# Absence de résultats au brevet : raison affichée sur la fiche (voir app.js).
SITE_ANNEXE = r"\bsite\b|annexe|unité pédagogique|antenne"


def raison_sans_brevet(nom: str, hors_contrat: bool, ouverture, derniere_session: int | None) -> str:
    if hors_contrat:
        return "hors_contrat"
    if re.search(SITE_ANNEXE, nom or "", re.IGNORECASE):
        return "annexe"
    # Ouvert dans les 4 ans précédant la dernière session : pas encore de classe de 3e complète.
    if ouverture == ouverture and ouverture is not None and derniere_session and ouverture >= derniere_session - 4:
        return "recent"
    return "non_publie"


# ---------------------------------------------------------------- export

def build_features(etabs, ivac, ips, ev, ann=None) -> tuple[list[dict], dict[str, dict]]:
    """Renvoie les points (dernière valeur de chaque indicateur) et les historiques par département."""
    b = _outils()
    by = lambda df: {k: g for k, g in df.groupby("uai")} if df is not None and len(df) else {}
    ivac_by, ips_by, ev_by = by(ivac), by(ips), by(ev)
    ann_by = ann.set_index("uai").to_dict("index") if ann is not None and len(ann) else {}
    sessions = [int(s) for s in ivac["session"].unique() if str(s).isdigit()] if ivac is not None and len(ivac) else []
    derniere_session = max(sessions) if sessions else None
    feats, fiches = [], {}
    for e in etabs.itertuples():
        p = {"uai": e.uai, "nom": e.nom, "commune": e.commune, "dep": e.dep,
             "departement": e.departement, "academie": e.academie, "secteur": e.secteur}
        hist = {}
        g = ivac_by.get(e.uai)
        if g is not None:
            g = g.sort_values("session")
            hist["brevet"] = [{
                "session": r.session, "candidats": b.round_or_none(r.candidats, 0),
                "taux_reussite": b.round_or_none(r.taux_reussite), "taux_mentions": b.round_or_none(r.taux_mentions),
                "taux_tb": b.round_or_none(r.taux_tb), "va_reussite": b.round_or_none(r.va_reussite),
                "note_ecrit": b.round_or_none(r.note_ecrit, 2), "va_note": b.round_or_none(r.va_note, 2),
                "score": b.round_or_none(r.score), "rang": b.round_or_none(r.rang, 0), "nb": b.round_or_none(r.nb_classes, 0),
                "rang_acad": b.round_or_none(r.rang_acad, 0), "nb_acad": b.round_or_none(r.nb_acad, 0),
            } for r in g.itertuples()]
            last = hist["brevet"][-1]
            p["session_brevet"] = last["session"]
            for k in ("taux_reussite", "taux_mentions", "taux_tb", "va_reussite", "note_ecrit", "va_note", "score", "rang", "nb"):
                p[k] = last[k]
        g = ips_by.get(e.uai)
        if g is not None:
            g = g.sort_values("annee")
            hist["ips"] = [{"annee": r.annee, "ips": b.round_or_none(r.ips), "ecart_type": b.round_or_none(r.ips_et)} for r in g.itertuples()]
            p["ips"] = hist["ips"][-1]["ips"]
            p["annee_ips"] = hist["ips"][-1]["annee"]
        g = ev_by.get(e.uai)
        if g is not None:
            g = g.sort_values("annee")
            hist["eval6e"] = [{"annee": r.annee, "fr": b.round_or_none(r.fr), "ma": b.round_or_none(r.ma)} for r in g.itertuples()][-5:]
            p["eval_fr"] = hist["eval6e"][-1]["fr"]
            p["eval_ma"] = hist["eval6e"][-1]["ma"]
            p["annee_eval"] = hist["eval6e"][-1]["annee"]
        a = ann_by.get(e.uai)
        if a and a["hors_contrat"] and e.secteur == "privé":
            p["contrat"] = "hors"
        if "taux_reussite" not in p and ann_by:
            raison = raison_sans_brevet(e.nom, bool(p.get("contrat")), a["ouverture"] if a else None, derniere_session)
            p["sans_brevet"] = raison
            if raison == "recent":
                p["ouverture"] = int(a["ouverture"])
        if hist:
            fiches.setdefault(e.dep, {})[e.uai] = {
                "adresse": f"{e.adresse}, {e.cp} {e.commune}".strip(", "),
                "hist": {k: [{c: v for c, v in r.items() if v is not None} for r in rows] for k, rows in hist.items()},
            }
        p = b.sans_nan(p)  # MapLibre : absence = donnée manquante
        # 5 décimales (environ 1 m) suffisent et allègent le fichier national.
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e.lon, 5), round(e.lat, 5)]}, "properties": p})
    return feats, fiches


# ---------------------------------------------------------------- construction

def construire(tous: pd.DataFrame, frames: dict, out_dir, problemes: list) -> dict:
    b = _outils()
    etabs = colleges_de(tous)
    uais = set(etabs["uai"])
    academies = dict(zip(etabs["uai"], etabs["academie"]))
    results = {}
    for key, fn in (("ivac", load_ivac), ("ips", load_ips), ("eval6e", load_eval6e), ("annuaire_education", load_annuaire)):
        if key not in frames:
            results[key] = None
            continue
        b.log(f"-- {key}")
        try:
            results[key] = fn(frames[key], uais, academies) if key == "ivac" else fn(frames[key], uais)
        except b.ColonneIntrouvable as exc:
            b.log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : {exc}")
            results[key] = None

    feats, fiches = build_features(etabs, results["ivac"], results["ips"], results["eval6e"], results["annuaire_education"])
    sans_brevet = pd.Series([f["properties"]["sans_brevet"] for f in feats if "sans_brevet" in f["properties"]]).value_counts().to_dict()
    hors_contrat = sum(1 for f in feats if f["properties"].get("contrat") == "hors")
    b.log(f"  collèges sans brevet, par raison : {sans_brevet} ; privés hors contrat : {hors_contrat}")
    geo = {"type": "FeatureCollection", "features": feats}
    # allow_nan=False : un NaN oublié fait échouer le build (l'ancien site reste en ligne) au lieu de publier un fichier illisible.
    compact = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    (out_dir / "colleges.geojson").write_text(compact(geo), encoding="utf-8")
    dossier_fiches = out_dir / "fiches"
    dossier_fiches.mkdir(exist_ok=True)
    for f in dossier_fiches.glob("colleges-*.json"):
        f.unlink()
    for dep, contenu in fiches.items():
        (dossier_fiches / f"colleges-{dep}.json").write_text(compact(contenu), encoding="utf-8")
    tailles = sorted(((f.stat().st_size, f.name) for f in dossier_fiches.glob("colleges-*.json")), reverse=True)
    b.log(f"\n== tailles : colleges.geojson {(out_dir / 'colleges.geojson').stat().st_size / 1e6:.2f} Mo ; "
          f"{len(tailles)} fichiers de fiches, total {sum(t for t, _ in tailles) / 1e6:.2f} Mo, "
          f"plus gros : {', '.join(f'{n} {t / 1e3:.0f} ko' for t, n in tailles[:3])}")

    def medianes(filtre=None):
        """Médiane de chaque indicateur par année, sur les collèges retenus par `filtre` (tous par défaut)."""
        m = {"brevet": {}, "ips": {}, "eval6e": {}}
        garder = lambda df: df if df is None or filtre is None else df[df["uai"].isin(filtre)]
        iv, ip, ev = garder(results["ivac"]), garder(results["ips"]), garder(results["eval6e"])
        if iv is not None and len(iv):
            for sess, g in iv.groupby("session"):
                m["brevet"][sess] = {
                    "taux_reussite": b.round_or_none(g["taux_reussite"].median()),
                    "taux_mentions": b.round_or_none(g["taux_mentions"].median()),
                    "va_reussite": b.round_or_none(g["va_reussite"].median()),
                    "note_ecrit": b.round_or_none(g["note_ecrit"].median(), 2),
                    "va_note": b.round_or_none(g["va_note"].median(), 2),
                    "score": b.round_or_none(g["score"].median()),
                }
        if ip is not None and len(ip):
            for an, g in ip.groupby("annee"):
                m["ips"][an] = b.round_or_none(g["ips"].median())
        if ev is not None and len(ev):
            for an, g in ev.groupby("annee"):
                m["eval6e"][an] = {"fr": b.round_or_none(g["fr"].median()), "ma": b.round_or_none(g["ma"].median())}
        return m

    def periodes(df, col):
        return sorted(df[col].unique().tolist()) if df is not None and len(df) else []

    # Blocs de premier niveau de meta.json (noms inchangés : le site les lit tels quels).
    meta = {
        "colleges": {"total": len(feats), "publics": int((etabs["secteur"] == "public").sum()), "prives": int((etabs["secteur"] == "privé").sum()),
                     "hors_contrat": hors_contrat, "sans_brevet": {k: int(v) for k, v in sans_brevet.items()}},
        "periodes": {"brevet": periodes(results["ivac"], "session"), "ips": periodes(results["ips"], "annee"), "eval6e": periodes(results["eval6e"], "annee")},
        # Médianes nationales (France métropolitaine) et par académie (fiches des collèges).
        "medianes": medianes(),
        "medianes_academies": {a: medianes(set(g["uai"])) for a, g in etabs.groupby("academie")},
    }

    b.log(f"  {len(feats)} collèges écrits")
    couverture = {k: sum(1 for f in feats if k in f["properties"]) for k in ("taux_reussite", "va_reussite", "note_ecrit", "ips", "eval_fr")}
    b.log(f"   couverture des indicateurs : {couverture}")
    for k in ("taux_reussite", "taux_mentions", "va_reussite", "note_ecrit", "ips", "eval_fr", "eval_ma", "score"):
        v = pd.Series([f["properties"][k] for f in feats if k in f["properties"]], dtype=float)
        if len(v):
            b.log(f"   {k:14s} n={len(v):5d} min={v.min():.1f} médiane={v.median():.1f} max={v.max():.1f}")
    exemple = next((f["properties"] for f in feats if "ips" in f["properties"] and "taux_reussite" in f["properties"]), None)
    if exemple:
        b.log(f"   exemple : {json.dumps(exemple, ensure_ascii=False)}")
    sans = {k: sum(1 for f in feats if k not in f["properties"]) for k in ("taux_reussite", "ips")}
    par_dep = pd.Series([f["properties"]["dep"] for f in feats if "taux_reussite" not in f["properties"]]).value_counts().head(8).to_dict()
    b.log(f"   collèges sans indicateur : {sans} ; départements les plus touchés (brevet) : {par_dep}")
    return meta
