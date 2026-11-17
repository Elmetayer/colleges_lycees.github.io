"""Vérifie le site construit avant de le publier. Échoue (code 1) si un problème bloquant est trouvé.

1. Les fichiers de données sont du JSON strict (pas de NaN) et contiennent des établissements,
   avec une couverture minimale de chaque indicateur (COUVERTURE_MINIMALE).
   Écoles : fichiers par département (data/ecoles/), au moins ECOLES_MINIMUM écoles et une
   couverture minimale de leurs indicateurs (COUVERTURE_ECOLES).
2. Le site, ouvert dans Chromium (ordinateur et téléphone), charge les calques des collèges,
   des lycées et des écoles, et les fiches d'un collège, d'un lycée et d'une école s'ouvrent avec
   leurs indicateurs (une fiche impossible à tester, faute d'établissement avec l'indicateur, est un
   échec) ; la fiche d'une école publique donne son collège de secteur, celle d'une école hors
   contrat l'explication de l'absence de données ; les écoles ne s'affichent qu'en zoomant : petits points sous les
   collèges à l'échelle d'une région (zoom 7, couche « ecoles-loin »), formes au-dessus à partir du zoom 10, zones des
   écoles à partir du zoom 11.
   Secteurs des écoles (Paris, autres villes) : contrôles du rattachement aux écoles (SECTEURS_ECOLES_MINIMUM) ;
   la fiche d'une école de Paris donne son secteur, dont la zone est dessinée, et l'onglet « Entrée en 6e »
   (évaluations de 6e du collège de secteur).
   Zones des communes (seule école publique, regroupements pédagogiques : pipeline/zones_communes.py) : nombre de
   communes couvertes et part des élèves (ZONES_COMMUNES_MINIMUM) ; la fiche d'une école seule dans sa commune et celle
   d'une école de RPI donnent leur zone, dessinée avec un contour plein.
3. Les secteurs concordent avec les secteurs officiels de Paris et des Hauts-de-Seine : au moins
   CONCORDANCE_MINIMALE de la surface attribuée au même collège (meta.json, secteurs.controle).
   Si les secteurs officiels n'ont pas pu être téléchargés, simple avertissement.

Usage : python tests/verifier_site.py site   (le dossier site doit déjà contenir data/)
Les secteurs absents ne bloquent pas : ils sont signalés en avertissement.
SIMULER_CONCORDANCE (variable d'environnement, ex. 0.95) remplace CONCORDANCE_MINIMALE pour vérifier le blocage.
"""
import asyncio
import functools
import http.server
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

GOATCOUNTER = 'data-goatcounter="https://macartescolaire.goatcounter.com/count"'
# Actions comptées (app.js, compter()) : jamais le texte d'une adresse ni une position.
ACTION_AUDIENCE = re.compile(r"^(fiche-(ecole|college|lycee)/[0-9A-Z]{8}|recherche-(adresse|etablissement|commune)|adresse-(secteur-trouve|sans-secteur))$")
SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
erreurs, avertissements = [], []
# Contrôles chiffrés et résultat du test navigateur, écrits dans data/verification.json pour la page de suivi.
controles, navigateur = [], {}


def controle(libelle: str, valeur, seuil, unite: str = "") -> bool:
    """Consigne un contrôle à seuil (page de suivi) ; renvoie True s'il passe."""
    ok = valeur is not None and valeur >= seuil
    controles.append({"libelle": libelle, "valeur": valeur, "seuil": seuil, "unite": unite, "ok": ok})
    return ok


COUVERTURE_MINIMALE = {
    "colleges.geojson": {"taux_reussite": 5300, "ips": 5400, "eval_fr": 5400},
    "lycees.geojson": {"gt_reussite": 1900, "pro_reussite": 1550, "ips": 2750},
}

# Écoles (jalon 7) : environ 80 % des effectifs attendus d'après le diagnostic du 14/11/2026
# (IPS : 29 070 écoles en 2024-2025 ; effectifs : 47 418 écoles à la rentrée 2025 ; taille des classes : 47 148).
ECOLES_MINIMUM = 40000
COUVERTURE_ECOLES = {"ips": 23000, "eleves": 36000, "classe": 36000,
                     # Entrée en 6e : évaluations du collège de secteur (pipeline/ecoles_6e.py), écoles publiques
                     # des départements qui ont une carte scolaire des collèges.
                     # 34 887 / 34 876 le 15/11/2026 (40 743 écoles publiques, 84 départements).
                     "e6_fr": 31000, "e6_ma": 31000}
# Secteurs des écoles de Paris (jalon 7b), valeurs du 15/11/2026 : rattachement des noms de la Ville aux UAI
# 0,998 / 0,994 ; écoles publiques citées dans un secteur 0,963 / 0,989 ; écoles dans leur propre secteur 0,979 / 1.
SECTEURS_ECOLES_MINIMUM = {"rattachement": 0.95, "couverture": 0.9, "coherence": 0.9}
# Zones des communes (jalon 7d). Diagnostic du 16/11/2026 : 11 602 communes à une seule élémentaire publique hors RPI
# dispersé (1 001 398 élèves, 31,2 %) et 11 392 à une seule maternelle (543 417, 29,5 %), plus les communes des RPI
# dispersés (2 844 regroupements) ; seuils à environ 70 % de ces valeurs.
ZONES_COMMUNES_MINIMUM = {"elementaire": {"communes": 11000, "part_eleves": 0.22}, "maternelle": {"communes": 10000, "part_eleves": 0.2}}

# Part minimale de la surface attribuée au même collège que dans les secteurs officiels.
# Valeurs au 13/11/2026 : Paris 0,937, Hauts-de-Seine 0,923 ; 0,85 laisse environ 8 points de marge.
CONCORDANCE_MINIMALE = float(os.environ.get("SIMULER_CONCORDANCE") or 0.85)
DEPARTEMENTS_CONTROLE = ("Paris", "Hauts-de-Seine")
LIBELLES = {
    ("colleges.geojson", "taux_reussite"): "Collèges avec résultats au brevet", ("colleges.geojson", "ips"): "Collèges avec IPS",
    ("colleges.geojson", "eval_fr"): "Collèges avec évaluations de 6e", ("lycees.geojson", "gt_reussite"): "Lycées GT avec résultats",
    ("lycees.geojson", "pro_reussite"): "Lycées professionnels avec résultats", ("lycees.geojson", "ips"): "Lycées avec IPS",
    ("ecoles", "ips"): "Écoles avec IPS", ("ecoles", "eleves"): "Écoles avec effectifs", ("ecoles", "classe"): "Écoles avec taille des classes",
    ("ecoles", "e6_fr"): "Écoles avec l'entrée en 6e (français)", ("ecoles", "e6_ma"): "Écoles avec l'entrée en 6e (maths)",
}
NIVEAUX_SECTEURS = {"elementaire": "élémentaires", "maternelle": "maternelles"}


def refuser_constante(nom):
    raise ValueError(f"valeur {nom} interdite en JSON")


def verifier_fichiers():
    data = SITE / "data"
    fichiers = (sorted(data.glob("*.json")) + sorted(data.glob("*.geojson")) + sorted(data.glob("fiches/*.json"))
                + sorted(data.glob("secteurs/*.json")) + sorted(data.glob("secteurs/*.geojson")))
    contenus = {}
    for f in fichiers:
        try:
            contenus[f.name] = json.loads(f.read_text(encoding="utf-8"), parse_constant=refuser_constante)
        except ValueError as e:
            erreurs.append(f"{f.relative_to(SITE)} n'est pas du JSON valide : {e}")
    print(f"{len(fichiers)} fichiers de données lus")
    for nom, minimum in (("colleges.geojson", 1000), ("lycees.geojson", 1000)):
        g = contenus.get(nom)
        if g is None:
            erreurs.append(f"{nom} absent ou illisible")
            continue
        n = len(g.get("features", []))
        sans_nom = sum(1 for f in g["features"] if not f["properties"].get("nom"))
        print(f"{nom} : {n} établissements, {sans_nom} sans nom")
        if n < minimum:
            erreurs.append(f"{nom} : seulement {n} établissements (au moins {minimum} attendus)")
        if sans_nom:
            erreurs.append(f"{nom} : {sans_nom} établissements sans nom")
    # Couverture des indicateurs : un indicateur qui disparaît (source injoignable et aucune version
    # précédente à reprendre) bloque la publication ; le site garde alors sa version en ligne.
    # Seuils : environ 80 % de la couverture constatée le 13/11/2026.
    for nom, seuils in COUVERTURE_MINIMALE.items():
        feats = (contenus.get(nom) or {}).get("features", [])
        couverture = {k: sum(1 for f in feats if isinstance(f["properties"].get(k), (int, float))) for k in seuils}
        print(f"{nom} : couverture {couverture}")
        for k, mini in seuils.items():
            if not controle(LIBELLES.get((nom, k), f"{nom} {k}"), couverture[k], mini):
                erreurs.append(f"{nom} : indicateur {k} présent pour {couverture[k]} établissements seulement (au moins {mini} attendus)")
    meta = contenus.get("meta.json") or {}
    sb = (meta.get("colleges") or {}).get("sans_brevet") or {}
    print(f"collèges sans brevet, par raison : {sb}")
    if sb.get("hors_contrat", 0) < 300:
        avertissements.append(f"seulement {sb.get('hors_contrat', 0)} collèges hors contrat repérés (annuaire de l'éducation indisponible ?)")
    for pb in meta.get("problemes", []):
        avertissements.append(f"meta.json : {pb}")
    verifier_ecoles(data, contenus)
    index = contenus.get("index.json")
    if not index:
        avertissements.append("secteurs/index.json absent : la carte sera publiée sans secteurs")
    else:
        print(f"secteurs : {len(index)} départements")
        vides = [d for d, v in index.items() if not v.get("zones")]
        if vides:
            avertissements.append(f"départements sans aucune zone : {vides}")
        # Concordance avec les secteurs officiels : une dégradation du calcul bloque la publication.
        ctrl_off = (meta.get("secteurs") or {}).get("controle") or {}
        for dep in DEPARTEMENTS_CONTROLE:
            c = ctrl_off.get(dep)
            if not c or c.get("taux_surface") is None:
                avertissements.append(f"contrôle des secteurs impossible pour {dep} (secteurs officiels non téléchargés)")
                continue
            print(f"secteurs : {dep}, {c['taux_surface']:.1%} de la surface attribuée au même collège que les secteurs officiels")
            if not controle(f"Concordance des secteurs des collèges, {dep}", round(c["taux_surface"] * 100, 1), round(CONCORDANCE_MINIMALE * 100, 1), "%"):
                erreurs.append(f"secteurs : {dep}, {c['taux_surface']:.1%} seulement de la surface attribuée au même collège "
                               f"que les secteurs officiels (au moins {CONCORDANCE_MINIMALE:.0%} attendus)")
    return contenus


def verifier_ecoles(data, contenus):
    """Écoles : un fichier par département, lu à part (les noms 75.geojson existent aussi dans secteurs/)."""
    dossier = data / "ecoles"
    points = []
    for f in sorted(dossier.glob("*.geojson")):
        try:
            points += json.loads(f.read_text(encoding="utf-8"), parse_constant=refuser_constante).get("features", [])
        except ValueError as e:
            erreurs.append(f"{f.relative_to(SITE)} n'est pas du JSON valide : {e}")
    for nom in ("index.json", "recherche.json"):
        try:
            contenus["ecoles/" + nom] = json.loads((dossier / nom).read_text(encoding="utf-8"), parse_constant=refuser_constante)
        except (OSError, ValueError) as e:
            erreurs.append(f"ecoles/{nom} absent ou illisible : {e}")
    contenus["ecoles"] = points
    # Secteurs des écoles : fichiers lisibles et contrôles du rattachement (meta.json, ecoles.secteurs).
    zones, par_fichier = [], {}
    for f in sorted((data / "secteurs-ecoles").glob("*.geojson")):
        try:
            par_fichier[f.stem] = json.loads(f.read_text(encoding="utf-8"), parse_constant=refuser_constante).get("features", [])
            zones += par_fichier[f.stem]
        except ValueError as e:
            erreurs.append(f"{f.relative_to(SITE)} n'est pas du JSON valide : {e}")
    contenus["secteurs-ecoles"] = zones
    contenus["secteurs-ecoles-fichiers"] = par_fichier
    sect = ((contenus.get("meta.json") or {}).get("ecoles") or {}).get("secteurs")
    if not sect:
        avertissements.append("secteurs des écoles absents (Ville de Paris injoignable et aucune version à reprendre ?)")
    else:
        for dep, m in sect.items():
            for niv in ("elementaire", "maternelle"):
                c = m.get(niv) or {}
                print(f"secteurs des écoles {dep}, {niv} {c.get('annee') or c.get('maj')} : {c.get('secteurs')} zones, rattachement {c.get('rattachement')}, "
                      f"couverture {c.get('couverture')}, cohérence {c.get('coherence')}")
                for k, mini in SECTEURS_ECOLES_MINIMUM.items():
                    if not controle(f"Secteurs des écoles, {m.get('source', dep)}, {NIVEAUX_SECTEURS[niv]} : {k}",
                                    round((c.get(k) or 0) * 100, 1), round(mini * 100, 1), "%"):
                        erreurs.append(f"secteurs des écoles {dep} ({niv}) : {k} {c.get(k)} (au moins {mini} attendu)")
        if not zones:
            erreurs.append("secteurs des écoles annoncés dans meta.json mais aucun fichier secteurs-ecoles/*.geojson")
        for fid in sect:
            if fid not in par_fichier:
                erreurs.append(f"secteurs des écoles {fid} annoncés dans meta.json mais fichier secteurs-ecoles/{fid}.geojson absent")
    # Zones des communes : fichiers lisibles, chiffres de meta.json (ecoles.zones_communes).
    zc_zones = []
    for f in sorted((data / "zones-communes").glob("*.geojson")):
        try:
            zc_zones += json.loads(f.read_text(encoding="utf-8"), parse_constant=refuser_constante).get("features", [])
        except ValueError as e:
            erreurs.append(f"{f.relative_to(SITE)} n'est pas du JSON valide : {e}")
    contenus["zones-communes"] = zc_zones
    zc = ((contenus.get("meta.json") or {}).get("ecoles") or {}).get("zones_communes")
    if not zc:
        avertissements.append("zones des communes absentes (annuaire sans code commune ou contours injoignables ?)")
    else:
        if not zc_zones:
            erreurs.append("zones des communes annoncées dans meta.json mais aucun fichier zones-communes/*.geojson")
        for niv, seuils in ZONES_COMMUNES_MINIMUM.items():
            c = zc.get(niv) or {}
            print(f"zones des communes, {niv} : {c.get('zones_commune')} communes à une école, {c.get('zones_rpi')} RPI sur {c.get('communes_rpi')} communes, "
                  f"{c.get('eleves')} élèves ({c.get('part_eleves')})")
            if not controle(f"Zones des communes, {NIVEAUX_SECTEURS[niv]} : communes couvertes", c.get("communes"), seuils["communes"]):
                erreurs.append(f"zones des communes ({niv}) : {c.get('communes')} communes (au moins {seuils['communes']} attendues)")
            if not controle(f"Zones des communes, {NIVEAUX_SECTEURS[niv]} : élèves du public couverts", round((c.get("part_eleves") or 0) * 100, 1), round(seuils["part_eleves"] * 100, 1), "%"):
                erreurs.append(f"zones des communes ({niv}) : part des élèves {c.get('part_eleves')} (au moins {seuils['part_eleves']} attendu)")
    sans_nom = sum(1 for f in points if not f["properties"].get("nom"))
    couverture = {k: sum(1 for f in points if isinstance(f["properties"].get(k), (int, float))) for k in COUVERTURE_ECOLES}
    print(f"écoles : {len(points)} dans {len(list(dossier.glob('*.geojson')))} départements, {sans_nom} sans nom ; couverture {couverture}")
    if not controle("Écoles sur la carte", len(points), ECOLES_MINIMUM):
        erreurs.append(f"écoles : seulement {len(points)} (au moins {ECOLES_MINIMUM} attendues)")
    if sans_nom:
        erreurs.append(f"écoles : {sans_nom} sans nom")
    for k, mini in COUVERTURE_ECOLES.items():
        if not controle(LIBELLES.get(("ecoles", k), f"écoles {k}"), couverture[k], mini):
            erreurs.append(f"écoles : indicateur {k} présent pour {couverture[k]} écoles seulement (au moins {mini} attendues)")
    # Le menu du calque ne propose un indicateur que si meta.json donne son échelle de couleurs.
    couleurs = ((contenus.get("meta.json") or {}).get("ecoles") or {}).get("couleurs") or {}
    for k in COUVERTURE_ECOLES:
        if k != "eleves" and k not in couleurs:
            erreurs.append(f"écoles : pas d'échelle de couleurs pour {k} dans meta.json (indicateur absent du menu du calque)")
    hc = sum(1 for f in points if f["properties"].get("contrat") == "hors")
    if hc < 500:
        avertissements.append(f"seulement {hc} écoles hors contrat repérées (annuaire de l'éducation indisponible ?)")


norm_dep = lambda d: str(int(d)) if str(d).isdigit() else str(d)


def ecole_a_tester(contenus, public=True):
    """Requête de recherche (nom et commune) d'une école à tester : publique avec IPS et taille des classes,
    dans un département qui a des secteurs (pour le collège de secteur), ou privée hors contrat."""
    index = contenus.get("index.json") or {}
    avec_secteurs = {norm_dep(d) for d, v in index.items() if v.get("zones")}
    # Paris d'abord : ses secteurs couvrent toute la ville, l'école a donc forcément un collège de secteur ;
    # et de préférence une école citée dans un secteur d'école (fiche avec « Voir le secteur sur la carte »).
    cites = {u for z in contenus.get("secteurs-ecoles", []) for u in z["properties"].get("uais", "").split()}
    for f in sorted(contenus.get("ecoles", []), key=lambda f: (f["properties"].get("dep") != "75", f["properties"]["uai"] not in cites)):
        p = f["properties"]
        if public and p.get("secteur") == "public" and "ips" in p and "classe" in p and norm_dep(p["dep"]) in avec_secteurs:
            return f"{p['nom']} {p['commune']}", p
        if not public and p.get("contrat") == "hors":
            return f"{p['nom']} {p['commune']}", p
    return None, None


def ecoles_des_villes(contenus):
    """[(requête, source)] : pour chaque ville hors Paris, une école publique citée dans ses secteurs."""
    sect = ((contenus.get("meta.json") or {}).get("ecoles") or {}).get("secteurs") or {}
    out = []
    for fid, zones in (contenus.get("secteurs-ecoles-fichiers") or {}).items():
        if fid == "75":
            continue
        cites = {u for z in zones for u in z["properties"].get("uais", "").split()}
        p = next((f["properties"] for f in contenus.get("ecoles", []) if f["properties"]["uai"] in cites and f["properties"].get("secteur") == "public" and "ips" in f["properties"]), None)
        if p:
            out.append((f"{p['nom']} {p['commune']}", (sect.get(fid) or {}).get("source") or "Ville de"))
    return out


def ecoles_des_communes(contenus):
    """[(requête, textes attendus)] : une école seule dans sa commune (zone élémentaire) et une école de RPI dispersé,
    avec IPS et taille des classes (fiche à onglets) et un nom distinctif (la recherche doit la trouver en premier)."""
    zones = [z for z in contenus.get("zones-communes", []) if "elementaire" in z["properties"].get("niveau", "").split()]
    points = {f["properties"]["uai"]: f["properties"] for f in contenus.get("ecoles", [])}
    generiques = {"ecole", "école", "primaire", "elementaire", "élémentaire", "publique", "maternelle", "de", "du", "la", "le", "des"}
    out = []
    for regle, attendus in (("commune", ["Seule école publique", "Voir la commune sur la carte"]),
                            ("rpi", ["Regroupement pédagogique intercommunal", "Voir le regroupement sur la carte"])):
        for z in zones:
            pr = z["properties"]
            if pr.get("regle") != regle or pr.get("concentre"):
                continue
            p = next((points[u] for u in pr.get("uais", "").split() if u in points), None)
            if p and "ips" in p and "classe" in p and len([w for w in p["nom"].lower().split() if w not in generiques]) >= 2:
                out.append((f"{p['nom']} {p['commune']}", attendus, regle))
                break
    return out


def college_hors_idf(contenus):
    """(nom, fichier du département) d'un collège public hors Île-de-France dont le département a des secteurs."""
    index = contenus.get("index.json") or {}
    fichiers = {norm_dep(d): d for d, v in index.items() if v.get("zones")}
    for f in contenus.get("colleges.geojson", {}).get("features", []):
        p = f["properties"]
        d = norm_dep(p.get("dep", ""))
        if p.get("secteur") == "public" and "taux_reussite" in p and d in fichiers and d not in ("75", "77", "78", "91", "92", "93", "94", "95"):
            return p["nom"], fichiers[d]
    return None, None


def exemple(contenus, fichier, cle):
    """Nom d'un établissement qui a l'indicateur `cle`, pour tester sa fiche."""
    for f in contenus.get(fichier, {}).get("features", []):
        if cle in f["properties"]:
            return f["properties"]["nom"]
    return None


async def ouvrir_fiche(pg, nom, attendu, selecteur="#fiche-contenu .onglets button", attente=1200, interdit=None, onglet=None):
    await pg.fill("#recherche", nom)
    await pg.wait_for_timeout(attente)
    await pg.keyboard.press("ArrowDown")
    await pg.keyboard.press("Enter")
    try:
        await pg.wait_for_selector(selecteur, timeout=10000)
    except Exception:  # noqa: BLE001
        texte = (await pg.inner_text("#fiche-contenu")) if await pg.query_selector("#fiche-contenu") else ""
        return f"la fiche « {nom} » n'affiche pas d'indicateurs : {texte[:200]!r}"
    texte = await pg.inner_text("#fiche-contenu")
    for a in (attendu if isinstance(attendu, list) else [attendu]):
        if a not in texte:
            return f"la fiche « {nom} » ne contient pas « {a} » : {texte[:300]!r}"
    if interdit and interdit in texte:
        return f"la fiche « {nom} » contient « {interdit} » : {texte[:300]!r}"
    if onglet:
        # (clé de l'onglet, texte attendu dans son contenu)
        bouton = await pg.query_selector(f"#fiche-contenu [data-onglet={onglet[0]}]")
        if not bouton:
            return f"la fiche « {nom} » n'a pas d'onglet « {onglet[0]} »"
        await bouton.click()
        await pg.wait_for_timeout(300)
        contenu = await pg.inner_text("#fiche-graphe")
        if onglet[1] not in contenu or "svg" not in (await pg.inner_html("#fiche-graphe")):
            return f"l'onglet « {onglet[0]} » de la fiche « {nom} » est incomplet : {contenu[:300]!r}"
    await pg.click("#fermer")
    return None


async def verifier_navigateur(contenus):
    college = exemple(contenus, "colleges.geojson", "taux_reussite")
    lycee = exemple(contenus, "lycees.geojson", "ips")
    hors_contrat = next((f["properties"]["nom"] for f in contenus.get("colleges.geojson", {}).get("features", [])
                         if f["properties"].get("sans_brevet") == "hors_contrat"), None)
    college_secteur, fichier_secteur = college_hors_idf(contenus)
    ecole, p_ecole = ecole_a_tester(contenus)
    secteur_ecole = bool(p_ecole) and any(p_ecole["uai"] in z["properties"].get("uais", "").split() for z in contenus.get("secteurs-ecoles", []))
    ecole_hc, _ = ecole_a_tester(contenus, public=False)
    ecoles_villes = ecoles_des_villes(contenus)
    ecoles_communes = ecoles_des_communes(contenus) if contenus.get("zones-communes") else []
    if contenus.get("zones-communes") and len(ecoles_communes) < 2:
        avertissements.append(f"zones des communes : {len(ecoles_communes)} fiche(s) d'exemple trouvée(s) sur 2 (commune, RPI)")
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for appareil, ctx in (("ordinateur", {"viewport": {"width": 1280, "height": 800}}), ("téléphone", p.devices["iPhone 13"])):
            c = await b.new_context(**ctx)
            # GoatCounter : script bloqué pendant le test, remplacé par un relevé des actions comptées.
            async def bloquer(route):
                await route.abort()
            await c.route("**/gc.zgo.at/**", bloquer)
            await c.add_init_script("window.goatcounter = { appels: [], count(o) { this.appels.push(o.path); } };")
            pg = await c.new_page()
            problemes, secteurs_charges = [], []
            pg.on("response", lambda r: secteurs_charges.append(r.url) if "/data/secteurs/" in r.url and "index.json" not in r.url and r.ok else None)
            pg.on("pageerror", lambda e: problemes.append(f"erreur JavaScript : {e}"))
            pg.on("console", lambda m: problemes.append(f"console : {m.text}")
                  if m.type in ("warning", "error") and "indisponibles" in m.text and "Secteurs" not in m.text else None)
            await pg.goto("http://localhost:8765/index.html")
            try:
                await pg.wait_for_function("document.getElementById('etat').textContent === ''", timeout=45000)
            except Exception:  # noqa: BLE001
                problemes.append("les établissements ne finissent pas de charger : "
                                 + await pg.evaluate("document.getElementById('etat').textContent"))
            # Vue nationale au démarrage : aucune zone affichée, indication « Zoomez » visible.
            await pg.wait_for_timeout(2000)
            if await pg.evaluate("!!(window.carteScolaire && window.carteScolaire.getLayer('secteurs-fond'))"):
                await pg.evaluate("window.carteScolaire.jumpTo({center: [2.4, 46.6], zoom: 5})")
                await pg.wait_for_timeout(1500)
                rendues = await pg.evaluate("window.carteScolaire.queryRenderedFeatures({layers: ['secteurs-fond']}).length")
                indice = await pg.evaluate("!document.getElementById('indice-secteurs').hidden")
                if rendues or not indice:
                    problemes.append(f"vue nationale : {rendues} zones affichées, indication « Zoomez » {'visible' if indice else 'absente'}")
                ecoles_rendues = await pg.evaluate("window.carteScolaire.getLayer('ecoles') ? window.carteScolaire.queryRenderedFeatures({layers: ['ecoles', 'ecoles-loin'].filter((l) => window.carteScolaire.getLayer(l))}).length : -1")
                texte_indice = await pg.inner_text("#indice-secteurs")
                if ecoles_rendues != 0 or "écoles" not in texte_indice:
                    problemes.append(f"vue nationale : calque des écoles {'absent' if ecoles_rendues < 0 else f'avec {ecoles_rendues} écoles affichées'}, "
                                     f"indication « {texte_indice} »")
                # Vue région (zoom 7,5 sur Lyon) : écoles en petits points, pas encore de zones d'écoles, indication.
                await pg.evaluate("window.carteScolaire.jumpTo({center: [4.85, 45.75], zoom: 7.5})")
                await pg.wait_for_timeout(4000)
                loin = await pg.evaluate("window.carteScolaire.getLayer('ecoles-loin') ? window.carteScolaire.queryRenderedFeatures({layers: ['ecoles-loin']}).length : -1")
                zones_region = await pg.evaluate("window.carteScolaire.getLayer('secteurs-ecoles-fond') ? window.carteScolaire.queryRenderedFeatures({layers: ['secteurs-ecoles-fond']}).length : 0")
                texte_indice = await pg.inner_text("#indice-secteurs") if await pg.is_visible("#indice-secteurs") else ""
                if loin <= 0 or zones_region or "secteurs des écoles" not in texte_indice:
                    problemes.append(f"vue région (zoom 7,5) : {'couche ecoles-loin absente' if loin < 0 else f'{loin} écoles affichées'}, "
                                     f"{zones_region} zones d'écoles, indication « {texte_indice} »")
                else:
                    print(f"{appareil} : vue région (zoom 7,5), {loin} écoles en petits points, indication « {texte_indice} »")
                await pg.evaluate("window.carteScolaire.jumpTo({center: [4.85, 45.75], zoom: 10.5})")
                await pg.wait_for_timeout(2500)
                dessus = await pg.evaluate("window.carteScolaire.queryRenderedFeatures({layers: ['ecoles']}).length")
                if dessus <= 0:
                    problemes.append("zoom 10,5 : aucune école dans la couche au-dessus des collèges")
                else:
                    print(f"{appareil} : zoom 10,5, {dessus} écoles au-dessus des collèges")
            panneau = await pg.inner_text("#panneau")
            if "Données indisponibles" in panneau:
                problemes.append("un calque affiche « Données indisponibles »")
            for nom, attendu, type_ in ((college, "brevet", "collège"), (lycee, "IPS", "lycée")):
                if not nom:
                    problemes.append(f"aucun {type_} n'a l'indicateur nécessaire pour tester sa fiche")
                    continue
                pb = await ouvrir_fiche(pg, nom, attendu)
                if pb:
                    problemes.append(pb)
            # École publique : fiche avec IPS (rangs) et collège de secteur ; écoles affichées une fois zoomé.
            if ecole:
                attendus = ["Collège de secteur"] + (["Voir le secteur sur la carte"] if secteur_ecole else [])
                pb = await ouvrir_fiche(pg, ecole, attendus, attente=3000, interdit="Non disponible",
                                        onglet=("entree6e", "Ce ne sont pas les résultats de cette école"))
                if pb:
                    problemes.append(pb)
                await pg.wait_for_timeout(1500)
                if secteur_ecole:
                    zn = await pg.evaluate("window.carteScolaire.getLayer('secteurs-ecoles-fond') ? window.carteScolaire.queryRenderedFeatures({layers: ['secteurs-ecoles-fond']}).length : -1")
                    if zn <= 0:
                        problemes.append(f"secteurs des écoles : {'calque absent' if zn < 0 else 'aucune zone affichée'} après avoir ouvert la fiche « {ecole} »")
                    else:
                        print(f"{appareil} : {zn} zones de secteurs d'écoles à l'écran")
                n = await pg.evaluate("window.carteScolaire.queryRenderedFeatures({layers: ['ecoles']}).length")
                if n == 0:
                    problemes.append(f"aucune école affichée après avoir ouvert la fiche « {ecole} » (zoom {await pg.evaluate('window.carteScolaire.getZoom()'):.1f})")
                else:
                    print(f"{appareil} : fiche école « {ecole} » ouverte, {n} écoles à l'écran")
            else:
                problemes.append("aucune école publique avec IPS et taille des classes dans un département à secteurs : fiche école non testée")
            # Secteurs des autres villes : une école de chaque ville, avec son secteur et la source.
            if appareil == "ordinateur":
                for requete, source in ecoles_villes:
                    pb = await ouvrir_fiche(pg, requete, ["Voir le secteur sur la carte", source], attente=3000)
                    if pb:
                        problemes.append(pb)
                    else:
                        print(f"{appareil} : fiche école « {requete} » avec son secteur ({source})")
            # Zones des communes : fiche d'une école seule dans sa commune et d'une école de RPI, zone dessinée.
            for requete, attendus, regle in ecoles_communes:
                pb = await ouvrir_fiche(pg, requete, attendus, attente=3000)
                if pb:
                    problemes.append(pb)
                    continue
                await pg.wait_for_timeout(1500)
                zn = await pg.evaluate("window.carteScolaire.getLayer('secteurs-ecoles-commune') ? window.carteScolaire.queryRenderedFeatures({layers: ['secteurs-ecoles-commune']}).length : -1")
                if zn <= 0:
                    problemes.append(f"zones des communes : {'calque absent' if zn < 0 else 'aucune zone affichée'} après avoir ouvert la fiche « {requete} »")
                else:
                    print(f"{appareil} : fiche école « {requete} » avec sa zone ({regle}), {zn} zones de communes à l'écran")
            if ecole_hc:
                pb = await ouvrir_fiche(pg, ecole_hc, "hors contrat", "#fiche-contenu .sans-brevet", attente=2000)
                if pb:
                    problemes.append(pb)
            else:
                avertissements.append("aucune école hors contrat repérée : fiche réduite non testée")
            # Collège sans brevet : la fiche en donne la raison (privé hors contrat).
            if hors_contrat:
                pb = await ouvrir_fiche(pg, hors_contrat, "hors contrat", "#fiche-contenu .sans-brevet")
                if pb:
                    problemes.append(pb)
            else:
                avertissements.append("aucun collège hors contrat repéré : raison de l'absence de brevet non testée")
            # Secteurs chargés à la demande : au démarrage (vue nationale) aucun département n'est chargé ;
            # après avoir zoomé sur un collège hors Île-de-France, celui de son département doit l'être.
            if college_secteur:
                pb = await ouvrir_fiche(pg, college_secteur, "brevet")
                if pb:
                    problemes.append(pb)
                await pg.wait_for_timeout(3000)
                charges = [u for u in secteurs_charges if f"/data/secteurs/{fichier_secteur}.geojson" in u]
                rendues = await pg.evaluate("window.carteScolaire ? window.carteScolaire.queryRenderedFeatures({layers: ['secteurs-fond']}).length : -1")
                if charges and rendues == 0:
                    problemes.append(f"les secteurs du département {fichier_secteur} sont chargés mais aucune zone n'est affichée")
                elif charges:
                    print(f"{appareil} : secteurs du département {fichier_secteur} chargés et affichés ({rendues} zones à l'écran) "
                          f"en zoomant sur « {college_secteur} » ; "
                          f"{len(secteurs_charges)} départements chargés en tout")
                else:
                    problemes.append(f"les secteurs du département {fichier_secteur} ne se chargent pas en zoomant sur « {college_secteur} » "
                                     f"(chargés : {[u.split('/')[-1].split('?')[0] for u in secteurs_charges]})")
            # Bouton « Effacer la recherche » : caché champ vide, visible avec du texte, vide le champ au clic.
            # (la recherche est branchée une fois les établissements chargés : attendre comme au démarrage)
            await pg.goto("http://localhost:8765/index.html")
            await pg.wait_for_function("document.getElementById('etat').textContent === ''", timeout=45000)
            if await pg.is_visible("#effacer-recherche"):
                problemes.append("recherche : le bouton Effacer est visible alors que le champ est vide")
            await pg.fill("#recherche", "Lyon")
            await pg.wait_for_timeout(300)
            if not await pg.is_visible("#effacer-recherche"):
                problemes.append("recherche : le bouton Effacer n'apparaît pas après la saisie")
            else:
                await pg.click("#effacer-recherche")
                await pg.wait_for_timeout(300)
                valeur = await pg.input_value("#recherche")
                if valeur or await pg.is_visible("#effacer-recherche") or await pg.is_visible("#suggestions"):
                    problemes.append(f"recherche : après Effacer, champ « {valeur} », bouton ou suggestions encore visibles")
                else:
                    print(f"{appareil} : bouton Effacer de la recherche OK")
            # Mesure d'audience : chaque action comptée a un nom attendu (aucune adresse, aucune position).
            appels = await pg.evaluate("(window.goatcounter && window.goatcounter.appels) || []")
            mauvais = [a for a in appels if not ACTION_AUDIENCE.match(str(a))]
            if mauvais:
                problemes.append(f"audience : actions inattendues {mauvais[:3]}")
            else:
                print(f"{appareil} : audience, {len(appels)} action(s) comptée(s) : {sorted(set(a.split('/')[0] for a in appels))}")
            # Pages de documentation : chargement sans erreur, données de meta.json affichées.
            for page in sorted(SITE.glob("documentation*.html")):
                await pg.goto(f"http://localhost:8765/{page.name}")
                await pg.wait_for_timeout(800)
                for sel, vide in (("#liste-sources", "Chargement"), ("#resume-donnees", "Chargement"), ("#liste-villes-ecoles", "Chargement"), ("#ecoles-communes-chiffres", "Chargement")):
                    el = await pg.query_selector(sel)
                    if el and (vide in await el.inner_text() or "pas pu" in await el.inner_text()):
                        problemes.append(f"{page.name} : {sel} n'est pas rempli")
                # Page sur la construction du site (usage de l'IA) : auteur, IA nommée, lien pour signaler une erreur.
                if page.name == "documentation-construction.html":
                    texte = await pg.inner_text("main")
                    lien = await pg.query_selector("#signaler a[href$='/issues']")
                    if "Bruno Lemetayer" not in texte or "Claude" not in texte or not lien:
                        problemes.append("documentation-construction.html : auteur, IA ou lien vers les issues manquant")
                if page.name == "documentation.html" and not await pg.query_selector(".doc-cartes a[href='documentation-construction.html']"):
                    problemes.append("documentation.html : pas de lien vers « Comment ce site est construit »")
            # Page de suivi des données : rapport de ce build (data/suivi.json, provisoire) affiché.
            if (SITE / "suivi.html").exists():
                await pg.goto("http://localhost:8765/suivi.html")
                try:
                    await pg.wait_for_selector("#suivi[data-pret]", timeout=15000)
                    lignes = await pg.evaluate("document.querySelectorAll('.suivi-ligne').length")
                    etat = await pg.evaluate("document.getElementById('suivi-etat').textContent.trim()")
                    if lignes < 10:
                        problemes.append(f"suivi.html : {lignes} sources affichées seulement")
                    else:
                        print(f"{appareil} : page de suivi, {lignes} sources, état « {etat} »")
                except Exception:  # noqa: BLE001
                    problemes.append("suivi.html : la page de suivi ne se remplit pas")
            print(f"{appareil} : {'OK' if not problemes else str(len(problemes)) + ' problème(s)'}")
            navigateur[appareil] = {"ok": not problemes, "problemes": problemes[:10]}
            erreurs.extend(f"{appareil} : {x}" for x in problemes)
            await c.close()
        await b.close()


def ecrire_verification():
    """data/verification.json : contrôles, test navigateur, erreurs ; lu par pipeline/suivi.py."""
    (SITE / "data" / "verification.json").write_text(json.dumps({
        "le": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": not erreurs,
        "controles": controles, "navigateur": navigateur, "erreurs": erreurs[:50], "avertissements": avertissements[:50],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def verifier_icones():
    """Icône d'onglet (favicon) : fichiers présents et déclarés dans chaque page."""
    for nom in ("favicon.svg", "favicon.ico", "apple-touch-icon.png"):
        if not (SITE / nom).is_file() or (SITE / nom).stat().st_size == 0:
            erreurs.append(f"icône : {nom} manquant")
    for page in sorted(SITE.glob("*.html")):
        texte = page.read_text(encoding="utf-8")
        for attendu in ('href="favicon.svg"', 'href="favicon.ico"', 'rel="apple-touch-icon"'):
            if attendu not in texte:
                erreurs.append(f"icône : {page.name} ne déclare pas {attendu}")


def verifier_audience():
    """Mesure d'audience : le script GoatCounter est présent dans chaque page."""
    for page in sorted(SITE.glob("*.html")):
        if GOATCOUNTER not in page.read_text(encoding="utf-8"):
            erreurs.append(f"audience : {page.name} n'a pas le script GoatCounter")


def main():
    try:
        verifier_icones()
        verifier_audience()
        contenus = verifier_fichiers()

        class Silencieux(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        serveur = http.server.ThreadingHTTPServer(("localhost", 8765), functools.partial(Silencieux, directory=str(SITE)))
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        asyncio.run(verifier_navigateur(contenus))
        serveur.shutdown()
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"la vérification s'est arrêtée : {type(e).__name__}: {e}")
    finally:
        ecrire_verification()
    for a in avertissements:
        print(f"::warning::{a}")
    for e in erreurs:
        print(f"::error::{e}")
    print("Vérification : " + ("OK" if not erreurs else f"{len(erreurs)} problème(s) bloquant(s)"))
    sys.exit(1 if erreurs else 0)


if __name__ == "__main__":
    main()
