"""Calque Transports : lignes de métro, tram, RER, Transilien et trains de banlieue, gares et stations (OpenStreetMap).

Option A choisie par Bruno le 18/11/2026 : lignes urbaines à leurs couleurs (métro, tram, tram-train, funiculaires
urbains, RER, Transilien, Léman Express) et toutes les gares en points ; au clic, une gare ou une station donne les
lignes qui la desservent (TER compris). Diagnostic préalable : branche diag-transports.

Source : extrait France de Geofabrik (download.geofabrik.de, mis à jour chaque jour), filtré par osmium dans le job
« transports » du workflow. Licence ODbL (© contributeurs OpenStreetMap). L'extrait (4,8 Go) met une vingtaine de
minutes à se télécharger : il n'est repris que si les données gardées en cache ont plus de AGE_MAX_JOURS jours ;
l'extrait filtré (environ 15 Mo) est gardé en cache pour recalculer sans retélécharger quand la méthode change
(VERSION_CALCUL).

Commandes :
  python pipeline/transports.py age --entree transports-out          # faut-il retélécharger, recalculer ?
  python pipeline/transports.py calculer --pbf filtre.osm.pbf --sortie transports-out
  python pipeline/transports.py assembler --entree transports-out --out site/data
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VERSION_CALCUL = 2  # 2 : un TER marqué « commuter » reste un TER (non dessiné)
AGE_MAX_JOURS = 25
PAGE_SOURCE = "https://download.geofabrik.de/europe/france.html"
# Contours des départements (Etalab, découpage administratif) pour couper les lignes à la frontière.
CONTOURS = [f"https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/{a}/geojson/departements-100m.geojson"
            for a in (2026, 2025, 2024, 2023)]
BBOX = (-5.5, 41.3, 9.7, 51.2)  # France métropolitaine, Corse comprise (l'extrait contient aussi l'outre-mer)
TOL = 0.0001                    # simplification des tracés, environ 10 m
MARGE_FRONTIERE = 0.003         # environ 300 m : une gare frontalière (Annemasse, Saint-Louis) reste dedans
ROUTES = {"subway", "monorail", "light_rail", "tram", "train", "funicular"}
# Lignes dessinées sur la carte (option A). Les TER ne sont pas dessinés : ils figurent dans la fiche des gares.
DESSINEES = ["metro", "rer", "transilien", "tram", "tram-train", "banlieue", "funiculaire"]
TOURISTIQUE = re.compile(r"touristi|historique|petit train|horse|hippomobile|paradiski|fun arc|vapeur|chemin de fer de|musée", re.I)
# Minimums de vraisemblance (diagnostic du 18/11/2026 : 32 lignes de métro, 111 de tram, 2 252 gares et 1 038 haltes).
MINIMUMS = {"metro": 25, "tram": 80, "rer": 5, "gares": 2000}
COULEURS_NOMMEES = {"red": "#e3051b", "blue": "#0055a4", "green": "#00a650", "yellow": "#ffcd00", "orange": "#f28e00",
                    "purple": "#8c4799", "brown": "#8d5e2a", "pink": "#f49fc8", "grey": "#8a8a8a", "gray": "#8a8a8a",
                    "black": "#222222", "darkblue": "#003a80", "lightblue": "#6ec4e8", "darkgreen": "#006a3b"}


def log(msg: str) -> None:
    print(msg, flush=True)


def couleur(v: str | None) -> str | None:
    v = (v or "").strip().lower()
    if re.fullmatch(r"#?[0-9a-f]{6}", v):
        return "#" + v.lstrip("#")
    if re.fullmatch(r"#?[0-9a-f]{3}", v):
        return "#" + "".join(c * 2 for c in v.lstrip("#"))
    return COULEURS_NOMMEES.get(v)


def norm(s: str | None) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(gare|station|de|du|des|la|le|les|d|l|sncf)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def dans_bbox(lon: float, lat: float) -> bool:
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def categorie(t: dict) -> str:
    """Catégorie d'affichage d'une ligne d'après ses attributs OSM."""
    route = t.get("route")
    if route in ("subway", "monorail"):
        return "metro"
    if route == "tram":
        return "tram"
    if route == "light_rail":
        return "tram-train"
    if route == "funicular":
        return "funiculaire"
    texte = f"{t.get('network', '')} {t.get('name', '')}"
    if re.search(r"\bRER\b", texte):
        return "rer"
    if "Transilien" in texte:
        return "transilien"
    service = (t.get("service") or "").split(";")[0]
    if service == "commuter" and not re.search(r"\bTER\b", texte):
        return "banlieue"  # Léman Express ; un TER marqué « commuter » reste un TER
    if service in ("tourism", "touristic"):
        return "touristique"
    if service in ("high_speed", "long_distance", "national", "international", "night", "car_shuttle"):
        return "grande-ligne"
    return "regional"  # TER et trains sans service précisé


def touristique(t: dict, cat: str) -> bool:
    """Lignes à écarter : touristiques, historiques, en projet ou fermées, remontées de stations de ski, lignes urbaines sans réseau."""
    if cat == "touristique" or t.get("usage") == "tourism":
        return True
    if t.get("state") in ("proposed", "construction", "disused", "abandoned"):  # lignes en projet ou fermées
        return True
    if TOURISTIQUE.search(f"{t.get('network', '')} {t.get('name', '')} {t.get('operator', '')}"):
        return True
    if cat in ("metro", "tram", "tram-train") and not t.get("network"):
        return True
    return cat == "funiculaire" and not couleur(t.get("colour"))


# ---------------------------------------------------------------- lecture de l'extrait OSM

def lire_pbf(chemin: str):
    import osmium

    class Lecteur(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways, self.points, self.arrets = {}, [], {}
            self.routes, self.masters = {}, {}

        def _point(self, tags, lon, lat, oid):
            rw, pt = tags.get("railway"), tags.get("public_transport")
            if rw in ("station", "halt", "tram_stop") or pt == "station":
                self.points.append({"id": oid, "lon": lon, "lat": lat, "tags": dict(tags)})

        def node(self, n):
            if not n.location.valid() or not len(n.tags):
                return
            lon, lat = n.location.lon, n.location.lat
            self._point(n.tags, lon, lat, f"n{n.id}")
            if n.tags.get("public_transport") in ("stop_position", "platform") or n.tags.get("railway") in ("stop", "halt", "station", "tram_stop"):
                self.arrets[n.id] = (lon, lat, n.tags.get("name"))

        def way(self, w):
            pts = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
            if len(pts) >= 2:
                self.ways[w.id] = pts
            if pts and len(w.tags):
                self._point(w.tags, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), f"w{w.id}")

        def relation(self, r):
            t = dict(r.tags)
            if t.get("type") == "route" and t.get("route") in ROUTES:
                self.routes[r.id] = {
                    "tags": t,
                    "ways": [m.ref for m in r.members if m.type == "w" and m.role in ("", "forward", "backward", "route")],
                    "arrets": [m.ref for m in r.members if m.type == "n" and (m.role.startswith("stop") or m.role.startswith("platform"))],
                }
            elif t.get("type") == "route_master" and t.get("route_master") in ROUTES:
                self.masters[r.id] = {"tags": t, "routes": [m.ref for m in r.members if m.type == "r"]}

    L = Lecteur()
    L.apply_file(chemin, locations=True, idx="flex_mem")
    date = None
    try:
        h = osmium.io.Reader(chemin, osmium.osm.osm_entity_bits.NOTHING).header()
        date = h.get("osmosis_replication_timestamp") or h.get("timestamp")
    except Exception:  # noqa: BLE001
        pass
    log(f"  lu : {len(L.ways)} voies, {len(L.routes)} itinéraires, {len(L.masters)} lignes (route_master), "
        f"{len(L.points)} gares et arrêts, {len(L.arrets)} positions d'arrêt ; données OSM du {date}")
    return L, date


# ---------------------------------------------------------------- frontière

def frontiere():
    """Polygone de la France métropolitaine (réunion des départements, Etalab), élargi de MARGE_FRONTIERE."""
    import requests
    from shapely.geometry import shape
    from shapely.ops import unary_union
    for url in CONTOURS:
        try:
            r = requests.get(url, timeout=120)
            if r.status_code != 200:
                log(f"  contours : {url} → HTTP {r.status_code}")
                continue
            feats = r.json()["features"]
            geoms = [shape(f["geometry"]) for f in feats if not str(f["properties"].get("code", "")).startswith("97")]
            if len(geoms) < 90:
                log(f"  contours : {url} → {len(geoms)} départements seulement")
                continue
            poly = unary_union([g.buffer(0) for g in geoms]).buffer(MARGE_FRONTIERE)
            log(f"  contours : {len(geoms)} départements ({url})")
            return poly, url
        except Exception as exc:  # noqa: BLE001
            log(f"  contours : {url} → {exc!r}")
    return None, None


# ---------------------------------------------------------------- calcul

def calculer(pbf: str, sortie: Path) -> dict:
    from shapely.geometry import MultiLineString, Point, mapping
    from shapely.ops import linemerge
    from shapely.prepared import prep

    L, date_osm = lire_pbf(pbf)
    france, url_contours = frontiere()
    pfrance = prep(france) if france is not None else None

    def en_france(lon, lat):
        return dans_bbox(lon, lat) and (pfrance is None or pfrance.contains(Point(lon, lat)))

    # Itinéraires (un par sens, parfois par branche) regroupés en lignes : route_master, sinon réseau + numéro.
    master_de = {rid: mid for mid, m in L.masters.items() for rid in m["routes"]}
    groupes = collections.defaultdict(lambda: {"routes": [], "ways": set(), "arrets": set(), "master": None})
    for rid, r in L.routes.items():
        t = r["tags"]
        cle = ("m", master_de[rid]) if rid in master_de else (
            "r", t.get("route"), t.get("network") or t.get("operator") or "", t.get("ref") or t.get("name") or str(rid))
        g = groupes[cle]
        g["routes"].append(t)
        g["ways"].update(r["ways"])
        g["arrets"].update(r["arrets"])
        if cle[0] == "m":
            g["master"] = L.masters[cle[1]]["tags"]

    lignes, compte = [], collections.Counter()
    for g in groupes.values():
        t0, tm = g["routes"][0], g["master"] or {}
        t = {k: tm.get(k) or t0.get(k) for k in ("route", "ref", "name", "network", "operator", "usage", "state")}
        t["service"] = next((r.get("service") for r in g["routes"] if r.get("service")), None)
        t["colour"] = tm.get("colour") or next((r.get("colour") for r in g["routes"] if r.get("colour")), None)
        cat = categorie(t)
        arrets = [L.arrets[a] for a in g["arrets"] if a in L.arrets]
        segs = [L.ways[w] for w in g["ways"] if w in L.ways]
        pts = [p for s in segs for p in s] or [(a[0], a[1]) for a in arrets]
        if not pts or sum(1 for p in pts if dans_bbox(*p)) / len(pts) < 0.3:
            compte["hors_metropole"] += 1
            continue
        if touristique(t, cat):
            compte["touristiques"] += 1
            continue
        geo = None
        if cat in DESSINEES and segs:
            geo = linemerge(MultiLineString(segs))
            if france is not None:
                avant = geo.length
                geo = geo.intersection(france)
                if geo.is_empty or geo.length < 0.002:
                    compte["hors_france"] += 1
                    continue
                if geo.length < avant * 0.999:
                    compte["coupees_frontiere"] += 1
            geo = geo.simplify(TOL, preserve_topology=False)
        lignes.append({"cat": cat, "ref": t.get("ref"), "nom": t.get("name"), "reseau": t.get("network"),
                       "couleur": couleur(t.get("colour")), "geo": geo, "arrets": arrets})

    # Gares, stations et arrêts : un point par type et par nom (à moins de 300 m environ).
    def type_point(t):
        rw, st = t.get("railway"), t.get("station")
        if rw == "tram_stop" or st == "tram" or (t.get("tram") == "yes" and t.get("train") != "yes" and st not in ("subway", "light_rail")):
            return "tram"
        if st in ("subway", "monorail") or (t.get("subway") == "yes" and t.get("train") != "yes"):
            return "metro"
        if st == "light_rail" or (t.get("light_rail") == "yes" and t.get("train") != "yes"):
            return "tram-train"
        if st == "funicular":
            return "funiculaire"
        if rw == "halt":
            return "halte"
        if rw == "station" or st == "train" or t.get("train") == "yes":
            return "gare"
        return None  # gares routières, remontées mécaniques…

    vus, retenus = {}, collections.Counter()
    for p in L.points:
        t = p["tags"]
        typ = type_point(t)
        if not typ or not t.get("name") or not en_france(p["lon"], p["lat"]):
            continue
        if any(k.startswith(("disused", "abandoned", "construction", "proposed", "razed")) for k in t) or t.get("usage") == "tourism":
            continue
        retenus[typ] += 1
        cle = (typ, norm(t["name"]), round(p["lat"] / 0.003), round(p["lon"] / 0.004))
        if cle not in vus:
            vus[cle] = {"type": typ, "nom": t["name"], "lon": p["lon"], "lat": p["lat"], "lignes": {}}
    gares = list(vus.values())

    # Lignes de chaque gare : arrêts des itinéraires à moins de 300 m (trains) ou 150 m (métro, tram), même famille.
    FAMILLES = {"metro": {"metro"}, "tram": {"tram", "tram-train"}, "tram-train": {"tram-train", "gare", "halte", "tram"},
                "funiculaire": {"funiculaire"}}
    grille = collections.defaultdict(list)
    for i, gp in enumerate(gares):
        grille[(int(gp["lon"] / 0.01), int(gp["lat"] / 0.01))].append(i)
    ORDRE = {c: i for i, c in enumerate(["metro", "rer", "transilien", "tram", "tram-train", "banlieue", "funiculaire", "regional", "grande-ligne"])}
    for k, li in enumerate(lignes):
        familles = FAMILLES.get(li["cat"], {"gare", "halte", "tram-train"})
        rayon = 0.0015 if li["cat"] in ("metro", "tram", "funiculaire") else 0.003
        for lon, lat, nom in li["arrets"]:
            meilleur = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in grille.get((int(lon / 0.01) + dx, int(lat / 0.01) + dy), []):
                        gp = gares[i]
                        if gp["type"] not in familles:
                            continue
                        d = math.hypot((gp["lon"] - lon) * 0.69, gp["lat"] - lat)
                        if d <= rayon and (meilleur is None or d < meilleur[0]):
                            meilleur = (d, i)
            if meilleur:
                gares[meilleur[1]]["lignes"][k] = True

    def badge(li):
        if li["cat"] == "grande-ligne":
            texte = f"{li['reseau'] or ''} {li['nom'] or ''}"
            if re.search(r"ouigo", texte, re.I):
                return ("Ouigo", None, "Ouigo")
            if re.search(r"tgv|inoui|lyria|eurostar|frecciarossa|ice\b", texte, re.I):
                return ("TGV", None, "TGV")
            if re.search(r"intercit|\bIC\b", texte, re.I):
                return ("Intercités", None, "Intercités")
            return None
        ref = (li["ref"] or "").strip() or (li["nom"] or "").split(":")[0].strip()
        if not ref:
            return None
        return (ref[:16], li["couleur"], (li["nom"] or ref)[:90])

    feats_gares = []
    for gp in gares:
        vus_b, badges = set(), []
        for k in sorted(gp["lignes"], key=lambda k: (ORDRE.get(lignes[k]["cat"], 99), lignes[k]["ref"] or "")):
            b = badge(lignes[k])
            if b and (b[0], b[2]) not in vus_b:
                vus_b.add((b[0], b[2]))
                badges.append(b)
        props = {"type": gp["type"], "nom": gp["nom"]}
        if badges:
            props["lignes"] = ";".join(f"{a}~{c or ''}~{t}".replace(";", ",") for a, c, t in badges[:16])
        feats_gares.append({"type": "Feature", "properties": props,
                            "geometry": {"type": "Point", "coordinates": [round(gp["lon"], 5), round(gp["lat"], 5)]}})

    feats_lignes = [{"type": "Feature", "properties": {k: li[k] for k in ("cat", "ref", "nom", "reseau", "couleur") if li[k]},
                     "geometry": mapping(li["geo"])} for li in lignes if li["geo"] is not None and not li["geo"].is_empty]

    par_cat = collections.Counter(li["cat"] for li in lignes)
    dessinees = collections.Counter(f["properties"]["cat"] for f in feats_lignes)
    types = collections.Counter(f["properties"]["type"] for f in feats_gares)
    refs = lambda motif: sorted({li["ref"] or "?" for li in lignes if li["cat"] == "metro" and re.search(motif, f"{li['reseau']} {li['nom']}", re.I)})
    bilan = {
        "version": VERSION_CALCUL,
        "donnees_osm": date_osm,
        "calcule_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": PAGE_SOURCE,
        "frontiere": url_contours,
        "lignes": dict(dessinees),
        "lignes_total": sum(dessinees.values()),
        "lignes_avec_couleur": sum(1 for f in feats_lignes if f["properties"].get("couleur")),
        "lignes_osm": dict(par_cat),
        "ecartees": dict(compte),
        "gares": dict(types),
        "gares_avec_lignes": sum(1 for f in feats_gares if f["properties"].get("lignes") and f["properties"]["type"] in ("gare", "halte")),
        "objets_retenus": dict(retenus),
        "metro": {"Paris": refs(r"paris|ratp"), "Lyon": refs(r"lyon|tcl"), "Marseille": refs(r"marseille|rtm"),
                  "Lille": refs(r"lille|il[ée]via"), "Toulouse": refs(r"toulouse|tiss[ée]o"), "Rennes": refs(r"rennes|star")},
        "rer": sorted({li["ref"] or "?" for li in lignes if li["cat"] == "rer"}),
    }
    manque = [k for k, mini in MINIMUMS.items()
              if (dessinees.get(k, 0) if k != "gares" else types.get("gare", 0)) < mini]
    if manque and not os.environ.get("TRANSPORTS_SANS_MINIMUM"):  # variable pour les tests locaux sur un petit extrait
        raise SystemExit(f"résultat invraisemblable ({', '.join(f'{k} {dessinees.get(k, types.get(k, 0))} < {MINIMUMS[k]}' for k in manque)}) : "
                         "les données précédentes sont gardées")

    sortie.mkdir(parents=True, exist_ok=True)
    def ecrire(nom, feats):
        txt = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":"))
        txt = re.sub(r"(\d+\.\d{5})\d+", r"\1", txt)
        (sortie / nom).write_text(txt, encoding="utf-8")
        return round(len(txt.encode()) / 1e6, 2)
    bilan["taille_mo"] = {"lignes": ecrire("lignes.geojson", feats_lignes), "gares": ecrire("gares.geojson", feats_gares)}
    (sortie / "bilan.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")
    log(json.dumps(bilan, ensure_ascii=False, indent=1))
    return bilan


# ---------------------------------------------------------------- commandes

def lire_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def age_jours(iso: str | None) -> float | None:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d).total_seconds() / 86400
    except ValueError:
        return None


def cmd_age(args) -> int:
    """Écrit dans $GITHUB_OUTPUT : telecharger=1 si les données OSM manquent ou ont plus de AGE_MAX_JOURS jours ;
    recalculer=1 s'il faut refaire le calcul (téléchargement, ou méthode changée avec l'extrait filtré en cache)."""
    entree = Path(args.entree)
    bilan = lire_json(entree / "bilan.json") or {}
    age = age_jours(bilan.get("donnees_osm"))
    filtre = (entree / "filtre.osm.pbf").exists()
    telecharger = (not filtre) or age is None or age > AGE_MAX_JOURS or bool(os.environ.get("FORCER_TRANSPORTS"))
    recalculer = telecharger or bilan.get("version") != VERSION_CALCUL or not (entree / "lignes.geojson").exists()
    log(f"données OSM en cache : {bilan.get('donnees_osm')} ({'—' if age is None else f'{age:.0f} jours'}), "
        f"version {bilan.get('version')} (actuelle {VERSION_CALCUL}), extrait filtré {'présent' if filtre else 'absent'} "
        f"→ télécharger {int(telecharger)}, recalculer {int(recalculer)}")
    # État du passage, complété par « calculer » ; lu par « assembler » (version reprise ou non).
    entree.mkdir(parents=True, exist_ok=True)
    (entree / "passage.json").write_text(json.dumps({"telechargement": "a_faire" if telecharger else "non_necessaire",
                                                     "calcul": "a_faire" if recalculer else "non_necessaire"}), encoding="utf-8")
    sortie = os.environ.get("GITHUB_OUTPUT")
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            f.write(f"telecharger={int(telecharger)}\nrecalculer={int(recalculer)}\n")
    return 0


def cmd_calculer(args) -> int:
    """Calcule dans un dossier temporaire et ne remplace la sortie qu'en cas de succès."""
    sortie = Path(args.sortie)
    passage = {"telechargement": args.telechargement, "calcul": "echec"}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            calculer(args.pbf, Path(tmp))
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            log(f"! calcul des transports en échec : {exc}")
            sortie.mkdir(parents=True, exist_ok=True)
            (sortie / "passage.json").write_text(json.dumps(passage, ensure_ascii=False), encoding="utf-8")
            return 1
        sortie.mkdir(parents=True, exist_ok=True)
        for nom in ("lignes.geojson", "gares.geojson", "bilan.json"):
            shutil.copy(Path(tmp) / nom, sortie / nom)
    if Path(args.pbf).resolve() != (sortie / "filtre.osm.pbf").resolve():
        shutil.copy(args.pbf, sortie / "filtre.osm.pbf")
    passage["calcul"] = "ok"
    (sortie / "passage.json").write_text(json.dumps(passage, ensure_ascii=False), encoding="utf-8")
    return 0


def cmd_assembler(args) -> int:
    """Copie lignes et gares dans site/data/transports/ et ajoute le bloc « transports » à meta.json."""
    entree, out = Path(args.entree), Path(args.out)
    meta_p = out / "meta.json"
    meta = lire_json(meta_p) or {}
    bilan = lire_json(entree / "bilan.json")
    passage = lire_json(entree / "passage.json") or {}
    if not bilan or not (entree / "lignes.geojson").exists() or not (entree / "gares.geojson").exists():
        meta["transports"] = None
        meta.setdefault("problemes", []).append("transports : aucune donnée (téléchargement ou calcul en échec, rien en cache)")
        log("! transports absents")
    else:
        (out / "transports").mkdir(parents=True, exist_ok=True)
        for nom in ("lignes.geojson", "gares.geojson"):
            shutil.copy(entree / nom, out / "transports" / nom)
        meta["transports"] = {k: bilan.get(k) for k in ("donnees_osm", "calcule_le", "source", "frontiere", "lignes", "lignes_total",
                                                       "lignes_avec_couleur", "gares", "gares_avec_lignes", "ecartees", "metro", "rer", "taille_mo", "version")}
        meta["transports"]["passage"] = passage or {"telechargement": "non_necessaire", "calcul": "non_necessaire"}
        # Version précédente gardée : téléchargement ou calcul de ce passage en échec.
        meta["transports"]["reprise"] = passage.get("telechargement") == "echec" or passage.get("calcul") in ("echec", "a_faire")
        meta.setdefault("sources", []).append({"cle": "osm_transports", "titre": "Lignes, gares et stations de transport (OpenStreetMap, extrait Geofabrik), ODbL",
                                               "page": PAGE_SOURCE, "mise_a_jour": (bilan.get("donnees_osm") or "")[:10] or None})
        if not bilan.get("frontiere"):
            meta.setdefault("problemes", []).append("transports : contours des départements injoignables, lignes non coupées à la frontière")
        log(f"transports : {bilan.get('lignes_total')} lignes, {sum((bilan.get('gares') or {}).values())} gares et arrêts, données OSM du {bilan.get('donnees_osm')}")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = ap.add_subparsers(dest="cmd", required=True)
    a = sous.add_parser("age")
    a.add_argument("--entree", default="transports-out")
    c = sous.add_parser("calculer")
    c.add_argument("--pbf", required=True)
    c.add_argument("--sortie", default="transports-out")
    c.add_argument("--telechargement", default="ok", help="ok | echec | non_necessaire (consigné dans passage.json)")
    s = sous.add_parser("assembler")
    s.add_argument("--entree", default="transports-out")
    s.add_argument("--out", default="site/data")
    args = ap.parse_args()
    return {"age": cmd_age, "calculer": cmd_calculer, "assembler": cmd_assembler}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
