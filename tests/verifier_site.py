"""Vérifie le site construit avant de le publier. Échoue (code 1) si un problème bloquant est trouvé.

1. Les fichiers de données sont du JSON strict (pas de NaN) et contiennent des établissements,
   avec une couverture minimale de chaque indicateur (COUVERTURE_MINIMALE).
   Écoles : fichiers par département (data/ecoles/), au moins ECOLES_MINIMUM écoles et une
   couverture minimale de leurs indicateurs (COUVERTURE_ECOLES).
2. Le site, ouvert dans Chromium (ordinateur et téléphone), charge les calques des collèges,
   des lycées et des écoles, et les fiches d'un collège, d'un lycée et d'une école s'ouvrent avec
   leurs indicateurs (une fiche impossible à tester, faute d'établissement avec l'indicateur, est un
   échec) ; la fiche d'une école publique donne son collège de secteur, celle d'une école hors
   contrat l'explication de l'absence de données ; les écoles ne s'affichent qu'en zoomant.
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
import sys
import threading
from pathlib import Path

from playwright.async_api import async_playwright

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
erreurs, avertissements = [], []


COUVERTURE_MINIMALE = {
    "colleges.geojson": {"taux_reussite": 5300, "ips": 5400, "eval_fr": 5400},
    "lycees.geojson": {"gt_reussite": 1900, "pro_reussite": 1550, "ips": 2750},
}

# Écoles (jalon 7) : environ 80 % des effectifs attendus d'après le diagnostic du 14/11/2026
# (IPS : 29 070 écoles en 2024-2025 ; effectifs : 47 418 écoles à la rentrée 2025 ; taille des classes : 47 148).
ECOLES_MINIMUM = 40000
COUVERTURE_ECOLES = {"ips": 23000, "eleves": 36000, "classe": 36000}

# Part minimale de la surface attribuée au même collège que dans les secteurs officiels.
# Valeurs au 13/11/2026 : Paris 0,937, Hauts-de-Seine 0,923 ; 0,85 laisse environ 8 points de marge.
CONCORDANCE_MINIMALE = float(os.environ.get("SIMULER_CONCORDANCE") or 0.85)
DEPARTEMENTS_CONTROLE = ("Paris", "Hauts-de-Seine")


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
            if couverture[k] < mini:
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
        controle = (meta.get("secteurs") or {}).get("controle") or {}
        for dep in DEPARTEMENTS_CONTROLE:
            c = controle.get(dep)
            if not c or c.get("taux_surface") is None:
                avertissements.append(f"contrôle des secteurs impossible pour {dep} (secteurs officiels non téléchargés)")
                continue
            print(f"secteurs : {dep}, {c['taux_surface']:.1%} de la surface attribuée au même collège que les secteurs officiels")
            if c["taux_surface"] < CONCORDANCE_MINIMALE:
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
    sans_nom = sum(1 for f in points if not f["properties"].get("nom"))
    couverture = {k: sum(1 for f in points if isinstance(f["properties"].get(k), (int, float))) for k in COUVERTURE_ECOLES}
    print(f"écoles : {len(points)} dans {len(list(dossier.glob('*.geojson')))} départements, {sans_nom} sans nom ; couverture {couverture}")
    if len(points) < ECOLES_MINIMUM:
        erreurs.append(f"écoles : seulement {len(points)} (au moins {ECOLES_MINIMUM} attendues)")
    if sans_nom:
        erreurs.append(f"écoles : {sans_nom} sans nom")
    for k, mini in COUVERTURE_ECOLES.items():
        if couverture[k] < mini:
            erreurs.append(f"écoles : indicateur {k} présent pour {couverture[k]} écoles seulement (au moins {mini} attendues)")
    hc = sum(1 for f in points if f["properties"].get("contrat") == "hors")
    if hc < 500:
        avertissements.append(f"seulement {hc} écoles hors contrat repérées (annuaire de l'éducation indisponible ?)")


norm_dep = lambda d: str(int(d)) if str(d).isdigit() else str(d)


def ecole_a_tester(contenus, public=True):
    """Requête de recherche (nom et commune) d'une école à tester : publique avec IPS et taille des classes,
    dans un département qui a des secteurs (pour le collège de secteur), ou privée hors contrat."""
    index = contenus.get("index.json") or {}
    avec_secteurs = {norm_dep(d) for d, v in index.items() if v.get("zones")}
    # Paris d'abord : ses secteurs couvrent toute la ville, l'école a donc forcément un collège de secteur.
    for f in sorted(contenus.get("ecoles", []), key=lambda f: f["properties"].get("dep") != "75"):
        p = f["properties"]
        if public and p.get("secteur") == "public" and "ips" in p and "classe" in p and norm_dep(p["dep"]) in avec_secteurs:
            return f"{p['nom']} {p['commune']}", p
        if not public and p.get("contrat") == "hors":
            return f"{p['nom']} {p['commune']}", p
    return None, None


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


async def ouvrir_fiche(pg, nom, attendu, selecteur="#fiche-contenu .onglets button", attente=1200, interdit=None):
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
    if attendu not in texte:
        return f"la fiche « {nom} » ne contient pas « {attendu} » : {texte[:200]!r}"
    if interdit and interdit in texte:
        return f"la fiche « {nom} » contient « {interdit} » : {texte[:300]!r}"
    await pg.click("#fermer")
    return None


async def verifier_navigateur(contenus):
    college = exemple(contenus, "colleges.geojson", "taux_reussite")
    lycee = exemple(contenus, "lycees.geojson", "ips")
    hors_contrat = next((f["properties"]["nom"] for f in contenus.get("colleges.geojson", {}).get("features", [])
                         if f["properties"].get("sans_brevet") == "hors_contrat"), None)
    college_secteur, fichier_secteur = college_hors_idf(contenus)
    ecole, _ = ecole_a_tester(contenus)
    ecole_hc, _ = ecole_a_tester(contenus, public=False)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for appareil, ctx in (("ordinateur", {"viewport": {"width": 1280, "height": 800}}), ("téléphone", p.devices["iPhone 13"])):
            c = await b.new_context(**ctx)
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
                ecoles_rendues = await pg.evaluate("window.carteScolaire.getLayer('ecoles') ? window.carteScolaire.queryRenderedFeatures({layers: ['ecoles']}).length : -1")
                texte_indice = await pg.inner_text("#indice-secteurs")
                if ecoles_rendues != 0 or "écoles" not in texte_indice:
                    problemes.append(f"vue nationale : calque des écoles {'absent' if ecoles_rendues < 0 else f'avec {ecoles_rendues} écoles affichées'}, "
                                     f"indication « {texte_indice} »")
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
                pb = await ouvrir_fiche(pg, ecole, "Collège de secteur", attente=3000, interdit="Non disponible")
                if pb:
                    problemes.append(pb)
                await pg.wait_for_timeout(1500)
                n = await pg.evaluate("window.carteScolaire.queryRenderedFeatures({layers: ['ecoles']}).length")
                if n == 0:
                    problemes.append(f"aucune école affichée après avoir ouvert la fiche « {ecole} » (zoom {await pg.evaluate('window.carteScolaire.getZoom()'):.1f})")
                else:
                    print(f"{appareil} : fiche école « {ecole} » ouverte, {n} écoles à l'écran")
            else:
                problemes.append("aucune école publique avec IPS et taille des classes dans un département à secteurs : fiche école non testée")
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
            # Pages de documentation : chargement sans erreur, données de meta.json affichées.
            for page in sorted(SITE.glob("documentation*.html")):
                await pg.goto(f"http://localhost:8765/{page.name}")
                await pg.wait_for_timeout(800)
                for sel, vide in (("#liste-sources", "Chargement"), ("#resume-donnees", "Chargement")):
                    el = await pg.query_selector(sel)
                    if el and (vide in await el.inner_text() or "pas pu" in await el.inner_text()):
                        problemes.append(f"{page.name} : {sel} n'est pas rempli")
            print(f"{appareil} : {'OK' if not problemes else str(len(problemes)) + ' problème(s)'}")
            erreurs.extend(f"{appareil} : {x}" for x in problemes)
            await c.close()
        await b.close()


def main():
    contenus = verifier_fichiers()
    class Silencieux(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    serveur = http.server.ThreadingHTTPServer(("localhost", 8765), functools.partial(Silencieux, directory=str(SITE)))
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    asyncio.run(verifier_navigateur(contenus))
    serveur.shutdown()
    for a in avertissements:
        print(f"::warning::{a}")
    for e in erreurs:
        print(f"::error::{e}")
    print("Vérification : " + ("OK" if not erreurs else f"{len(erreurs)} problème(s) bloquant(s)"))
    sys.exit(1 if erreurs else 0)


if __name__ == "__main__":
    main()
