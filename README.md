# Carte scolaire

Carte des écoles, des collèges et des lycées de France métropolitaine, avec leurs indicateurs : indice de position sociale (IPS), résultats au brevet, valeur ajoutée, évaluations de 6e et, pour les écoles, taille des classes. Pensée d'abord pour le téléphone.

Site : https://elmetayer.github.io/colleges_lycees.github.io/

## Organisation

```
pipeline/build.py         chef d'orchestre : télécharge l'open data, lit l'annuaire, appelle les modules, écrit meta.json
pipeline/colleges.py      indicateurs des collèges (brevet, IPS, évaluations 6e) → colleges.geojson, fiches
pipeline/lycees.py        indicateurs des lycées (voies GT et pro, IPS) → lycees.geojson, fiches
pipeline/ecoles.py        écoles (IPS et rangs, effectifs, taille des classes) → ecoles/<dep>.geojson, fiches
pipeline/secteurs.py      secteurs des collèges publics, département par département
pipeline/ecoles_6e.py     entrée en 6e des écoles : évaluations de 6e du collège de secteur (après l'assemblage des secteurs)
pipeline/secteurs_ecoles.py secteurs des écoles publiés par les villes (Paris, Bordeaux, Strasbourg, Nantes, Orléans, Clermont-Ferrand, Tours, Saint-Nazaire) → secteurs-ecoles/<ville>.geojson
pipeline/zones_communes.py  zones des communes à une seule école publique et des regroupements pédagogiques (RPI), d'après l'annuaire → zones-communes/<dep>.geojson
pipeline/transports.py    calque Transports : lignes de métro, tram, RER, Transilien, téléphériques urbains, réseau TER et gares d'OpenStreetMap (extrait Geofabrik) → transports/lignes.geojson, ter.geojson, gares.geojson
pipeline/suivi.py         rapport de chaque build (sources, contrôles) → data/suivi.json, historique dans la branche suivi-donnees
pipeline/requirements.txt dépendances Python
site/                     site statique publié sur GitHub Pages
  index.html, app.js      carte (MapLibre GL)
  style.css               styles ; bloc :root en tête = charte graphique (toutes les couleurs et polices, lues aussi par la carte)
  polices/                Literata et Atkinson Hyperlegible (woff2 des paquets @fontsource, licence SIL OFL), servies par le site
  parametres.js           réglages modifiables sans toucher au code (zone neutre de la valeur ajoutée, textes, clé Web3Forms du formulaire de contact)
  documentation.html      sommaire de la documentation
  documentation-*.html    pages : carte, collèges, lycées, écoles, secteurs, sources
  suivi.html, suivi.js    suivi de la récupération des données (état des sources, contrôles, historique)
  documentation.js        valeurs lues dans meta.json et sommaire de chaque page
  favicon.svg, favicon.ico, apple-touch-icon.png  icône d'onglet (épingle et école) ; .ico et .png tirés du .svg
  robots.txt, sitemap.xml  référencement (liste des pages à mettre à jour quand on en ajoute une)
  partage.png             image des liens partagés (Open Graph), tirée de outils/partage.svg
                          mesure d'audience : GoatCounter (macartescolaire.goatcounter.com, sans cookie), script en bas de chaque page,
                          actions comptées par compter() dans app.js (fiches par UAI, recherches, collège de secteur trouvé)
  data/                   fichiers générés par le script (non versionnés) ; data/fiches/ : historiques par département
.github/workflows/        construction et publication automatiques
```

## Fonctionnement

Le workflow GitHub Actions calcule les secteurs des collèges, lance `pipeline/build.py` (données des établissements et des secteurs des écoles), vérifie le site dans un vrai navigateur (`tests/verifier_site.py`), puis publie le dossier `site/` sur GitHub Pages. Une vérification en échec bloque la publication : le site garde sa version précédente. Il tourne à chaque modification de `main`, le 3 de chaque mois, et à la demande depuis l'onglet Actions.

Le calque Transports est préparé par un job à part (`transports`), en parallèle des secteurs : il télécharge l'extrait France d'OpenStreetMap chez Geofabrik (4,8 Go, une vingtaine de minutes), le filtre avec osmium et calcule lignes et gares. L'extrait n'est retéléchargé que si les données gardées en cache Actions ont plus de 25 jours ; l'extrait filtré (environ 15 Mo) reste en cache pour recalculer quand la méthode change (`VERSION_CALCUL` dans `pipeline/transports.py`). En cas d'échec, la version précédente est publiée et signalée sur la page de suivi. Les lignes sont coupées à la frontière avec les contours des départements d'Etalab ; une copie des contours est gardée dans le même cache, reprise si Etalab ne répond pas, et un calcul fait sans frontière est refait au build suivant. Sur le site, le calque est masqué par défaut et ses fichiers ne sont chargés qu'à la première activation.

Charte graphique : toutes les couleurs et les polices sont des variables CSS du bloc `:root` en tête de `site/style.css` (marque, gris, états, graphiques, carte, échelles de données). `app.js` les lit au démarrage (`couleur("encre")`) pour colorer la carte, les icônes et les graphiques : changer une valeur dans ce bloc change l'interface et la carte. Restent à reprendre à la main quand la charte change : les deux icônes en data URI de `style.css` (flèche des listes, loupe), `favicon.svg` (puis `.ico` et `.png`) et `outils/partage.svg` (puis `partage.png`). La vérification contrôle que chaque couleur lue par `app.js` existe dans `style.css` et qu'aucune page n'appelle Google Fonts.

Dans les réglages du dépôt, Settings → Pages doit avoir « GitHub Actions » comme source.

## Branches

| Branche | Contenu | Durée de vie |
|---|---|---|
| `main` | Code du site et du pipeline, workflow de build | Permanente |
| `suivi-donnees` | Rapport du dernier build (`suivi/dernier.json`) et historique des 10 derniers (`suivi/historique.json`) | Permanente : **ne pas supprimer** |
| `diag-ecoles` | Scripts de diagnostic des portails open data des villes, avec leur propre petit workflow | Temporaire, à supprimer à la fin du jalon 7 |

Les autres branches sont celles des pull requests : une par livraison, à supprimer après la fusion.

```
  branche d'une PR ──(fusion)──► main
                                  │
               build (à chaque fusion, le 3 du mois, à la demande)
                  │                              │
      si tout est OK : publie           dans tous les cas : écrit
      le site (GitHub Pages)            le rapport dans suivi-donnees
                  │                              │
                  └────── suivi.html lit ────────┘
                          les deux

  diag-ecoles : indépendante, ses diagnostics tournent à part
```

- Une pull request lance un build de vérification, sans publication ni rapport dans `suivi-donnees`.
- À la fin de chaque build de `main`, réussi ou non, l'étape « Ranger le rapport » (`pipeline/suivi.py publier`) copie la seule branche `suivi-donnees` dans un dossier temporaire, y écrit le rapport, met à jour l'historique, puis pousse un commit au nom de `github-actions[bot]`, avec le jeton fourni au build (permission `contents: write`). Si la branche n'existe pas, elle est recréée vide ; seul l'historique est alors perdu.
- `suivi-donnees` ne contient aucun workflow : un push sur elle ne déclenche rien (et GitHub ne lance jamais de workflow sur un push fait avec le jeton d'un build).
- La page `suivi.html` lit le rapport du site publié (`data/suivi.json`) et celui de `suivi-donnees` sur `raw.githubusercontent.com`. Si le dernier build a échoué, elle le signale : la carte affichée est alors celle du build précédent.

## Lancer en local

```
pip install -r pipeline/requirements.txt
python pipeline/build.py --out site/data
python -m http.server --directory site 8000
```

Puis ouvrir http://localhost:8000.

## Sources

Données de l'Éducation nationale (DEPP, DGESCO) sous Licence Ouverte 2.0. Calque Transports : © contributeurs OpenStreetMap, ODbL. Le détail est sur la page Documentation du site.
