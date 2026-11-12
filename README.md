# Carte scolaire

Carte des collèges et des lycées de France métropolitaine, avec leurs indicateurs : indice de position sociale (IPS), résultats au brevet, valeur ajoutée et évaluations de 6e. Pensée d'abord pour le téléphone.

Site : https://elmetayer.github.io/colleges_lycees.github.io/

## Organisation

```
pipeline/build.py         télécharge l'open data, calcule les indicateurs (collèges et lycées : France métropolitaine)
pipeline/requirements.txt dépendances Python
site/                     site statique publié sur GitHub Pages
  index.html, app.js      carte (MapLibre GL)
  parametres.js           réglages modifiables sans toucher au code (zone neutre de la valeur ajoutée, textes)
  documentation.html      sommaire de la documentation
  documentation-*.html    pages : carte, collèges, lycées, secteurs, sources
  documentation.js        valeurs lues dans meta.json et sommaire de chaque page
  data/                   fichiers générés par le script (non versionnés) ; data/fiches/ : historiques par département
.github/workflows/        construction et publication automatiques
```

## Fonctionnement

Le workflow GitHub Actions lance `pipeline/build.py`, qui écrit `site/data/colleges.geojson` et `site/data/meta.json`, puis publie le dossier `site/` sur GitHub Pages. Il tourne à chaque modification de `main`, le 3 de chaque mois, et à la demande depuis l'onglet Actions.

Dans les réglages du dépôt, Settings → Pages doit avoir « GitHub Actions » comme source.

## Lancer en local

```
pip install -r pipeline/requirements.txt
python pipeline/build.py --out site/data
python -m http.server --directory site 8000
```

Puis ouvrir http://localhost:8000.

## Sources

Données de l'Éducation nationale (DEPP, DGESCO) sous Licence Ouverte 2.0. Le détail est sur la page Documentation du site.
