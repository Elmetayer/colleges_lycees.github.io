"""Prépare les données de la carte scolaire (académies de Paris et de Versailles).

Télécharge les jeux open data de l'Éducation nationale, garde les collèges des
cinq départements concernés, calcule les indicateurs et écrit :
  - <out>/colleges.geojson : un point par collège avec ses indicateurs
  - <out>/meta.json        : date de génération, sessions, sources

Usage : python pipeline/build.py --out site/data
        python pipeline/build.py --out site/data --local-dir chemin/vers/csv  (tests hors ligne)
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DEPARTEMENTS = {"75": "Paris", "78": "Yvelines", "91": "Essonne", "92": "Hauts-de-Seine", "95": "Val-d'Oise"}
ACADEMIE_PAR_DEP = {"75": "Paris", "78": "Versailles", "91": "Versailles", "92": "Versailles", "95": "Versailles"}

EXPLORE = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
DATAGOUV = "https://www.data.gouv.fr/api/1/datasets"

# Jeux de données. "explore_id" est l'identifiant sur data.education.gouv.fr ;
# "datagouv" sert à le retrouver automatiquement s'il change.
SOURCES = {
    "etablissements": {
        "titre": "Adresse et géolocalisation des établissements d'enseignement du premier et second degrés",
        "explore_id": "fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre",
        "datagouv": None,
        "obligatoire": True,
    },
    "ivac": {
        "titre": "Indicateurs de valeur ajoutée des collèges",
        "explore_id": "fr-en-indicateurs-valeur-ajoutee-colleges",
        "datagouv": "indicateurs-de-valeur-ajoutee-des-colleges",
        "obligatoire": False,
    },
    "ips": {
        "titre": "Indices de position sociale des collèges (à partir de 2023)",
        "explore_id": None,
        "datagouv": "ips-colleges-a-partir-de-2023",
        "obligatoire": False,
    },
    "eval6e": {
        "titre": "Résultats consolidés aux évaluations nationales de début de sixième par établissement",
        "explore_id": None,
        "datagouv": "6831448743bcf0349285887e",
        "obligatoire": False,
    },
}

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"


# ---------------------------------------------------------------- utilitaires

def log(msg: str) -> None:
    print(msg, flush=True)


def norm(s: str) -> str:
    """'Taux de réussite - G' -> 'taux_de_reussite_g'."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


class ColonneIntrouvable(KeyError):
    pass


def _alternatives(pattern: str) -> list[str]:
    """Découpe 'a|b(c|d)|e' en ['a', 'b(c|d)', 'e'] (alternatives de premier niveau)."""
    parts, depth, cur = [], 0, ""
    for ch in pattern:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def pick(df: pd.DataFrame, include: str, exclude: str | None = None, required: bool = True) -> str | None:
    """Renvoie la colonne correspondant à `include`.

    Les alternatives sont essayées dans l'ordre : 'nature_uai_libe|^nature' préfère
    nature_uai_libe même si nature_uai apparaît avant dans le fichier.
    """
    for alt in _alternatives(include):
        for col in df.columns:
            if re.search(alt, col) and not (exclude and re.search(exclude, col)):
                return col
    if required:
        raise ColonneIntrouvable(f"aucune colonne ne correspond à /{include}/ parmi : {list(df.columns)}")
    return None


def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False).str.strip(), errors="coerce")


def dep_code(value) -> str:
    """'075', '75', 75 -> '75' ; '2A' reste '2A'."""
    v = str(value).strip()
    return v.lstrip("0") if v.isdigit() else v


def round_or_none(x, nd=1):
    if x is None or pd.isna(x):
        return None
    return int(round(float(x))) if nd == 0 else round(float(x), nd)


# ---------------------------------------------------------------- téléchargement

def resolve(key: str) -> dict:
    """Complète la source avec son identifiant Explore et sa date de mise à jour."""
    src = dict(SOURCES[key])
    src["page"] = None
    src["maj"] = None
    if src["datagouv"]:
        try:
            r = HTTP.get(f"{DATAGOUV}/{src['datagouv']}/", timeout=60)
            r.raise_for_status()
            meta = r.json()
            src["page"] = meta.get("page")
            src["maj"] = meta.get("last_update") or meta.get("last_modified")
            src["titre"] = meta.get("title") or src["titre"]
            if not src["explore_id"]:
                for res in meta.get("resources", []):
                    m = re.search(r"data\.education\.gouv\.fr/(?:api/explore/v2\.1/catalog/datasets|explore/dataset|api/records/1\.0/download)/?(?:\?dataset=)?([A-Za-z0-9_\-]+)", res.get("url", ""))
                    if m:
                        src["explore_id"] = m.group(1)
                        break
                if not src["explore_id"]:
                    csv = [res for res in meta.get("resources", []) if (res.get("format") or "").lower() == "csv"]
                    if csv:
                        src["url_csv"] = csv[0]["url"]
        except Exception as exc:  # noqa: BLE001
            log(f"  ! data.gouv.fr indisponible pour {key} : {exc}")
    if src["explore_id"]:
        src.setdefault("page", None)
        src["page"] = src["page"] or f"https://data.education.gouv.fr/explore/dataset/{src['explore_id']}/"
        if not src["maj"]:
            try:
                r = HTTP.get(f"{EXPLORE}/{src['explore_id']}", timeout=60)
                r.raise_for_status()
                info = r.json()
                src["maj"] = info.get("metas", {}).get("default", {}).get("modified") or info.get("data_processed")
            except Exception as exc:  # noqa: BLE001
                log(f"  ! métadonnées Explore indisponibles pour {key} : {exc}")
    return src


def download(key: str, src: dict, local_dir: Path | None) -> pd.DataFrame:
    if local_dir:
        path = local_dir / f"{key}.csv"
        log(f"  lecture locale {path}")
        raw = path.read_bytes()
    elif src.get("explore_id"):
        url = f"{EXPLORE}/{src['explore_id']}/exports/csv?delimiter=%3B"
        log(f"  téléchargement {url}")
        r = HTTP.get(url, timeout=600)
        r.raise_for_status()
        raw = r.content
    elif src.get("url_csv"):
        log(f"  téléchargement {src['url_csv']}")
        r = HTTP.get(src["url_csv"], timeout=600)
        r.raise_for_status()
        raw = r.content
    else:
        raise RuntimeError(f"aucune adresse de téléchargement pour {key}")
    text = raw.decode("utf-8-sig", errors="replace")
    sep = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_values=[""])
    original = list(df.columns)
    df.columns = [norm(c) for c in df.columns]
    log(f"  {len(df)} lignes, colonnes : {original}")
    return df


# ---------------------------------------------------------------- traitements

def load_etablissements(df: pd.DataFrame) -> pd.DataFrame:
    c_uai = pick(df, r"^numero_uai$|^uai$")
    c_nom = pick(df, r"^appellation_officielle$|denomination_principale|^nom_etablissement$|patronyme")
    c_nature = pick(df, r"nature_uai_libe|^nature")
    c_secteur = pick(df, r"secteur_public_prive")
    c_commune = pick(df, r"libelle_commune|^commune$")
    c_dep = pick(df, r"^code_departement$|^code_dep")
    c_lat = pick(df, r"^latitude$")
    c_lon = pick(df, r"^longitude$")
    c_adr = pick(df, r"^adresse_uai$|adresse", required=False)
    c_cp = pick(df, r"code_postal", required=False)
    c_etat = pick(df, r"etat_etablissement_libe", required=False)
    if c_etat:
        df = df[df[c_etat].fillna("").map(norm).str.startswith("ouvert")]
    out = pd.DataFrame({
        "uai": df[c_uai].str.strip().str.upper(),
        "nom": df[c_nom].str.strip(),
        "nature": df[c_nature].fillna("").map(norm),
        "secteur": df[c_secteur].fillna("").map(lambda s: "public" if norm(s).startswith("pu") else "privé"),
        "commune": df[c_commune].str.replace(r"\s+", " ", regex=True).str.strip(),
        "dep": df[c_dep].map(dep_code),
        "lat": num(df[c_lat]),
        "lon": num(df[c_lon]),
        "adresse": df[c_adr].fillna("").str.strip() if c_adr else "",
        "cp": df[c_cp].fillna("").str.strip() if c_cp else "",
    })
    out = out[out["dep"].isin(DEPARTEMENTS) & out["nature"].str.contains("college")]
    out = out.dropna(subset=["lat", "lon"]).drop_duplicates("uai")
    log(f"  {len(out)} collèges géolocalisés dans les 5 départements "
        f"({(out['secteur'] == 'public').sum()} publics, {(out['secteur'] == 'privé').sum()} privés)")
    return out


def load_ivac(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    c_uai = pick(df, r"^uai$|numero_uai|^code_uai")
    c_session = pick(df, r"^session$|^annee|session")
    c_reussite = pick(df, r"taux_de_reussite.*_g$|taux_reussite.*_g$", exclude=r"attendu|^va|valeur|ecart")
    c_cand = pick(df, r"^nb_candidats.*_g$|^nombre_de_candidats.*_g$|candidats.*_g$")
    c_mentions = pick(df, r"^nb_mentions_global.*_g$|mentions_global.*_g$|^nb_mentions.*_g$", exclude=r"_tb|_b_|_ab|tres_bien|assez|attendu")
    c_tb = pick(df, r"mentions_tb.*_g$|mentions_tres_bien.*_g$", exclude=r"attendu")
    c_va = pick(df, r"(^va_|valeur_ajoutee).*reussite.*_g$", required=False)
    c_note = pick(df, r"note.*ecrit.*_g$", exclude=r"attendu|^va|valeur", required=False)
    c_va_note = pick(df, r"(^va_|valeur_ajoutee).*note.*_g$", required=False)
    log(f"  colonnes retenues : session={c_session} réussite={c_reussite} candidats={c_cand} "
        f"mentions={c_mentions} TB={c_tb} VA réussite={c_va} note écrit={c_note} VA note={c_va_note}")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    cand = num(d[c_cand])
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "session": d[c_session].str.strip(),
        "candidats": cand,
        "taux_reussite": num(d[c_reussite]),
        "taux_mentions": num(d[c_mentions]) / cand * 100,
        "taux_tb": num(d[c_tb]) / cand * 100,
        "va_reussite": num(d[c_va]) if c_va else float("nan"),
        "note_ecrit": num(d[c_note]) if c_note else float("nan"),
        "va_note": num(d[c_va_note]) if c_va_note else float("nan"),
    })
    out = out.dropna(subset=["taux_reussite"]).drop_duplicates(["uai", "session"])
    # Score optionnel : moyenne des trois taux bruts, rang parmi les collèges des deux académies.
    out["score"] = out[["taux_reussite", "taux_mentions", "taux_tb"]].mean(axis=1, skipna=False)
    out["rang"] = out.groupby("session")["score"].rank(ascending=False, method="min")
    out["nb_classes"] = out.groupby("session")["score"].transform("count")
    log(f"  {len(out)} lignes brevet, sessions {sorted(out['session'].unique())}")
    return out


def load_ips(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    c_uai = pick(df, r"^uai$|numero_uai|^code_uai")
    c_annee = pick(df, r"rentree|^annee")
    c_ips = pick(df, r"^ips$|^ips_|indice_de_position_sociale|indice_position_sociale", exclude=r"ecart|academ|depart|national")
    c_et = pick(df, r"ecart_type", exclude=r"academ|depart|national", required=False)
    log(f"  colonnes retenues : année={c_annee} IPS={c_ips} écart-type={c_et}")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)]
    out = pd.DataFrame({
        "uai": d[c_uai].str.strip().str.upper(),
        "annee": d[c_annee].str.strip(),
        "ips": num(d[c_ips]),
        "ips_et": num(d[c_et]) if c_et else float("nan"),
    }).dropna(subset=["ips"]).drop_duplicates(["uai", "annee"])
    log(f"  {len(out)} lignes IPS, années {sorted(out['annee'].unique())}")
    return out


def load_eval6e(df: pd.DataFrame, uais: set[str]) -> pd.DataFrame:
    c_uai = pick(df, r"^uai$|numero_uai|^code_uai")
    c_annee = pick(df, r"rentree|^annee|session")
    d = df[df[c_uai].str.strip().str.upper().isin(uais)].copy()
    c_matiere = pick(df, r"matiere|discipline|^domaine", required=False)
    for c in (pick(df, r"caracteristique", required=False), c_matiere, pick(df, r"libelle_secteur", required=False)):
        if c:
            log(f"  valeurs de {c} : {d[c].value_counts().head(15).to_dict()}")
    c_carac = pick(df, r"caracteristique", required=False)
    if c_carac:
        d = d[d[c_carac].fillna("").map(norm).isin(["ensemble", "total", "tous"])]
    if c_matiere:
        c_score = pick(df, r"score_moyen|moyenne", exclude=r"ecart|academ|depart|national|france")
        log(f"  format long : matière={c_matiere} score={c_score}")
        d["m"] = d[c_matiere].map(norm).map(lambda s: "fr" if s.startswith("fr") else ("ma" if s.startswith("math") else None))
        d = d.dropna(subset=["m"])
        d["v"] = num(d[c_score])
        wide = d.pivot_table(index=[c_uai, c_annee], columns="m", values="v", aggfunc="mean").reset_index()
        wide.columns.name = None
        wide = wide.rename(columns={c_uai: "uai", c_annee: "annee"})
    else:
        c_fr = pick(df, r"(score|moyenne).*fran|fran.*(score|moyenne)", exclude=r"ecart|academ|depart|national|france")
        c_ma = pick(df, r"(score|moyenne).*math|math.*(score|moyenne)", exclude=r"ecart|academ|depart|national|france")
        log(f"  format large : français={c_fr} maths={c_ma}")
        wide = pd.DataFrame({"uai": d[c_uai], "annee": d[c_annee], "fr": num(d[c_fr]), "ma": num(d[c_ma])})
    wide["uai"] = wide["uai"].str.strip().str.upper()
    wide["annee"] = wide["annee"].str.strip()
    for c in ("fr", "ma"):
        if c not in wide:
            wide[c] = float("nan")
    wide = wide.dropna(subset=["fr", "ma"], how="all").drop_duplicates(["uai", "annee"])
    log(f"  {len(wide)} lignes évaluations 6e, années {sorted(wide['annee'].unique())}")
    return wide[["uai", "annee", "fr", "ma"]]


# ---------------------------------------------------------------- export

def build_features(etabs, ivac, ips, ev) -> list[dict]:
    by = lambda df: {k: g for k, g in df.groupby("uai")} if df is not None and len(df) else {}
    ivac_by, ips_by, ev_by = by(ivac), by(ips), by(ev)
    feats = []
    for e in etabs.itertuples():
        p = {"uai": e.uai, "nom": e.nom, "commune": e.commune, "dep": e.dep,
             "departement": DEPARTEMENTS[e.dep], "academie": ACADEMIE_PAR_DEP[e.dep],
             "secteur": e.secteur, "adresse": f"{e.adresse}, {e.cp} {e.commune}".strip(", ")}
        hist = {}
        g = ivac_by.get(e.uai)
        if g is not None:
            g = g.sort_values("session")
            hist["brevet"] = [{
                "session": r.session, "candidats": round_or_none(r.candidats, 0),
                "taux_reussite": round_or_none(r.taux_reussite), "taux_mentions": round_or_none(r.taux_mentions),
                "taux_tb": round_or_none(r.taux_tb), "va_reussite": round_or_none(r.va_reussite),
                "note_ecrit": round_or_none(r.note_ecrit, 2), "va_note": round_or_none(r.va_note, 2),
                "score": round_or_none(r.score), "rang": round_or_none(r.rang, 0), "nb": round_or_none(r.nb_classes, 0),
            } for r in g.itertuples()]
            last = hist["brevet"][-1]
            p["session_brevet"] = last["session"]
            for k in ("taux_reussite", "taux_mentions", "taux_tb", "va_reussite", "note_ecrit", "va_note", "score", "rang", "nb"):
                p[k] = last[k]
        g = ips_by.get(e.uai)
        if g is not None:
            g = g.sort_values("annee")
            hist["ips"] = [{"annee": r.annee, "ips": round_or_none(r.ips), "ecart_type": round_or_none(r.ips_et)} for r in g.itertuples()]
            p["ips"] = hist["ips"][-1]["ips"]
            p["annee_ips"] = hist["ips"][-1]["annee"]
        g = ev_by.get(e.uai)
        if g is not None:
            g = g.sort_values("annee")
            hist["eval6e"] = [{"annee": r.annee, "fr": round_or_none(r.fr), "ma": round_or_none(r.ma)} for r in g.itertuples()][-5:]
            p["eval_fr"] = hist["eval6e"][-1]["fr"]
            p["eval_ma"] = hist["eval6e"][-1]["ma"]
            p["annee_eval"] = hist["eval6e"][-1]["annee"]
        p["hist"] = json.dumps(hist, ensure_ascii=False, separators=(",", ":"))
        p = {k: v for k, v in p.items() if v is not None}  # MapLibre : absence = donnée manquante
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e.lon, 6), round(e.lat, 6)]}, "properties": p})
    return feats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--local-dir", type=Path, default=None, help="dossier de CSV nommés <clé>.csv, pour tester hors ligne")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    resolved, frames, problemes = {}, {}, []
    for key in SOURCES:
        log(f"\n== {key}")
        src = resolve(key) if not args.local_dir else dict(SOURCES[key], page=None, maj=None)
        resolved[key] = src
        try:
            frames[key] = download(key, src, args.local_dir)
        except Exception as exc:  # noqa: BLE001
            if src["obligatoire"]:
                raise
            log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : téléchargement impossible ({exc})")

    log("\n== traitement")
    etabs = load_etablissements(frames["etablissements"])
    uais = set(etabs["uai"])
    results = {}
    for key, fn in (("ivac", load_ivac), ("ips", load_ips), ("eval6e", load_eval6e)):
        if key not in frames:
            results[key] = None
            continue
        log(f"-- {key}")
        try:
            results[key] = fn(frames[key], uais)
        except ColonneIntrouvable as exc:
            log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : {exc}")
            results[key] = None

    feats = build_features(etabs, results["ivac"], results["ips"], results["eval6e"])
    geo = {"type": "FeatureCollection", "features": feats}
    (out / "colleges.geojson").write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def periodes(df, col):
        return sorted(df[col].unique().tolist()) if df is not None and len(df) else []

    meta = {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perimetre": {"academies": ["Paris", "Versailles"], "departements": DEPARTEMENTS},
        "colleges": {"total": len(feats), "publics": int((etabs["secteur"] == "public").sum()), "prives": int((etabs["secteur"] == "privé").sum())},
        "periodes": {"brevet": periodes(results["ivac"], "session"), "ips": periodes(results["ips"], "annee"), "eval6e": periodes(results["eval6e"], "annee")},
        "sources": [{"cle": k, "titre": s["titre"], "page": s.get("page"), "mise_a_jour": s.get("maj")} for k, s in resolved.items()],
        "problemes": problemes,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"\n== terminé : {len(feats)} collèges écrits dans {out}")
    couverture = {k: sum(1 for f in feats if k in f["properties"]) for k in ("taux_reussite", "va_reussite", "note_ecrit", "ips", "eval_fr")}
    log(f"   couverture des indicateurs : {couverture}")
    for k in ("taux_reussite", "taux_mentions", "va_reussite", "note_ecrit", "ips", "eval_fr", "eval_ma", "score"):
        v = pd.Series([f["properties"][k] for f in feats if k in f["properties"]], dtype=float)
        if len(v):
            log(f"   {k:14s} n={len(v):4d} min={v.min():.1f} médiane={v.median():.1f} max={v.max():.1f}")
    exemple = next((f["properties"] for f in feats if "ips" in f["properties"] and "taux_reussite" in f["properties"]), None)
    if exemple:
        log(f"   exemple : {json.dumps({k: v for k, v in exemple.items() if k != 'hist'}, ensure_ascii=False)}")
    if problemes:
        log("   problèmes :\n   - " + "\n   - ".join(problemes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
