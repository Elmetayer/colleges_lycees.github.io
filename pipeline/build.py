"""Prépare les données de la carte scolaire.

Télécharge les jeux open data de l'Éducation nationale, calcule les indicateurs et écrit :
  - <out>/colleges.geojson         : un point par collège de France métropolitaine, avec
                                     la dernière valeur de chaque indicateur (fichier léger)
  - <out>/fiches/colleges-<dep>.json : historique des collèges d'un département, chargé
                                     à l'ouverture d'une fiche
  - <out>/lycees.geojson           : un point par lycée de France métropolitaine (fichier léger)
  - <out>/fiches/lycees-<dep>.json : historique des lycées d'un département
  - <out>/meta.json                : date de génération, sessions, médianes, sources

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

sys.path.insert(0, str(Path(__file__).parent))
import lycees  # noqa: E402

# Collèges et lycées : France métropolitaine (Corse comprise). L'outre-mer viendra plus tard.
METROPOLE = re.compile(r"\d{1,2}|2[AB]")

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
    # Lycées : on lit directement le CSV publié sur data.gouv.fr (noms de colonnes vérifiés).
    "ival_gt": {
        "titre": "Indicateurs de valeur ajoutée des lycées d'enseignement général et technologique",
        "explore_id": None,
        "datagouv": "6707515c84dfa4012c3ecd45",
        "csv_direct": True,
        "obligatoire": False,
    },
    "ival_pro": {
        "titre": "Indicateurs de valeur ajoutée des lycées d'enseignement professionnel",
        "explore_id": None,
        "datagouv": "6707516684dfa4012c3ecd47",
        "csv_direct": True,
        "obligatoire": False,
    },
    "ips_lycees": {
        "titre": "Indices de position sociale des lycées (à partir de 2023)",
        "explore_id": None,
        "datagouv": "664d720768d6ab64e06740f0",
        "csv_direct": True,
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
    """'075', '75', 75 -> '75' ; '02A' et '2A' -> '2A' ; '971' reste '971'."""
    v = str(value).strip().upper()
    if v.isdigit():
        return v.lstrip("0") or "0"
    return v[1:] if len(v) == 3 and v[0] == "0" else v


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
            if not src["explore_id"] and not src.get("csv_direct"):
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
    c_ldep = pick(df, r"^libelle_departement$|libelle_dep", required=False)
    c_acad = pick(df, r"^libelle_academie$|libelle_acad", required=False)
    log(f"  colonnes retenues : département={c_dep} ({c_ldep}) académie={c_acad}")
    if c_etat:
        df = df[df[c_etat].fillna("").map(norm).str.startswith("ouvert")]
    out = pd.DataFrame({
        "uai": df[c_uai].str.strip().str.upper(),
        "nom": df[c_nom].str.strip(),
        "nature": df[c_nature].fillna("").map(norm),
        "secteur": df[c_secteur].fillna("").map(lambda s: "public" if norm(s).startswith("pu") else "privé"),
        "commune": df[c_commune].str.replace(r"\s+", " ", regex=True).str.strip(),
        "dep": df[c_dep].map(dep_code),
        "departement": df[c_ldep].fillna("").str.strip() if c_ldep else "",
        "academie": df[c_acad].fillna("").str.strip() if c_acad else "",
        "lat": num(df[c_lat]),
        "lon": num(df[c_lon]),
        "adresse": df[c_adr].fillna("").str.strip() if c_adr else "",
        "cp": df[c_cp].fillna("").str.strip() if c_cp else "",
    })
    out = out[out["dep"].map(lambda d: bool(METROPOLE.fullmatch(d)))]
    out["departement"] = out["departement"].where(out["departement"] != "", out["dep"])
    out["academie"] = out["academie"].where(out["academie"] != "", "Non renseignée")
    out = out.dropna(subset=["lat", "lon"]).drop_duplicates("uai")
    return out


def colleges_de(etabs: pd.DataFrame) -> pd.DataFrame:
    out = etabs[etabs["nature"].str.contains("college")]
    log(f"  {len(out)} collèges géolocalisés en France métropolitaine "
        f"({(out['secteur'] == 'public').sum()} publics, {(out['secteur'] == 'privé').sum()} privés), "
        f"{out['dep'].nunique()} départements, {out['academie'].nunique()} académies")
    log(f"  collèges par académie : {out['academie'].value_counts().to_dict()}")
    return out


def load_ivac(df: pd.DataFrame, uais: set[str], academies: dict[str, str]) -> pd.DataFrame:
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
    # Score optionnel : moyenne des trois taux bruts. Rang national (France métropolitaine)
    # et rang dans l'académie, pour la même session.
    out["score"] = out[["taux_reussite", "taux_mentions", "taux_tb"]].mean(axis=1, skipna=False)
    out["academie"] = out["uai"].map(academies)
    out["rang"] = out.groupby("session")["score"].rank(ascending=False, method="min")
    out["nb_classes"] = out.groupby("session")["score"].transform("count")
    out["rang_acad"] = out.groupby(["session", "academie"])["score"].rank(ascending=False, method="min")
    out["nb_acad"] = out.groupby(["session", "academie"])["score"].transform("count")
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

def build_features(etabs, ivac, ips, ev) -> tuple[list[dict], dict[str, dict]]:
    """Renvoie les points (dernière valeur de chaque indicateur) et les historiques par département."""
    by = lambda df: {k: g for k, g in df.groupby("uai")} if df is not None and len(df) else {}
    ivac_by, ips_by, ev_by = by(ivac), by(ips), by(ev)
    feats, fiches = [], {}
    for e in etabs.itertuples():
        p = {"uai": e.uai, "nom": e.nom, "commune": e.commune, "dep": e.dep,
             "departement": e.departement, "academie": e.academie, "secteur": e.secteur}
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
                "rang_acad": round_or_none(r.rang_acad, 0), "nb_acad": round_or_none(r.nb_acad, 0),
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
        if hist:
            fiches.setdefault(e.dep, {})[e.uai] = {
                "adresse": f"{e.adresse}, {e.cp} {e.commune}".strip(", "),
                "hist": {k: [{c: v for c, v in r.items() if v is not None} for r in rows] for k, rows in hist.items()},
            }
        p = {k: v for k, v in p.items() if v is not None}  # MapLibre : absence = donnée manquante
        # 5 décimales (environ 1 m) suffisent et allègent le fichier national.
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(e.lon, 5), round(e.lat, 5)]}, "properties": p})
    return feats, fiches


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
    tous = load_etablissements(frames["etablissements"])
    etabs = colleges_de(tous)
    uais = set(etabs["uai"])
    academies = dict(zip(etabs["uai"], etabs["academie"]))
    results = {}
    for key, fn in (("ivac", load_ivac), ("ips", load_ips), ("eval6e", load_eval6e)):
        if key not in frames:
            results[key] = None
            continue
        log(f"-- {key}")
        try:
            results[key] = fn(frames[key], uais, academies) if key == "ivac" else fn(frames[key], uais)
        except ColonneIntrouvable as exc:
            log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : {exc}")
            results[key] = None

    feats, fiches = build_features(etabs, results["ivac"], results["ips"], results["eval6e"])
    geo = {"type": "FeatureCollection", "features": feats}
    compact = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    (out / "colleges.geojson").write_text(compact(geo), encoding="utf-8")
    dossier_fiches = out / "fiches"
    dossier_fiches.mkdir(exist_ok=True)
    for f in dossier_fiches.glob("colleges-*.json"):
        f.unlink()
    for dep, contenu in fiches.items():
        (dossier_fiches / f"colleges-{dep}.json").write_text(compact(contenu), encoding="utf-8")
    tailles = sorted(((f.stat().st_size, f.name) for f in dossier_fiches.glob("colleges-*.json")), reverse=True)
    log(f"\n== tailles : colleges.geojson {(out / 'colleges.geojson').stat().st_size / 1e6:.2f} Mo ; "
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
                    "taux_reussite": round_or_none(g["taux_reussite"].median()),
                    "taux_mentions": round_or_none(g["taux_mentions"].median()),
                    "va_reussite": round_or_none(g["va_reussite"].median()),
                    "note_ecrit": round_or_none(g["note_ecrit"].median(), 2),
                    "va_note": round_or_none(g["va_note"].median(), 2),
                    "score": round_or_none(g["score"].median()),
                }
        if ip is not None and len(ip):
            for an, g in ip.groupby("annee"):
                m["ips"][an] = round_or_none(g["ips"].median())
        if ev is not None and len(ev):
            for an, g in ev.groupby("annee"):
                m["eval6e"][an] = {"fr": round_or_none(g["fr"].median()), "ma": round_or_none(g["ma"].median())}
        return m

    def periodes(df, col):
        return sorted(df[col].unique().tolist()) if df is not None and len(df) else []

    log("\n== lycées")
    lyc_meta = lycees.construire(tous, frames, out, problemes)

    meta = {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perimetre": {"colleges": "France métropolitaine", "lycees": "France métropolitaine"},
        "colleges": {"total": len(feats), "publics": int((etabs["secteur"] == "public").sum()), "prives": int((etabs["secteur"] == "privé").sum())},
        "periodes": {"brevet": periodes(results["ivac"], "session"), "ips": periodes(results["ips"], "annee"), "eval6e": periodes(results["eval6e"], "annee")},
        # Médianes nationales (France métropolitaine) et par académie (fiches des collèges).
        "medianes": medianes(),
        "medianes_academies": {a: medianes(set(g["uai"])) for a, g in etabs.groupby("academie")},
        "lycees": lyc_meta,
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
            log(f"   {k:14s} n={len(v):5d} min={v.min():.1f} médiane={v.median():.1f} max={v.max():.1f}")
    exemple = next((f["properties"] for f in feats if "ips" in f["properties"] and "taux_reussite" in f["properties"]), None)
    if exemple:
        log(f"   exemple : {json.dumps(exemple, ensure_ascii=False)}")
    sans = {k: sum(1 for f in feats if k not in f["properties"]) for k in ("taux_reussite", "ips")}
    par_dep = pd.Series([f["properties"]["dep"] for f in feats if "taux_reussite" not in f["properties"]]).value_counts().head(8).to_dict()
    log(f"   collèges sans indicateur : {sans} ; départements les plus touchés (brevet) : {par_dep}")
    if problemes:
        log("   problèmes :\n   - " + "\n   - ".join(problemes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
