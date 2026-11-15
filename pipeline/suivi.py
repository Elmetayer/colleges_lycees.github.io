"""Suivi de la récupération des données : rapport du build et historique (page site/suivi.html).

  python pipeline/suivi.py rapport --site site --statut en_cours|success|failure
      Assemble data/suivi.json à partir de data/telechargements.json (build.py), data/meta.json (modules et
      assemblage des secteurs) et data/verification.json (tests/verifier_site.py), s'ils existent : un build
      arrêté en route donne quand même un rapport, avec ce qui manque.

  python pipeline/suivi.py publier --site site --branche suivi-donnees
      Range le rapport dans la branche suivi-donnees du dépôt : suivi/dernier.json (rapport complet du dernier
      build de main, publié ou non) et suivi/historique.json (HISTORIQUE derniers builds, état de chaque source).
      La page lit ces deux fichiers sur raw.githubusercontent.com : un build en échec n'est pas publié sur le
      site, mais son rapport l'est.

États d'une source : ok (téléchargée, lignes en nombre habituel) ; partiel (version précédente réutilisée,
adresse de secours, ou moins de PART_ALERTE des lignes de la version précédente) ; ko (rien obtenu).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HISTORIQUE = 10
PART_ALERTE = 0.9
DEPARTEMENTS_METROPOLE = 96
GROUPES = [
    ("etablissements", "Établissements et indicateurs"),
    ("secteurs_colleges", "Secteurs des collèges"),
    ("secteurs_ecoles", "Secteurs des écoles"),
]


def lire(chemin: Path):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def nombre(n) -> str:
    return f"{n:,}".replace(",", " ") if isinstance(n, int) else ("—" if n is None else str(n))


def pourcent(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}".replace(".", ",") + " %"


def producteur(url: str | None) -> str:
    hote = urlparse(url or "").netloc
    return hote.removeprefix("www.") or "—"


def groupe_de(cle: str) -> str:
    return "secteurs_ecoles" if cle.startswith(("secteurs_", "ecoles_paris")) else "etablissements"


def sur_la_carte(cle: str, meta: dict) -> str:
    """Ce que la source apporte à la carte, d'après meta.json."""
    col, lyc, eco = (meta.get("colleges") or {}), (meta.get("lycees") or {}), (meta.get("ecoles") or {})
    cc, cl, ce = col.get("couverture") or {}, lyc.get("couverture") or {}, eco.get("couverture") or {}
    textes = {
        "etablissements": col.get("total") and f"{nombre(col.get('total'))} collèges, {nombre(lyc.get('total'))} lycées, {nombre(eco.get('total'))} écoles",
        "annuaire_education": "type de contrat, date d'ouverture, niveaux des écoles",
        "ivac": cc.get("taux_reussite") and f"{nombre(cc['taux_reussite'])} collèges avec résultats au brevet",
        "ips": cc.get("ips") and f"{nombre(cc['ips'])} collèges avec IPS",
        "eval6e": cc.get("eval_fr") and f"{nombre(cc['eval_fr'])} collèges avec évaluations",
        "ival_gt": cl.get("gt_reussite") and f"{nombre(cl['gt_reussite'])} lycées avec résultats",
        "ival_pro": cl.get("pro_reussite") and f"{nombre(cl['pro_reussite'])} lycées avec résultats",
        "ips_lycees": cl.get("ips") and f"{nombre(cl['ips'])} lycées avec IPS",
        "ips_ecoles": ce.get("ips") and f"{nombre(ce['ips'])} écoles avec IPS",
        "effectifs_ecoles": ce.get("eleves") and f"{nombre(ce['eleves'])} écoles avec effectifs",
        "taille_classes": ce.get("classe") and f"{nombre(ce['classe'])} écoles avec taille des classes",
    }
    if cle in textes:
        return textes[cle] or "—"
    # Secteurs des écoles : bloc de la ville (« Ville de Paris »…), retrouvé par le titre de la source.
    for fid, m in ((eco.get("secteurs") or {}).items()):
        if (fid == "75" and "paris" in cle) or (fid != "75" and fid.split("-", 1)[-1] in cle):
            niv = "maternelle" if "maternelle" in cle else "elementaire"
            c = m.get(niv) or {}
            if cle.startswith("ecoles_paris"):
                return f"rattachement des écoles : {pourcent(c.get('rattachement'))}"
            quand = c.get("annee") or (f"mis à jour le {fr_date(c.get('maj'))}" if c.get("maj") else "")
            return f"{nombre(c.get('secteurs'))} secteurs" + (f", {quand}" if quand else "")
    return "non publiés"


def fr_date(iso: str | None, heure: bool = False) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:10]
    if d.tzinfo:
        d = d.astimezone(PARIS)
    return d.strftime("%d/%m/%Y à %H:%M" if heure else "%d/%m/%Y")


try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001
    PARIS = timezone.utc


def ligne_source(t: dict, meta: dict, secteurs_villes: dict) -> dict:
    erreurs = t.get("erreurs") or []
    lignes, prec = t.get("lignes"), t.get("lignes_precedentes")
    details = [["Adresse lue", t.get("url") or "—"]]
    for e in erreurs:
        details.append(["Erreur", f"{producteur(e.get('url'))} : {e.get('message')}", "alerte"])
    if t.get("echec") and not erreurs:
        details.append(["Erreur", t["echec"], "alerte"])
    if prec:
        details.append(["Version précédente", f"{nombre(prec)} lignes"])
    if t.get("version_reprise"):
        etat = "partiel"
        details.append(["Version réutilisée", f"téléchargée le {fr_date(t['version_reprise'])}", "attention"])
    elif not lignes:
        etat = "ko"
    elif t.get("secours"):
        etat = "partiel"
        details.append(["Adresse de secours", "l'adresse principale n'a pas répondu", "attention"])
    elif prec and lignes < PART_ALERTE * prec:
        etat = "partiel"
        details.append(["Baisse", f"{nombre(lignes)} lignes contre {nombre(prec)} la fois précédente", "attention"])
    else:
        etat = "ok"
    carte = sur_la_carte(t["cle"], meta)
    # Secteurs d'une ville téléchargés mais non publiés (l'autre jeu manque, ou contrôles impossibles).
    if etat != "ko" and groupe_de(t["cle"]) == "secteurs_ecoles" and carte == "non publiés":
        etat = "ko"
        details.append(["Effet sur la carte", "secteurs de cette ville absents de cette mise à jour", "alerte"])
    if etat == "ko":
        carte = "absent de cette mise à jour"
    return {
        "cle": t["cle"], "titre": t.get("titre") or t["cle"], "producteur": producteur(t.get("url") or t.get("page")),
        "page": t.get("page"), "lignes": lignes, "lignes_precedentes": prec, "carte": carte,
        "mise_a_jour": t.get("mise_a_jour"), "telecharge_le": t.get("telecharge_le"), "etat": etat, "details": details,
    }


def lignes_secteurs_colleges(meta: dict) -> list[dict]:
    s = meta.get("secteurs")
    if not s:
        return [{"cle": "secteurs_colleges", "titre": "Secteurs des collèges", "producteur": "data.gouv.fr, adresse.data.gouv.fr",
                 "page": None, "lignes": None, "carte": "absents de cette mise à jour", "etat": "ko",
                 "details": [["Erreur", "l'assemblage des secteurs n'a pas abouti : la carte est publiée sans secteurs", "alerte"]]}]
    b = s.get("bilan") or {}
    adresses = s.get("adresses") or {}
    par_source = {}
    for d, v in adresses.items():
        par_source.setdefault(v.get("source_adresses") or "inconnue", []).append(d)
    echecs, anciens = b.get("echecs") or [], b.get("groupes_anciens") or []
    calc = {
        "cle": "carte_scolaire", "titre": "Carte scolaire des collèges publics, secteurs calculés à l'adresse",
        "producteur": "data.gouv.fr · adresse.data.gouv.fr · geo.api.gouv.fr", "page": "https://www.data.gouv.fr/datasets/carte-scolaire-des-colleges-publics/",
        "lignes": None, "carte": f"{s.get('departements')} départements sur {DEPARTEMENTS_METROPOLE}, {nombre(s.get('zones'))} zones",
        "mise_a_jour": None, "telecharge_le": None, "etat": "partiel" if (echecs or anciens) else "ok",
        "details": [
            ["Recalculés", ", ".join(b.get("recalcules") or []) or "aucun (carte scolaire inchangée)"],
            ["Inchangés", f"{len(b.get('inchanges') or [])} départements, secteurs repris du calcul précédent"],
            ["Adresses", " ; ".join(f"{src} : {len(ds)} départements" for src, ds in sorted(par_source.items())) or "—"],
            ["Absents de la source", f"{DEPARTEMENTS_METROPOLE - (s.get('departements') or 0)} départements sans carte scolaire nationale (limite connue)"],
        ],
    }
    if echecs:
        calc["details"].append(["En échec", ", ".join(echecs) + " : derniers secteurs valides conservés", "attention"])
    if anciens:
        calc["details"].append(["Groupes non recalculés", f"groupes {', '.join(map(str, anciens))} : calcul interrompu, secteurs du passage précédent", "attention"])
    ctrl = s.get("controle") or {}
    off = {
        "cle": "secteurs_officiels", "titre": "Secteurs officiels de Paris et des Hauts-de-Seine (contrôle)",
        "producteur": "opendata.paris.fr · opendata.hauts-de-seine.fr", "page": None,
        "lignes": None, "carte": "contrôle de la méthode", "mise_a_jour": None, "telecharge_le": None,
        "etat": "ok" if len(ctrl) >= 2 else ("partiel" if ctrl else "ko"),
        "details": [[f"Concordance {nom}", f"{pourcent(c.get('taux_surface'))} de la surface attribuée au même collège ({c.get('colleges')} collèges)"]
                    for nom, c in ctrl.items()] or [["Erreur", "secteurs officiels non téléchargés : contrôle impossible", "alerte"]],
    }
    return [calc, off]


def rapport(site: Path, statut: str) -> dict:
    data = site / "data"
    tele = lire(data / "telechargements.json") or []
    meta = lire(data / "meta.json") or {}
    verif = lire(data / "verification.json")
    groupes = {g: [] for g, _ in GROUPES}
    for t in tele:
        groupes[groupe_de(t["cle"])].append(ligne_source(t, meta, {}))
    if meta:
        groupes["secteurs_colleges"] = lignes_secteurs_colleges(meta)
    toutes = [r for g in groupes.values() for r in g]
    compte = {e: sum(1 for r in toutes if r["etat"] == e) for e in ("ok", "partiel", "ko")}
    erreurs = (verif or {}).get("erreurs") or []
    if not tele:
        erreurs = ["le build s'est arrêté avant de télécharger les sources"] + erreurs
    elif not meta:
        erreurs = ["le build s'est arrêté avant d'écrire les données (meta.json absent)"] + erreurs
    etat = "ko" if (compte["ko"] or statut == "failure") else "partiel" if compte["partiel"] else "ok"
    eco = meta.get("ecoles") or {}
    serveur, depot, passage = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return {
        "version": 1,
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statut": {"success": "publie", "failure": "echec", "cancelled": "echec"}.get(statut, "en_cours"),
        "etat": etat,
        "build": {"passage": passage, "lien": f"{serveur}/{depot}/actions/runs/{passage}" if passage else None,
                  "commit": (os.environ.get("GITHUB_SHA") or "")[:7] or None, "evenement": os.environ.get("GITHUB_EVENT_NAME"),
                  "branche": os.environ.get("GITHUB_REF_NAME")},
        "compte": compte,
        "chiffres": {
            "colleges": (meta.get("colleges") or {}).get("total"), "lycees": (meta.get("lycees") or {}).get("total"), "ecoles": eco.get("total"),
            "secteurs_departements": (meta.get("secteurs") or {}).get("departements"), "departements": DEPARTEMENTS_METROPOLE,
            "villes_ecoles": [m.get("source", fid).removeprefix("Ville de ") for fid, m in (eco.get("secteurs") or {}).items()],
        },
        "groupes": [{"cle": g, "titre": titre, "lignes": groupes[g]} for g, titre in GROUPES],
        "controles": (verif or {}).get("controles") or [],
        "navigateur": (verif or {}).get("navigateur") or {},
        "verification": None if verif is None else ("ok" if verif.get("ok") else "echec"),
        "erreurs": erreurs[:30],
        "problemes": (meta.get("problemes") or [])[:30],
    }


def cmd_rapport(args) -> int:
    site = Path(args.site)
    (site / "data").mkdir(parents=True, exist_ok=True)
    r = rapport(site, args.statut)
    (site / "data" / "suivi.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"suivi : {r['statut']}, état {r['etat']}, sources {r['compte']}, {len(r['controles'])} contrôles, {len(r['erreurs'])} erreurs")
    return 0


def git(*a, cwd=None):
    subprocess.run(["git", *a], cwd=cwd, check=True)


def cmd_publier(args) -> int:
    r = lire(Path(args.site) / "data" / "suivi.json")
    if not r:
        print("suivi : pas de rapport à publier")
        return 0
    depot = f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/{os.environ['GITHUB_REPOSITORY']}.git"
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        existe = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", depot, args.branche], capture_output=True).returncode == 0
        if existe:
            git("clone", "--quiet", "--depth", "1", "--branch", args.branche, depot, str(d))
        else:
            git("init", "--quiet", "-b", args.branche, str(d))
            git("remote", "add", "origin", depot, cwd=d)
            (d / "README.md").write_text("Rapports de récupération des données de la carte scolaire, écrits par le workflow "
                                         "« Construire et publier la carte » et lus par la page suivi.html du site. "
                                         "Ne pas supprimer cette branche.\n", encoding="utf-8")
        git("config", "user.name", "github-actions[bot]", cwd=d)
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=d)
        (d / "suivi").mkdir(exist_ok=True)
        (d / "suivi" / "dernier.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        hist = lire(d / "suivi" / "historique.json") or []
        hist = [h for h in hist if h.get("passage") != r["build"]["passage"]]
        hist.insert(0, {"genere_le": r["genere_le"], "passage": r["build"]["passage"], "lien": r["build"]["lien"],
                        "commit": r["build"]["commit"], "evenement": r["build"]["evenement"], "statut": r["statut"], "etat": r["etat"],
                        "sources": {l["cle"]: l["etat"] for g in r["groupes"] for l in g["lignes"]},
                        "titres": {l["cle"]: l["titre"] for g in r["groupes"] for l in g["lignes"]}})
        (d / "suivi" / "historique.json").write_text(json.dumps(hist[:HISTORIQUE], ensure_ascii=False, indent=1), encoding="utf-8")
        git("add", "-A", cwd=d)
        git("commit", "--quiet", "-m", f"Suivi : build {r['build']['passage']} ({r['statut']}, {r['etat']})", cwd=d)
        git("push", "--quiet", "origin", args.branche, cwd=d)
    print(f"suivi : rapport rangé dans la branche {args.branche} ({len(hist[:HISTORIQUE])} builds dans l'historique)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sous = ap.add_subparsers(dest="cmd", required=True)
    a = sous.add_parser("rapport")
    a.add_argument("--site", default="site")
    a.add_argument("--statut", default="en_cours")
    p = sous.add_parser("publier")
    p.add_argument("--site", default="site")
    p.add_argument("--branche", default="suivi-donnees")
    args = ap.parse_args()
    return cmd_rapport(args) if args.cmd == "rapport" else cmd_publier(args)


if __name__ == "__main__":
    sys.exit(main())
