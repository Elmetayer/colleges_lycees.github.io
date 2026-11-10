"""Données des lycées (académies de Paris et de Versailles).

Appelé par build.py. Lit trois jeux open data déjà téléchargés :
  - ival_gt    : indicateurs de valeur ajoutée des lycées généraux et technologiques
  - ival_pro   : indicateurs de valeur ajoutée des lycées professionnels
  - ips_lycees : indices de position sociale des lycées
et écrit <out>/lycees.geojson. Renvoie le bloc "lycees" de meta.json
(effectifs, périodes, médianes par voie).

Un lycée polyvalent a le même UAI dans les deux jeux de valeur ajoutée :
ses résultats de voie générale et technologique (GT) et de voie professionnelle
(pro) sont rangés côte à côte.
"""

from __future__ import annotations

import json

import pandas as pd

# Séries du bac général et technologique, dans l'ordre d'affichage (L, ES, S : avant 2021, ignorées).
SERIES_GT = [("gnle", "Générale"), ("sti2d", "STI2D"), ("stmg", "STMG"), ("st2s", "ST2S"),
             ("stl", "STL"), ("std2a", "STD2A"), ("sthr", "STHR"), ("s2tmd", "S2TMD")]

# Domaines du bac professionnel : deux grands groupes, chacun avec ses spécialités.
DOMAINES_PRO = [
    ("production", "Production", [
        ("specialites_pluri_technologiques_de_la_production", "Pluri-technologiques de la production"),
        ("transformations", "Transformations"),
        ("genie_civil_construction_bois", "Génie civil, construction, bois"),
        ("materiaux_souples", "Matériaux souples"),
        ("mecanique_electricite_electronique", "Mécanique, électricité, électronique"),
    ]),
    ("services", "Services", [
        ("specialites_plurivalentes_des_services", "Plurivalentes des services"),
        ("echanges_et_gestion", "Échanges et gestion"),
        ("communication_et_information", "Communication et information"),
        ("services_aux_personnes", "Services aux personnes"),
        ("services_a_la_collectivite", "Services à la collectivité"),
    ]),
]


HISTORIQUE = 8


def _outils():
    # Import tardif : build.py importe ce module.
    import build
    return build


def type_lycee(nature: str) -> str | None:
    """Nature normalisée de l'annuaire -> libellé, ou None si ce n'est pas un lycée."""
    if not nature.startswith("lycee"):
        return None
    if "agricole" in nature:
        return "Lycée agricole"
    if "polyvalent" in nature:
        return "Lycée polyvalent"
    if "professionnel" in nature:
        return "Lycée professionnel"
    if "general" in nature or "technolog" in nature:
        return "Lycée général et technologique"
    return "Lycée"


def colonne(df: pd.DataFrame, *noms: str) -> str | None:
    """Première colonne existante parmi des noms normalisés exacts."""
    for n in noms:
        if n in df.columns:
            return n
    return None


def valeur(df, ligne, *noms):
    c = colonne(df, *noms)
    return ligne.get(c) if c else None


# ---------------------------------------------------------------- lecture

def lire_gt(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$")
    c_an = b.pick(df, r"^annee$|^session$")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    n = lambda *noms: b.num(d[colonne(d, *noms)]) if colonne(d, *noms) else pd.Series(float("nan"), index=d.index)
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "session": d[c_an].str.strip().str[:4],
        "presents": n("presents_toutes_series"),
        "reussite": n("taux_de_reussite_toutes_series"),
        "mentions": n("taux_de_mentions_toutes_series"),
        "acces": n("taux_d_acces_2nde_bac"),
        "va_reussite": n("valeur_ajoutee_du_taux_de_reussite_toutes_series"),
        "va_mentions": n("valeur_ajoutee_du_taux_de_mentions_toutes_series"),
        "va_acces": n("valeur_ajoutee_du_taux_d_acces_2nde_bac"),
        "eff_2": n("effectif_de_seconde"),
        "eff_1": n("effectif_de_premiere"),
        "eff_t": n("effectif_de_terminale"),
    })
    # Voie générale seule : base du score agrégé.
    tb = n("nombre_de_mentions_tb_avec_felicitations_g").fillna(0) + n("nombre_de_mentions_tb_sans_felicitations_g").fillna(0)
    pg = n("presents_gnle")
    out["g_presents"] = pg
    out["g_reussite"] = n("taux_de_reussite_gnle")
    out["g_mentions"] = n("taux_de_mentions_gnle")
    out["g_tb"] = (tb / pg * 100).where(pg > 0)
    out["score"] = out[["g_reussite", "g_mentions", "g_tb"]].mean(axis=1, skipna=False)
    out["rang"] = out.groupby("session")["score"].rank(ascending=False, method="min")
    out["nb_classes"] = out.groupby("session")["score"].transform("count")
    # Détail par série (servira pour la dernière session).
    for code, _ in SERIES_GT:
        out[f"s_{code}_p"] = n(f"presents_{code}")
        out[f"s_{code}_r"] = n(f"taux_de_reussite_{code}")
        out[f"s_{code}_m"] = n(f"taux_de_mentions_{code}")
        out[f"s_{code}_va"] = n(f"valeur_ajoutee_du_taux_de_reussite_{code}")
    out = out.dropna(subset=["reussite"]).drop_duplicates(["uai", "session"])
    b.log(f"  voie GT : {len(out)} lignes, {out['uai'].nunique()} lycées, sessions {sorted(out['session'].unique())}")
    b.log(f"  score voie générale calculable : {out['score'].notna().sum()} lignes")
    return out


def lire_pro(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$")
    c_an = b.pick(df, r"^annee$|^session$")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    n = lambda *noms: b.num(d[colonne(d, *noms)]) if colonne(d, *noms) else pd.Series(float("nan"), index=d.index)
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "session": d[c_an].str.strip().str[:4],
        "presents": n("presents_toutes_series"),
        "reussite": n("taux_de_reussite_toutes_series"),
        "mentions": n("taux_de_mentions_toutes_series"),
        "acces": n("taux_d_acces_2nde_bac"),
        "va_reussite": n("valeur_ajoutee_du_taux_de_reussite_toutes_series"),
        "va_mentions": n("valeur_ajoutee_du_taux_de_mentions_toutes_series"),
        "va_acces": n("valeur_ajoutee_du_taux_d_acces_2nde_bac"),
        "eff_2": n("effectif_de_seconde"),
        "eff_1": n("effectif_de_premiere"),
        "eff_t": n("effectif_de_terminale"),
    })
    for code, _, sous in DOMAINES_PRO:
        for c, _ in [(code, None)] + sous:
            out[f"d_{c}_p"] = n(f"presents_{c}")
            out[f"d_{c}_r"] = n(f"taux_de_reussite_{c}")
    out = out.dropna(subset=["reussite"]).drop_duplicates(["uai", "session"])
    b.log(f"  voie pro : {len(out)} lignes, {out['uai'].nunique()} lycées, sessions {sorted(out['session'].unique())}")
    return out


def lire_ips(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    b = _outils()
    c_uai = b.pick(df, r"^uai$")
    c_an = b.pick(df, r"rentree|^annee")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    n = lambda *noms: b.num(d[colonne(d, *noms)]) if colonne(d, *noms) else pd.Series(float("nan"), index=d.index)
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "annee": d[c_an].str.strip(),
        "gt": n("ips_voie_gt"),
        "pro": n("ips_voie_pro"),
        "postbac": n("ips_post_bac"),
        "etab": n("ips_de_l_etablissement", "ips_ensemble_gt_pro"),
        "et_gt": n("ecart_type_voie_gt"),
        "et_pro": n("ecart_type_voie_pro"),
    })
    out["etab"] = out["etab"].fillna(out["gt"]).fillna(out["pro"])
    out = out.dropna(subset=["etab"]).drop_duplicates(["uai", "annee"])
    b.log(f"  IPS : {len(out)} lignes, {out['uai'].nunique()} lycées, années {sorted(out['annee'].unique())}")
    return out


# ---------------------------------------------------------------- export

def r(x, nd=0):
    return _outils().round_or_none(x, nd)


def ligne_voie(row) -> dict:
    eff = [r(row.eff_2), r(row.eff_1), r(row.eff_t)]
    d = {"session": row.session, "presents": r(row.presents), "reussite": r(row.reussite),
         "mentions": r(row.mentions), "acces": r(row.acces), "va_reussite": r(row.va_reussite),
         "va_mentions": r(row.va_mentions), "va_acces": r(row.va_acces),
         "effectifs": eff if any(v is not None for v in eff) else None}
    return {k: v for k, v in d.items() if v is not None}


def series_gt(row) -> list[dict]:
    out = []
    for code, nom in SERIES_GT:
        p = r(getattr(row, f"s_{code}_p"))
        if p:
            out.append({"nom": nom, "presents": p, "reussite": r(getattr(row, f"s_{code}_r")),
                        "mentions": r(getattr(row, f"s_{code}_m")), "va": r(getattr(row, f"s_{code}_va"))})
    return out


def domaines_pro(row) -> list[dict]:
    out = []
    for code, nom, sous in DOMAINES_PRO:
        p = r(getattr(row, f"d_{code}_p"))
        if not p:
            continue
        details = []
        for c, n in sous:
            sp = r(getattr(row, f"d_{c}_p"))
            if sp:
                details.append({"nom": n, "presents": sp, "reussite": r(getattr(row, f"d_{c}_r"))})
        out.append({"nom": nom, "presents": p, "reussite": r(getattr(row, f"d_{code}_r")), "details": details})
    return out


def construire(tous: pd.DataFrame, frames: dict, out_dir, problemes: list, departements: dict, academies: dict) -> dict:
    b = _outils()
    lyc = tous.copy()
    lyc["type"] = lyc["nature"].map(type_lycee)
    lyc = lyc.dropna(subset=["type"])
    b.log(f"  {len(lyc)} lycées géolocalisés ({(lyc['secteur'] == 'public').sum()} publics, "
          f"{(lyc['secteur'] == 'privé').sum()} privés) ; types : {lyc['type'].value_counts().to_dict()}")
    uais = set(lyc["uai"])

    lus = {}
    for key, fn in (("ival_gt", lire_gt), ("ival_pro", lire_pro), ("ips_lycees", lire_ips)):
        if key not in frames:
            lus[key] = None
            continue
        try:
            lus[key] = fn(frames[key], uais)
        except b.ColonneIntrouvable as exc:
            b.log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : {exc}")
            lus[key] = None
    gt, pro, ips = lus["ival_gt"], lus["ival_pro"], lus["ips_lycees"]
    # Historique limité aux HISTORIQUE dernières sessions (les plus anciennes alourdissent la fiche sans l'éclairer).
    by = lambda df: {k: g.sort_values(df.columns[1]).tail(HISTORIQUE) for k, g in df.groupby("uai")} if df is not None and len(df) else {}
    gt_by, pro_by, ips_by = by(gt), by(pro), by(ips)

    feats = []
    for e in lyc.itertuples():
        p = {"uai": e.uai, "nom": e.nom, "type": e.type, "commune": e.commune, "dep": e.dep,
             "departement": departements[e.dep], "academie": academies[e.dep], "secteur": e.secteur,
             "adresse": f"{e.adresse}, {e.cp} {e.commune}".strip(", ")}
        hist = {}
        g = gt_by.get(e.uai)
        if g is not None:
            hist["gt"] = [ligne_voie(x) for x in g.itertuples()]
            hist["series_gt"] = series_gt(list(g.itertuples())[-1])
            last = hist["gt"][-1]
            p["session_gt"] = last["session"]
            for k in ("presents", "reussite", "mentions", "acces", "va_reussite", "va_mentions", "va_acces"):
                p[f"gt_{k}"] = last.get(k)
            if last.get("effectifs"):
                p["eff_gt"] = sum(v or 0 for v in last["effectifs"])
            sc = [{"session": x.session, "score": r(x.score, 1), "rang": r(x.rang), "nb": r(x.nb_classes),
                   "reussite": r(x.g_reussite), "mentions": r(x.g_mentions), "tb": r(x.g_tb, 1)}
                  for x in g.itertuples() if pd.notna(x.score)]
            if sc:
                hist["score"] = sc
                p["score"], p["rang"], p["nb"], p["session_score"] = sc[-1]["score"], sc[-1]["rang"], sc[-1]["nb"], sc[-1]["session"]
        g = pro_by.get(e.uai)
        if g is not None:
            hist["pro"] = [ligne_voie(x) for x in g.itertuples()]
            hist["domaines_pro"] = domaines_pro(list(g.itertuples())[-1])
            last = hist["pro"][-1]
            p["session_pro"] = last["session"]
            for k in ("presents", "reussite", "mentions", "acces", "va_reussite", "va_mentions", "va_acces"):
                p[f"pro_{k}"] = last.get(k)
            if last.get("effectifs"):
                p["eff_pro"] = sum(v or 0 for v in last["effectifs"])
        g = ips_by.get(e.uai)
        if g is not None:
            hist["ips"] = [{k: v for k, v in {"annee": x.annee, "gt": r(x.gt, 1), "pro": r(x.pro, 1), "etab": r(x.etab, 1),
                            "postbac": r(x.postbac, 1), "et_gt": r(x.et_gt, 1), "et_pro": r(x.et_pro, 1)}.items() if v is not None}
                           for x in g.itertuples()]
            last = hist["ips"][-1]
            p["annee_ips"] = last["annee"]
            p["ips"] = last.get("etab")
            p["ips_gt"] = last.get("gt")
            p["ips_pro"] = last.get("pro")
        p["hist"] = json.dumps(hist, ensure_ascii=False, separators=(",", ":"))
        p = {k: v for k, v in p.items() if v is not None}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e.lon, 6), round(e.lat, 6)]}, "properties": p})

    (out_dir / "lycees.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Médianes par voie et par année, sur les lycées des deux académies.
    def med(df, cols, cle):
        m = {}
        if df is None or not len(df):
            return m
        for an, g in df.groupby(cle):
            m[an] = {c: r(g[c].median(), 1) for c in cols}
        return m

    recentes = lambda df, c: df[df[c].isin(sorted(df[c].unique())[-HISTORIQUE:])] if df is not None and len(df) else df
    gt, pro = recentes(gt, "session"), recentes(pro, "session")
    voie = ["reussite", "mentions", "acces", "va_reussite", "va_mentions", "va_acces"]
    medianes = {"gt": med(gt, voie + ["score"], "session"), "pro": med(pro, voie, "session"),
                "ips": med(ips, ["gt", "pro", "etab"], "annee")}
    periodes = lambda df, c: sorted(df[c].unique().tolist()) if df is not None and len(df) else []
    meta = {
        "total": len(feats),
        "publics": int((lyc["secteur"] == "public").sum()),
        "prives": int((lyc["secteur"] == "privé").sum()),
        "types": {k: int(v) for k, v in lyc["type"].value_counts().items()},
        "periodes": {"gt": periodes(gt, "session"), "pro": periodes(pro, "session"), "ips": periodes(ips, "annee")},
        "medianes": medianes,
    }

    couverture = {k: sum(1 for f in feats if k in f["properties"]) for k in ("gt_reussite", "pro_reussite", "ips", "score")}
    b.log(f"  {len(feats)} lycées écrits ; couverture : {couverture}")
    for k in ("gt_reussite", "gt_acces", "pro_reussite", "ips", "ips_gt", "ips_pro", "score"):
        v = pd.Series([f["properties"][k] for f in feats if k in f["properties"]], dtype=float)
        if len(v):
            b.log(f"   {k:12s} n={len(v):4d} min={v.min():.1f} médiane={v.median():.1f} max={v.max():.1f}")
    ex = next((f["properties"] for f in feats if f["properties"]["uai"] == "0782549X"), None)
    if ex:
        b.log(f"   exemple Louis Bascan : {json.dumps({k: v for k, v in ex.items() if k != 'hist'}, ensure_ascii=False)}")
    return meta
