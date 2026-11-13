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

Usage : python pipeline/build.py --out site/data --cache-dir sources-cache
        python pipeline/build.py --out site/data --local-dir chemin/vers/csv  (tests hors ligne)

Robustesse : chaque téléchargement est réessayé ; si data.gouv.fr ne répond pas, une adresse de
secours sur data.education.gouv.fr est utilisée ; si la source reste injoignable (ou renvoie un
fichier anormalement court), la dernière version valide gardée dans --cache-dir est reprise et
le problème est signalé dans meta.json. Sans version valide, l'indicateur est absent et
tests/verifier_site.py bloque la publication.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent))
import colleges  # noqa: E402
import lycees  # noqa: E402

# Collèges et lycées : France métropolitaine (Corse comprise). L'outre-mer viendra plus tard.
METROPOLE = re.compile(r"\d{1,2}|2[AB]")

EXPLORE = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"
DATAGOUV = "https://www.data.gouv.fr/api/1/datasets"

# Jeux de données. "explore_id" est l'identifiant sur data.education.gouv.fr ;
# "datagouv" sert à le retrouver automatiquement s'il change ; "url_secours" est l'adresse de
# téléchargement constatée le 13/11/2026, utilisée quand data.gouv.fr ne répond pas.
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
        "url_secours": f"{EXPLORE}/fr-en-ips-colleges-ap2023/exports/csv?delimiter=%3B",
        "obligatoire": False,
    },
    "eval6e": {
        "titre": "Résultats consolidés aux évaluations nationales de début de sixième par établissement",
        "explore_id": None,
        "datagouv": "6831448743bcf0349285887e",
        "url_secours": f"{EXPLORE}/fr-en-evaluations_nationales_6eme_par_etablissement/exports/csv?delimiter=%3B",
        "obligatoire": False,
    },
    # Lycées : on lit directement le CSV publié sur data.gouv.fr (noms de colonnes vérifiés).
    "ival_gt": {
        "titre": "Indicateurs de valeur ajoutée des lycées d'enseignement général et technologique",
        "explore_id": None,
        "datagouv": "6707515c84dfa4012c3ecd45",
        "csv_direct": True,
        "url_secours": f"{EXPLORE}/fr-en-indicateurs-de-resultat-des-lycees-gt_v2/exports/csv?use_labels=true",
        "obligatoire": False,
    },
    "ival_pro": {
        "titre": "Indicateurs de valeur ajoutée des lycées d'enseignement professionnel",
        "explore_id": None,
        "datagouv": "6707516684dfa4012c3ecd47",
        "csv_direct": True,
        "url_secours": f"{EXPLORE}/fr-en-indicateurs-de-resultat-des-lycees-pro_v2/exports/csv?use_labels=true",
        "obligatoire": False,
    },
    "ips_lycees": {
        "titre": "Indices de position sociale des lycées (à partir de 2023)",
        "explore_id": None,
        "datagouv": "664d720768d6ab64e06740f0",
        "csv_direct": True,
        "url_secours": f"{EXPLORE}/fr-en-ips-lycees-ap2023/exports/csv?use_labels=true",
        "obligatoire": False,
    },
}

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"
# Réessais : 4 tentatives de plus, espacées de 5, 10, 20 puis 40 s, sur les erreurs de connexion
# et les réponses 429/5xx (pannes passagères des portails open data).
_REESSAIS = Retry(total=4, connect=4, read=4, status=4, backoff_factor=5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), raise_on_status=True)
HTTP.mount("https://", HTTPAdapter(max_retries=_REESSAIS))
HTTP.mount("http://", HTTPAdapter(max_retries=_REESSAIS))

# Pour vérifier les secours : SIMULER_PANNE="datagouv,ival_gt" fait comme si l'API data.gouv.fr
# et le téléchargement de ival_gt échouaient (variable d'environnement, vide en temps normal).
PANNES = {x.strip() for x in os.environ.get("SIMULER_PANNE", "").split(",") if x.strip()}

# Une source téléchargée est refusée si elle a moins de lignes que cette part de la dernière
# version valide (page d'erreur, export tronqué) : on garde alors la version précédente.
PART_MINIMALE = 0.5


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

def explore_id_de(url: str) -> str | None:
    m = re.search(r"/catalog/datasets/([A-Za-z0-9_\-]+)/exports", url or "")
    return m.group(1) if m else None


def resolve(key: str) -> dict:
    """Complète la source avec son adresse de téléchargement et sa date de mise à jour."""
    src = dict(SOURCES[key])
    src["page"] = None
    src["maj"] = None
    if src["datagouv"]:
        try:
            if "datagouv" in PANNES:
                raise RuntimeError("panne simulée (SIMULER_PANNE)")
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
    if not src["explore_id"] and not src.get("url_csv") and src.get("url_secours"):
        log(f"  adresse de secours : {src['url_secours']}")
        src["url_csv"] = src["url_secours"]
    eid = src["explore_id"] or explore_id_de(src.get("url_csv"))
    if eid:
        src["page"] = src["page"] or f"https://data.education.gouv.fr/explore/dataset/{eid}/"
        if not src["maj"]:
            try:
                r = HTTP.get(f"{EXPLORE}/{eid}", timeout=60)
                r.raise_for_status()
                info = r.json()
                src["maj"] = info.get("metas", {}).get("default", {}).get("modified") or info.get("data_processed")
            except Exception as exc:  # noqa: BLE001
                log(f"  ! métadonnées Explore indisponibles pour {key} : {exc}")
    return src


def adresse(src: dict) -> str | None:
    if src.get("explore_id"):
        return f"{EXPLORE}/{src['explore_id']}/exports/csv?delimiter=%3B"
    return src.get("url_csv")


def telecharger(key: str, url: str) -> bytes:
    if key in PANNES:
        raise RuntimeError("panne simulée (SIMULER_PANNE)")
    log(f"  téléchargement {url}")
    r = HTTP.get(url, timeout=600)
    r.raise_for_status()
    return r.content


def lire_csv(raw: bytes) -> pd.DataFrame:
    text = raw.decode("utf-8-sig", errors="replace")
    sep = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, na_values=[""])
    original = list(df.columns)
    df.columns = [norm(c) for c in df.columns]
    log(f"  {len(df)} lignes, colonnes : {original}")
    return df


# Cache des dernières versions valides de chaque source (dossier gardé entre deux passages par
# le cache GitHub Actions) : <clé>.csv.gz (fichier brut) et <clé>.json (adresse, date, lignes).

def lire_cache(cache_dir: Path | None, key: str) -> tuple[Path, dict] | None:
    if not cache_dir:
        return None
    brut, info = cache_dir / f"{key}.csv.gz", cache_dir / f"{key}.json"
    if not (brut.exists() and info.exists()):
        return None
    try:
        return brut, json.loads(info.read_text(encoding="utf-8"))
    except ValueError:
        return None


def ecrire_cache(cache_dir: Path | None, key: str, raw: bytes, info: dict) -> None:
    if not cache_dir:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.csv.gz").write_bytes(gzip.compress(raw, compresslevel=6))
    (cache_dir / f"{key}.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def obtenir(key: str, src: dict, cache_dir: Path | None) -> tuple[pd.DataFrame, str | None]:
    """Télécharge une source (adresse trouvée, puis adresse de secours) ; si rien ne marche,
    reprend la dernière version valide du cache. Renvoie le tableau et un éventuel problème."""
    precedent = lire_cache(cache_dir, key)
    urls = [u for u in dict.fromkeys([adresse(src), src.get("url_secours")]) if u]
    erreur: Exception = RuntimeError(f"aucune adresse de téléchargement pour {key}")
    for url in urls:
        try:
            raw = telecharger(key, url)
            df = lire_csv(raw)
            if df.empty:
                raise RuntimeError("fichier vide")
            if precedent and len(df) < PART_MINIMALE * precedent[1].get("lignes", 0):
                raise RuntimeError(f"{len(df)} lignes seulement, contre {precedent[1]['lignes']} dans la dernière version valide")
            ecrire_cache(cache_dir, key, raw, {
                "url": url, "telecharge_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "lignes": len(df), "titre": src.get("titre"), "page": src.get("page"), "maj": src.get("maj")})
            return df, None
        except Exception as exc:  # noqa: BLE001
            log(f"  ! échec du téléchargement : {exc}")
            erreur = exc
    if not precedent:
        raise erreur
    brut, info = precedent
    date = (info.get("telecharge_le") or "?")[:10]
    log(f"  reprise de la dernière version valide (téléchargée le {date}, {info.get('lignes')} lignes)")
    df = lire_csv(gzip.decompress(brut.read_bytes()))
    src["page"] = src.get("page") or info.get("page")
    src["maj"] = src.get("maj") or info.get("maj")
    src["reprise"] = date
    return df, f"{key} : source injoignable ({erreur}) ; version téléchargée le {date} réutilisée"


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
    ap.add_argument("--cache-dir", type=Path, default=None,
                    help="dossier des dernières versions valides des sources, reprises si un téléchargement échoue")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    resolved, frames, problemes = {}, {}, []
    for key in SOURCES:
        log(f"\n== {key}")
        try:
            if args.local_dir:
                src = dict(SOURCES[key], page=None, maj=None)
                path = args.local_dir / f"{key}.csv"
                log(f"  lecture locale {path}")
                frames[key] = lire_csv(path.read_bytes())
            else:
                src = resolve(key)
                frames[key], probleme = obtenir(key, src, args.cache_dir)
                if probleme:
                    problemes.append(probleme)
        except Exception as exc:  # noqa: BLE001
            if src["obligatoire"]:
                raise
            log(f"  ! {key} ignoré : {exc}")
            problemes.append(f"{key} : téléchargement impossible ({exc})")
        finally:
            resolved[key] = src

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
        "sources": [{"cle": k, "titre": s["titre"], "page": s.get("page"), "mise_a_jour": s.get("maj"),
                     **({"version_reprise": s["reprise"]} if s.get("reprise") else {})} for k, s in resolved.items()],
        "problemes": problemes,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"\n== terminé : {col_meta['colleges']['total']} collèges et {lyc_meta['total']} lycées écrits dans {out}")
    if problemes:
        log("   problèmes :\n   - " + "\n   - ".join(problemes))
    return 0



if __name__ == "__main__":
    sys.exit(main())
