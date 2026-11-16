"""Diagnostic de l'approche A (règle de la commune) : communes à une seule école publique par niveau,
élèves concernés, sources possibles sur les RPI."""
import collections, json, requests

H = {"User-Agent": "carte-scolaire-colleges-lycees (github.com/Elmetayer/colleges_lycees.github.io)"}
ED = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"


def get(url, **p):
    if "/exports/" in url:  # même forme d'URL que build.py (delimiter d'abord, select sans encodage des virgules)
        q = "?delimiter=%3B" + "".join(f"&{k}={v}" for k, v in p.items() if k not in ("delimiter",))
        r = requests.get(url + q, headers=H, timeout=300)
        if r.status_code == 401 and "where" in p:
            print("401 avec where, nouvel essai sans filtre")
            q = "?delimiter=%3B" + "".join(f"&{k}={v}" for k, v in p.items() if k not in ("delimiter", "where"))
            r = requests.get(url + q, headers=H, timeout=300)
        print("export", r.status_code, url.split("/datasets/")[1][:40], len(r.text))
    else:
        r = requests.get(url, params=p, headers=H, timeout=300)
    if r.status_code >= 400:
        print("ERREUR", r.status_code, url, r.text[:300])
    r.raise_for_status()
    if "/exports/" in url:
        import io, pandas as pd
        return pd.read_csv(io.StringIO(r.text), sep=";", dtype=str).where(lambda d: d.notna(), None).to_dict("records")
    return r.json()


# 1. Colonnes de l'annuaire (recherche de champs RPI / regroupement)
m = get(ED + "/fr-en-annuaire-education")
cols = [f["name"] for f in m.get("fields", [])]
print("COLONNES annuaire :", len(cols))
print("  liées RPI/regroupement/réseau :", [c for c in cols if any(k in c.lower() for k in ("rpi", "regroup", "reseau", "pial", "multi", "rattach", "sige", "siege"))])

for jeu in ("fr-en-annuaire-education", "fr-en-ecoles-effectifs-nb_classes", "fr-en-ips-ecoles-ap2022", "fr-en-adresse-et-geolocalisation-etablissements-premier-et-second-degre"):
    r = requests.get(f"{ED}/{jeu}/exports/csv?delimiter=%3B&limit=2", headers=H, timeout=60)
    print("SONDE export", jeu, r.status_code, r.headers.get("www-authenticate"), r.text[:120].replace("\n", " | "))
import io, pandas as pd
d = requests.get("https://www.data.gouv.fr/api/1/datasets/", params={"q": "annuaire de l'éducation", "page_size": 5}, headers=H, timeout=60).json()
res = None
for ds in d.get("data", []):
    print("DATAGOUV jeu", ds["slug"], ds.get("organization", {}).get("name"), [(x["format"], x["title"][:50], x["url"][:120]) for x in ds["resources"][:6]])
    for x in ds["resources"]:
        if res is None and x["format"].lower() == "csv" and "annuaire" in (x["title"] + ds["slug"]).lower():
            res = x["url"]
print("ressource retenue :", res)
r = requests.get(res, headers=H, timeout=600); print("téléchargement", r.status_code, len(r.content))
txt = r.content.decode("utf-8-sig", errors="replace")
sep = ";" if txt[:2000].count(";") > txt[:2000].count(",") else ","
df = pd.read_csv(io.StringIO(txt), sep=sep, dtype=str)
print("colonnes data.gouv :", list(df.columns))
norm = {c: c.lower().replace(" ", "_").replace("'", "_").replace("é", "e").replace("è", "e") for c in df.columns}
df = df.rename(columns=norm)
print("colonnes normalisées :", list(df.columns))
ann = df.where(df.notna(), None).to_dict("records")
ann = [a for a in ann if str(a.get("type_etablissement")) in ("Ecole", "École") and (a.get("etat") or "OUVERT") == "OUVERT" and not str(a.get("code_commune") or "").startswith("97")]
print("écoles ouvertes métropole :", len(ann))
print("exemple :", ann[0])
for k in ("rpi_concentre", "rpi_disperse", "multi_uai"):
    print(k, collections.Counter(str(a.get(k)) for a in ann).most_common(5))
print("natures :", collections.Counter(a.get("libelle_nature") for a in ann).most_common(12))
pub = [a for a in ann if a.get("statut_public_prive") == "Public" and "SPECIALIS" not in str(a.get("libelle_nature") or "").upper()]
print("publiques ordinaires :", len(pub))

# 2. Effectifs de la dernière rentrée
eff = {}
for rentree in ("2025", "2024"):
    try:
        e = get(ED + "/fr-en-ecoles-effectifs-nb_classes/exports/csv", select="*")
    except Exception as ex:
        print("effectifs", rentree, str(ex)[:150]); continue
    if e:
        e = [r for r in e if str(r.get("rentree_scolaire")) == rentree]
        if not e: continue
        print("effectifs rentrée", rentree, len(e), "colonnes :", list(e[0].keys())[:40])
        for r in e:
            eff[r.get("numero_ecole") or r.get("uai")] = r
        break


def n(r, *cles):
    return sum(float(r.get(c) or 0) for c in cles)


def eleves(uai):
    r = eff.get(uai) or {}
    tot = n(r, "nombre_total_eleves")
    mat = n(r, "nombre_eleves_en_pre_elementaire_hors_ulis") or n(r, "nombre_eleves_preelementaire_hors_ulis")
    return tot, mat, tot - mat


# 3. Communes par nombre d'écoles publiques de chaque niveau
par_commune = collections.defaultdict(lambda: {"elem": [], "mat": [], "nom": ""})
for a in pub:
    c = a["code_commune"]; par_commune[c]["nom"] = a.get("nom_commune")
    if str(a.get("ecole_elementaire")) == "1":
        par_commune[c]["elem"].append(a["identifiant_de_l_etablissement"])
    if str(a.get("ecole_maternelle")) == "1":
        par_commune[c]["mat"].append(a["identifiant_de_l_etablissement"])

tot_elem = sum(eleves(a["identifiant_de_l_etablissement"])[2] for a in pub if str(a.get("ecole_elementaire")) == "1")
tot_mat = sum(eleves(a["identifiant_de_l_etablissement"])[1] for a in pub if str(a.get("ecole_maternelle")) == "1")
print(f"élèves publics : élémentaire {tot_elem:,.0f}, préélémentaire {tot_mat:,.0f}")
for niv, idx in (("elem", 2), ("mat", 1)):
    cat = collections.Counter(); el = collections.Counter(); ec = collections.Counter()
    for c, d in par_commune.items():
        k = len(d[niv]); k = "0" if k == 0 else ("1" if k == 1 else ("2-3" if k <= 3 else "4+"))
        cat[k] += 1; ec[k] += len(d[niv]); el[k] += sum(eleves(u)[idx] for u in d[niv])
    t = sum(el.values()) or 1
    print(f"NIVEAU {niv} : communes avec école publique de ce niveau = {sum(v for k, v in cat.items() if k != '0')}")
    for k in ("1", "2-3", "4+"):
        print(f"  {k} école(s) : {cat[k]} communes, {ec[k]} écoles, {el[k]:,.0f} élèves ({el[k] / t:.1%})")

# Cas particuliers : une maternelle seule ou une élémentaire seule (souvent RPI dispersé)
seule_mat = [c for c, d in par_commune.items() if d["mat"] and not d["elem"]]
seule_elem = [c for c, d in par_commune.items() if d["elem"] and not d["mat"]]
print("communes avec maternelle publique mais aucune élémentaire :", len(seule_mat), [par_commune[c]["nom"] for c in seule_mat[:8]])
print("communes avec élémentaire publique mais aucune maternelle :", len(seule_elem), [par_commune[c]["nom"] for c in seule_elem[:8]])

# Petites écoles d'une commune à une école : indice de RPI (classes à niveaux partiels)
if eff:
    ex = next(iter(eff.values()))
    niv_cols = [c for c in ex if c.startswith("nombre_eleves_") and any(x in c for x in ("cp", "ce1", "ce2", "cm1", "cm2"))]
    print("colonnes par niveau :", niv_cols)
    if niv_cols:
        partiel = 0; total1 = 0; exemples = []
        for c, d in par_commune.items():
            if len(d["elem"]) != 1: continue
            r = eff.get(d["elem"][0]); total1 += 1
            if not r: continue
            vides = [x for x in niv_cols if "ulis" not in x and float(r.get(x) or 0) == 0]
            if vides:
                partiel += 1
                if len(exemples) < 8: exemples.append((d["nom"], [v.replace("nombre_eleves_", "") for v in vides]))
        print(f"communes à 1 élémentaire dont l'école n'a pas tous les niveaux CP-CM2 (indice RPI dispersé) : {partiel} / {total1}", exemples)

# Population : communes sans aucune école publique
try:
    com = get("https://geo.api.gouv.fr/communes?fields=code,population,codeDepartement")
    com = [c for c in com if not c["code"].startswith("97")]
    sans = [c for c in com if c["code"] not in par_commune]
    print(f"communes métropole : {len(com)} ; sans école publique : {len(sans)} ({sum(c.get('population') or 0 for c in sans):,} habitants)")
except Exception as ex:
    print("geo.api", str(ex)[:150])

# 3b. RPI d'après l'annuaire
def oui(v): return str(v) in ("1", "True", "true", "OUI", "Oui")
for niv, idx in (("elem", 2), ("mat", 1)):
    une = [c for c, d in par_commune.items() if len(d[niv]) == 1]
    byu = {a["identifiant_de_l_etablissement"]: a for a in pub}
    rd = [c for c in une if oui(byu[par_commune[c][niv][0]].get("rpi_disperse"))]
    rc = [c for c in une if oui(byu[par_commune[c][niv][0]].get("rpi_concentre"))]
    el = lambda L: sum(eleves(par_commune[c][niv][0])[idx] for c in L)
    print(f"{niv} : communes à 1 école = {len(une)} ({el(une):,.0f} élèves) ; dont école en RPI dispersé {len(rd)} ({el(rd):,.0f}), RPI concentré {len(rc)} ({el(rc):,.0f})")
    propre = [c for c in une if c not in set(rd) | set(rc)]
    print(f"   hors RPI : {len(propre)} communes, {el(propre):,.0f} élèves")
print("écoles publiques en RPI dispersé :", sum(oui(a.get("rpi_disperse")) for a in pub), "concentré :", sum(oui(a.get("rpi_concentre")) for a in pub))

# 4. Sources sur les RPI
for q in ["regroupement pédagogique", "RPI", "regroupement intercommunal école"]:
    try:
        c = get(ED, where=f'search("{q}")', limit=20, select="dataset_id,metas.default.title")
        print("ÉDUCATION", q, [x.get("dataset_id") for x in c.get("results", [])])
    except Exception as ex:
        print("ÉDUCATION", q, str(ex)[:150])
    try:
        c = requests.get("https://www.data.gouv.fr/api/1/datasets/", params={"q": q, "page_size": 15}, headers=H, timeout=60).json()
        print("DATAGOUV", q, [(x["title"][:70], x.get("organization", {}) and x["organization"].get("name", "")[:30]) for x in c.get("data", [])])
    except Exception as ex:
        print("DATAGOUV", q, str(ex)[:150])
