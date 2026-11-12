"""Prépare les données de la carte scolaire.

Télécharge les jeux open data de l'Éducation nationale et lit l'annuaire des établissements,
puis confie les calculs aux modules colleges.py et lycees.py. Fichiers écrits :
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
import colleges  # noqa: E402
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


def sans_nan(p: dict) -> dict:
    """Retire les valeurs absentes (None, NaN) : un NaN écrit tel quel rend le GeoJSON illisible par le navigateur."""
    return {k: v for k, v in p.items() if v is not None and not (isinstance(v, float) and v != v)}


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
    c_denom = pick(df, r"^denomination_principale$", required=False)
    c_patro = pick(df, r"^patronyme_uai$|^patronyme$", required=False)
    log(f"  colonnes retenues : département={c_dep} ({c_ldep}) académie={c_acad}")
    if c_etat:
        df = df[df[c_etat].fillna("").map(norm).str.startswith("ouvert")]
    out = pd.DataFrame({
        "uai": df[c_uai].str.strip().str.upper(),
        "nom": df[c_nom].fillna("").str.strip(),
        "nature": df[c_nature].fillna("").map(norm),
        "secteur": df[c_secteur].fillna("").map(lambda s: "public" if norm(s).startswith("pu") else "privé"),
        "commune": df[c_commune].fillna("").str.replace(r"\s+", " ", regex=True).str.strip(),
        "dep": df[c_dep].map(dep_code),
        "departement": df[c_ldep].fillna("").str.strip() if c_ldep else "",
        "academie": df[c_acad].fillna("").str.strip() if c_acad else "",
        "lat": num(df[c_lat]),
        "lon": num(df[c_lon]),
        "adresse": df[c_adr].fillna("").str.strip() if c_adr else "",
        "cp": df[c_cp].fillna("").str.strip() if c_cp else "",
    })
    out = out[out["dep"].map(lambda d: bool(METROPOLE.fullmatch(d)))]
    # Nom manquant dans l'annuaire (quelques établissements) : dénomination + patronyme, sinon l'UAI.
    sans_nom = out["nom"] == ""
    if sans_nom.any():
        rechange = ((df.loc[out.index, c_denom].fillna("") if c_denom else "") + " " +
                    (df.loc[out.index, c_patro].fillna("") if c_patro else "")).str.strip() \
            if (c_denom or c_patro) else pd.Series("", index=out.index)
        out.loc[sans_nom, "nom"] = rechange[sans_nom].str.title().where(rechange[sans_nom] != "", "Établissement " + out.loc[sans_nom, "uai"])
        log(f"  ! {int(sans_nom.sum())} établissements sans nom dans l'annuaire : {out.loc[sans_nom, ['uai', 'nom']].values.tolist()[:10]}")
    out["departement"] = out["departement"].where(out["departement"] != "", out["dep"])
    out["academie"] = out["academie"].where(out["academie"] != "", "Non renseignée")
    out = out.dropna(subset=["lat", "lon"]).drop_duplicates("uai")
    return out


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

    log("\n== collèges")
    col_meta = colleges.construire(tous, frames, out, problemes)

    log("\n== lycées")
    lyc_meta = lycees.construire(tous, frames, out, problemes)

    meta = {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perimetre": {"colleges": "France métropolitaine", "lycees": "France métropolitaine"},
        **col_meta,  # colleges, periodes, medianes, medianes_academies
        "lycees": lyc_meta,
        "sources": [{"cle": k, "titre": s["titre"], "page": s.get("page"), "mise_a_jour": s.get("maj")} for k, s in resolved.items()],
        "problemes": problemes,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"\n== terminé : {col_meta['colleges']['total']} collèges et {lyc_meta['total']} lycées écrits dans {out}")
    if problemes:
        log("   problèmes :\n   - " + "\n   - ".join(problemes))
    return 0



if __name__ == "__main__":
    sys.exit(main())
