"""Diagnostic de l'approche A (règle de la commune) : communes à une seule école publique par niveau,
élèves concernés, sources possibles sur les RPI."""
import collections, json, requests

H = {"User-Agent": "carte-scolaire-diag"}
ED = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets"


def get(url, **p):
    r = requests.get(url, params=p, headers=H, timeout=300); r.raise_for_status(); return r.json()


# 1. Colonnes de l'annuaire (recherche de champs RPI / regroupement)
m = get(ED + "/fr-en-annuaire-education")
cols = [f["name"] for f in m.get("fields", [])]
print("COLONNES annuaire :", len(cols))
print("  liées RPI/regroupement/réseau :", [c for c in cols if any(k in c.lower() for k in ("rpi", "regroup", "reseau", "pial", "multi", "rattach", "sige", "siege"))])

ann = get(ED + "/fr-en-annuaire-education/exports/json", where="type_etablissement='Ecole'",
          select="identifiant_de_l_etablissement,nom_etablissement,statut_public_prive,ecole_maternelle,ecole_elementaire,code_commune,nom_commune,code_departement,etat,libelle_nature,code_nature")
ann = [a for a in ann if (a.get("etat") or "OUVERT") == "OUVERT" and not str(a.get("code_commune") or "").startswith("97")]
print("écoles ouvertes métropole :", len(ann))
print("natures :", collections.Counter(a.get("libelle_nature") for a in ann).most_common(12))
pub = [a for a in ann if a.get("statut_public_prive") == "Public" and "SPECIALIS" not in str(a.get("libelle_nature") or "").upper()]
print("publiques ordinaires :", len(pub))

# 2. Effectifs de la dernière rentrée
eff = {}
for rentree in ("2025", "2024"):
    try:
        e = get(ED + "/fr-en-ecoles-effectifs-nb_classes/exports/json", where=f"rentree_scolaire='{rentree}'")
    except Exception as ex:
        print("effectifs", rentree, str(ex)[:150]); continue
    if e:
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
