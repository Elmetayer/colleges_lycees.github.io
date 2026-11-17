"""Diagnostic du calque Transports (temporaire, branche diag-transports).

Entrée : extrait OSM filtré (lignes ferrées de voyageurs, gares, arrêts de tram), produit par
osmium tags-filter dans le workflow. Sortie : chiffres dans le journal, diag/resultats/transports.json,
et deux fichiers d'essai (lignes du périmètre 2, gares) pour mesurer le poids et faire un aperçu.

Usage : python diag/transports.py filtre.osm.pbf diag/resultats
"""
import collections
import gzip
import json
import math
import os
import re
import sys
import unicodedata

import osmium
from shapely.geometry import LineString, MultiLineString, mapping
from shapely.ops import linemerge

# France métropolitaine, Corse comprise (l'extrait Geofabrik contient aussi l'outre-mer).
BBOX = (-5.5, 41.3, 9.7, 51.2)
TOL = 0.0001  # simplification ≈ 10 m
LIGNES_ROUTES = {"subway", "monorail", "light_rail", "tram", "train", "funicular"}


def dans_metropole(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(gare|station|de|du|des|la|le|les|d|sncf)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class Lecteur(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = {}
        self.points = []  # gares, stations, arrêts de tram
        self.routes = {}
        self.masters = {}

    def _point(self, tags, lon, lat, typ, oid):
        rw, pt = tags.get("railway"), tags.get("public_transport")
        if rw in ("station", "halt", "tram_stop") or pt == "station":
            self.points.append({"id": f"{typ}{oid}", "lon": lon, "lat": lat, "tags": dict(tags)})

    def node(self, n):
        if n.location.valid() and len(n.tags):
            self._point(n.tags, n.location.lon, n.location.lat, "n", n.id)

    def way(self, w):
        pts = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
        if len(pts) >= 2:
            self.ways[w.id] = pts
        if pts and len(w.tags):
            lon = sum(p[0] for p in pts) / len(pts)
            lat = sum(p[1] for p in pts) / len(pts)
            self._point(w.tags, lon, lat, "w", w.id)

    def relation(self, r):
        t = dict(r.tags)
        if t.get("type") == "route" and t.get("route") in LIGNES_ROUTES:
            ways = [m.ref for m in r.members if m.type == "w" and m.role in ("", "forward", "backward", "route")]
            self.routes[r.id] = {"tags": t, "ways": ways}
        elif t.get("type") == "route_master" and t.get("route_master") in LIGNES_ROUTES:
            self.masters[r.id] = {"tags": t, "routes": [m.ref for m in r.members if m.type == "r"]}
        elif t.get("public_transport") == "station" or t.get("railway") == "station":
            pass  # zones de gare en relation : comptées par leurs nœuds


def categorie(t):
    route = t.get("route") or t.get("route_master")
    if route in ("subway", "monorail"):
        return "metro"
    if route in ("light_rail", "tram", "funicular"):
        return route
    net = f"{t.get('network', '')} {t.get('name', '')}"
    if re.search(r"\bRER\b", net):
        return "train-rer"
    if "Transilien" in net:
        return "train-transilien"
    return "train-" + (t.get("service") or "sans-service")


PERIMETRE2 = {"metro", "light_rail", "tram", "funicular", "train-rer", "train-transilien", "train-commuter"}


def main(entree, sortie):
    os.makedirs(sortie, exist_ok=True)
    L = Lecteur()
    L.apply_file(entree, locations=True, idx="flex_mem")
    print(f"Lu : {len(L.ways)} voies, {len(L.routes)} itinéraires, {len(L.masters)} lignes (route_master), {len(L.points)} points", flush=True)

    # Regroupement des itinéraires (sens aller / retour) en lignes.
    master_de = {}
    for mid, m in L.masters.items():
        for rid in m["routes"]:
            master_de[rid] = mid
    groupes = collections.defaultdict(lambda: {"routes": [], "ways": set(), "tags": None})
    for rid, r in L.routes.items():
        t = r["tags"]
        if rid in master_de:
            cle = ("m", master_de[rid])
        else:
            cle = ("r", t.get("route"), t.get("network") or t.get("operator") or "", t.get("ref") or t.get("name") or str(rid))
        g = groupes[cle]
        g["routes"].append(t)
        g["ways"].update(r["ways"])
        if cle[0] == "m":
            g["tags"] = L.masters[cle[1]]["tags"]

    lignes = []
    sans_geo = 0
    hors = 0
    for cle, g in groupes.items():
        t0 = g["routes"][0]
        tm = g["tags"] or {}
        tags = {
            "route": t0.get("route"),
            "ref": tm.get("ref") or t0.get("ref"),
            "name": tm.get("name") or t0.get("name"),
            "network": tm.get("network") or t0.get("network"),
            "operator": tm.get("operator") or t0.get("operator"),
            "service": next((r.get("service") for r in g["routes"] if r.get("service")), None),
            "colour": tm.get("colour") or next((r.get("colour") for r in g["routes"] if r.get("colour")), None),
        }
        segs = [L.ways[w] for w in g["ways"] if w in L.ways]
        if not segs:
            sans_geo += 1
            continue
        pts = [p for s in segs for p in s]
        dedans = sum(1 for p in pts if dans_metropole(*p)) / len(pts)
        if dedans < 0.5:
            hors += 1
            continue
        geo = linemerge(MultiLineString(segs))
        tags["categorie"] = categorie({**t0, **{k: v for k, v in tags.items() if v}})
        tags["morceaux"] = 1 if geo.geom_type == "LineString" else len(geo.geoms)
        tags["km"] = round(geo.length * 111 * math.cos(math.radians(46.5)), 1)
        tags["itineraires"] = len(g["routes"])
        lignes.append((tags, geo))
    print(f"Lignes : {len(lignes)} en métropole, {hors} hors métropole, {sans_geo} sans géométrie", flush=True)

    # Statistiques par catégorie.
    stats = {}
    par_cat = collections.defaultdict(list)
    for t, g in lignes:
        par_cat[t["categorie"]].append((t, g))
    for cat, ls in sorted(par_cat.items()):
        n = len(ls)
        reseaux = collections.Counter(t["network"] or "(aucun)" for t, _ in ls)
        stats[cat] = {
            "lignes": n,
            "km": round(sum(t["km"] for t, _ in ls)),
            "avec_couleur": sum(1 for t, _ in ls if t["colour"]),
            "avec_ref": sum(1 for t, _ in ls if t["ref"]),
            "avec_reseau": sum(1 for t, _ in ls if t["network"]),
            "fragmentees_plus_de_3_morceaux": sum(1 for t, _ in ls if t["morceaux"] > 3),
            "reseaux": reseaux.most_common(40),
            "sans_couleur_exemples": [f"{t['network']} · {t['ref']} · {t['name']}" for t, _ in ls if not t["colour"]][:25],
        }

    def refs(cat, motif):
        return sorted({t["ref"] or "?" for t, _ in par_cat.get(cat, []) if re.search(motif, f"{t['network']} {t['operator']} {t['name']}", re.I)})

    controles = {
        "metro_paris_refs": refs("metro", r"paris|ratp"),
        "metro_lyon_refs": refs("metro", r"lyon|tcl"),
        "metro_marseille_refs": refs("metro", r"marseille|rtm"),
        "metro_lille_refs": refs("metro", r"lille|ilévia|ilevia"),
        "metro_toulouse_refs": refs("metro", r"toulouse|tisséo|tisseo"),
        "metro_rennes_refs": refs("metro", r"rennes|star"),
        "rer_refs": sorted({t["ref"] or "?" for t, _ in par_cat.get("train-rer", [])}),
        "transilien_refs": sorted({t["ref"] or "?" for t, _ in par_cat.get("train-transilien", [])}),
        "tram_reseaux": collections.Counter(t["network"] or "(aucun)" for t, _ in par_cat.get("tram", [])).most_common(),
    }

    # Gares, stations et arrêts de tram, dédoublonnés (même type, même nom, à moins de ~300 m).
    def type_point(t):
        rw, st = t.get("railway"), t.get("station")
        if rw == "tram_stop" or st == "tram" or (t.get("tram") == "yes" and t.get("train") != "yes" and st not in ("subway", "light_rail")):
            return "tram"
        if st in ("subway", "monorail") or (t.get("subway") == "yes" and t.get("train") != "yes"):
            return "metro"
        if st == "light_rail" or (t.get("light_rail") == "yes" and t.get("train") != "yes"):
            return "light_rail"
        if st == "funicular":
            return "funicular"
        if rw == "halt":
            return "train-halte"
        if rw == "station" or st == "train" or t.get("train") == "yes":
            return "train-gare"
        return "autre"

    vus = {}
    brut = collections.Counter()
    for p in L.points:
        if not dans_metropole(p["lon"], p["lat"]):
            continue
        t = p["tags"]
        if any(k.startswith(("disused", "abandoned", "construction", "proposed")) for k in t) or t.get("usage") == "tourism":
            continue
        typ = type_point(t)
        brut[typ] += 1
        cle = (typ, norm(t.get("name")) or p["id"], round(p["lat"] / 0.003), round(p["lon"] / 0.004))
        if cle not in vus:
            vus[cle] = {"type": typ, "name": t.get("name"), "uic_ref": t.get("uic_ref"), "network": t.get("network"),
                        "operator": t.get("operator"), "lon": round(p["lon"], 5), "lat": round(p["lat"], 5)}
        else:
            for k in ("uic_ref", "network", "operator"):
                vus[cle][k] = vus[cle][k] or t.get(k)
    gares = list(vus.values())
    st_pts = {}
    for typ in sorted(brut):
        g = [x for x in gares if x["type"] == typ]
        st_pts[typ] = {"objets_osm": brut[typ], "apres_dedoublonnage": len(g), "avec_nom": sum(1 for x in g if x["name"]),
                       "avec_uic_ref": sum(1 for x in g if x["uic_ref"]),
                       "exploitants": collections.Counter(x["operator"] or "(aucun)" for x in g).most_common(10)}

    # Poids des fichiers d'essai.
    def ecrire(nom, feats):
        txt = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":"))
        txt = re.sub(r"(\d+\.\d{5})\d+", r"\1", txt)
        with open(os.path.join(sortie, nom), "w") as f:
            f.write(txt)
        return {"mo": round(len(txt.encode()) / 1e6, 2), "mo_gzip": round(len(gzip.compress(txt.encode())) / 1e6, 2), "objets": len(feats)}

    def feat_ligne(t, g):
        return {"type": "Feature", "properties": {k: t[k] for k in ("categorie", "ref", "name", "network", "colour") if t[k]},
                "geometry": mapping(g.simplify(TOL, preserve_topology=False))}

    poids = {}
    p2 = [feat_ligne(t, g) for t, g in lignes if t["categorie"] in PERIMETRE2]
    poids["lignes_perimetre2"] = ecrire("lignes-perimetre2.geojson", p2)
    poids["lignes_toutes"] = ecrire("lignes-toutes.geojson", [feat_ligne(t, g) for t, g in lignes])
    os.remove(os.path.join(sortie, "lignes-toutes.geojson"))  # seulement pour la mesure
    poids["gares"] = ecrire("gares.geojson", [
        {"type": "Feature", "properties": {k: v for k, v in x.items() if v and k not in ("lon", "lat")},
         "geometry": {"type": "Point", "coordinates": [x["lon"], x["lat"]]}}
        for x in gares if x["type"] in ("metro", "light_rail", "tram", "funicular", "train-gare", "train-halte")])

    resultat = {"lignes": stats, "controles": controles, "points": st_pts, "poids": poids,
                "lignes_hors_metropole": hors, "lignes_sans_geometrie": sans_geo}
    with open(os.path.join(sortie, "transports.json"), "w") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=1)
    print(json.dumps(resultat, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
