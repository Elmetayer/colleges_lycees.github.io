"""Vérifie le site construit avant de le publier. Échoue (code 1) si un problème bloquant est trouvé.

1. Les fichiers de données sont du JSON strict (pas de NaN) et contiennent des établissements.
2. Le site, ouvert dans Chromium (ordinateur et téléphone), charge les calques des collèges
   et des lycées, et les fiches d'un collège et d'un lycée s'ouvrent avec leurs indicateurs.

Usage : python tests/verifier_site.py site   (le dossier site doit déjà contenir data/)
Les secteurs absents ne bloquent pas : ils sont signalés en avertissement.
"""
import asyncio
import functools
import http.server
import json
import sys
import threading
from pathlib import Path

from playwright.async_api import async_playwright

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
erreurs, avertissements = [], []


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
    index = contenus.get("index.json")
    if not index:
        avertissements.append("secteurs/index.json absent : la carte sera publiée sans secteurs")
    else:
        print(f"secteurs : {len(index)} départements")
        vides = [d for d, v in index.items() if not v.get("zones")]
        if vides:
            avertissements.append(f"départements sans aucune zone : {vides}")
    return contenus


norm_dep = lambda d: str(int(d)) if str(d).isdigit() else str(d)


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


async def ouvrir_fiche(pg, nom, attendu):
    await pg.fill("#recherche", nom)
    await pg.wait_for_timeout(1200)
    await pg.keyboard.press("ArrowDown")
    await pg.keyboard.press("Enter")
    try:
        await pg.wait_for_selector("#fiche-contenu .onglets button", timeout=10000)
    except Exception:  # noqa: BLE001
        texte = (await pg.inner_text("#fiche-contenu")) if await pg.query_selector("#fiche-contenu") else ""
        return f"la fiche « {nom} » n'affiche pas d'indicateurs : {texte[:200]!r}"
    texte = await pg.inner_text("#fiche-contenu")
    if attendu not in texte:
        return f"la fiche « {nom} » ne contient pas « {attendu} » : {texte[:200]!r}"
    await pg.click("#fermer")
    return None


async def verifier_navigateur(contenus):
    college = exemple(contenus, "colleges.geojson", "taux_reussite")
    lycee = exemple(contenus, "lycees.geojson", "ips")
    college_secteur, fichier_secteur = college_hors_idf(contenus)
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
            panneau = await pg.inner_text("#panneau")
            if "Données indisponibles" in panneau:
                problemes.append("un calque affiche « Données indisponibles »")
            for nom, attendu in ((college, "brevet"), (lycee, "IPS")):
                if nom:
                    pb = await ouvrir_fiche(pg, nom, attendu)
                    if pb:
                        problemes.append(pb)
            # Secteurs chargés à la demande : au démarrage (vue nationale) aucun département n'est chargé ;
            # après avoir zoomé sur un collège hors Île-de-France, celui de son département doit l'être.
            if college_secteur:
                pb = await ouvrir_fiche(pg, college_secteur, "brevet")
                if pb:
                    problemes.append(pb)
                await pg.wait_for_timeout(3000)
                charges = [u for u in secteurs_charges if f"/data/secteurs/{fichier_secteur}.geojson" in u]
                if charges:
                    print(f"{appareil} : secteurs du département {fichier_secteur} chargés en zoomant sur « {college_secteur} » ; "
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
