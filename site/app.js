/* Carte scolaire : collèges et lycées de France métropolitaine, en calques. */
(function () {
  "use strict";

  // Plasma, du plus bas (jaune) au plus haut (bleu nuit). Lisible pour les daltoniens.
  const ECHELLE = ["#f0f921", "#f89540", "#cc4778", "#7e03a8", "#0d0887"];
  // Valeur ajoutée, dans la logique de Plasma : valeurs basses côté orange, valeurs hautes côté violet,
  // zéro en gris très clair. Les extrêmes ont une clarté proche pour ne favoriser aucun côté.
  const DIVERGENTE = ["#c4500f", "#f4ad73", "#f3f1f6", "#b48ad9", "#6a0d9e"];
  const ABSENT = "#a7adba";

  // Réglages modifiables dans parametres.js (valeurs par défaut si le fichier manque).
  const VA = Object.assign({
    seuils: { va_reussite: 2, va_note: 0.3 },
    libelles: { proche: "proche de l'attendu", dessous: "en dessous de l'attendu", dessus: "au-dessus de l'attendu" },
    texteZone: "Entre {min} et {max} {unite}, l'écart est considéré comme faible.",
    texteRepartition: "{dessous} % des collèges en dessous de l'attendu, {proches} % proches, {dessus} % au-dessus.",
  }, (window.PARAMETRES && window.PARAMETRES.valeurAjoutee) || {});
  const remplir = (modele, valeurs) => modele.replace(/\{(\w+)\}/g, (m, k) => (k in valeurs ? valeurs[k] : m));

  // Indicateurs proposés pour chaque calque. "doc" pointe vers la section de documentation.
  const pct1 = (v) => fr(v, 1) + " %", pct0 = (v) => fr(v, 0) + " %";
  const INDICATEURS = [
    { cle: "taux_reussite", nom: "Réussite au brevet", type: "seq", fmt: pct1, doc: "brevet" },
    { cle: "taux_mentions", nom: "Mentions au brevet", type: "seq", fmt: pct1, doc: "brevet" },
    { cle: "note_ecrit", nom: "Note aux écrits du brevet", type: "seq", fmt: (v) => fr(v, 1) + " / 20", doc: "brevet" },
    { cle: "va_reussite", nom: "Valeur ajoutée (réussite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "points",
      note: "Écart entre la réussite obtenue et celle attendue au vu du profil des élèves." },
    { cle: "va_note", nom: "Valeur ajoutée (note écrite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "point",
      note: "Écart entre la note obtenue et celle attendue au vu du profil des élèves." },
    { cle: "ips", nom: "Indice de position sociale (IPS)", court: "IPS", type: "seq", fmt: (v) => fr(v, 1), doc: "ips",
      note: "Plus l'IPS est élevé, plus le milieu social des élèves est favorisé." },
    { cle: "eval_fr", nom: "Évaluations 6e (français)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "eval_ma", nom: "Évaluations 6e (maths)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "score", nom: "Score agrégé", court: "Score au brevet", type: "seq", fmt: (v) => fr(v, 1), doc: "score",
      note: "Moyenne des taux de réussite, de mentions et de mentions très bien. À lire avec précaution." },
  ];
  const GT = "Voie générale et technologique", PRO = "Voie professionnelle", SOCIAL = "Milieu social", SYNTHESE = "Synthèse";
  const NOTE_VA = "Écart entre le résultat obtenu et celui attendu au vu du profil des élèves.";
  const NOTE_ACCES = "Part des élèves de seconde qui obtiennent le bac en restant dans le lycée.";
  const INDICATEURS_LYCEES = [
    { cle: "gt_reussite", groupe: GT, nom: "Réussite au bac", court: "Réussite au bac GT", type: "seq", fmt: pct0 },
    { cle: "gt_mentions", groupe: GT, nom: "Mentions au bac", court: "Mentions au bac GT", type: "seq", fmt: pct0 },
    { cle: "gt_acces", groupe: GT, nom: "Accès de la seconde au bac", court: "Accès au bac GT", type: "seq", fmt: pct0, note: NOTE_ACCES },
    { cle: "gt_va_reussite", groupe: GT, nom: "Valeur ajoutée (réussite)", court: "Valeur ajoutée GT", type: "div", fmt: signe0, unite: "points", note: NOTE_VA },
    { cle: "gt_va_acces", groupe: GT, nom: "Valeur ajoutée (accès au bac)", court: "Valeur ajoutée accès GT", type: "div", fmt: signe0, unite: "points", note: NOTE_VA },
    { cle: "pro_reussite", groupe: PRO, nom: "Réussite au bac pro", court: "Réussite au bac pro", type: "seq", fmt: pct0 },
    { cle: "pro_mentions", groupe: PRO, nom: "Mentions au bac pro", court: "Mentions au bac pro", type: "seq", fmt: pct0 },
    { cle: "pro_acces", groupe: PRO, nom: "Accès de la seconde au bac pro", court: "Accès au bac pro", type: "seq", fmt: pct0, note: NOTE_ACCES },
    { cle: "pro_va_reussite", groupe: PRO, nom: "Valeur ajoutée (réussite)", court: "Valeur ajoutée pro", type: "div", fmt: signe0, unite: "points", note: NOTE_VA },
    { cle: "pro_va_acces", groupe: PRO, nom: "Valeur ajoutée (accès au bac)", court: "Valeur ajoutée accès pro", type: "div", fmt: signe0, unite: "points", note: NOTE_VA },
    { cle: "ips", groupe: SOCIAL, nom: "IPS du lycée", court: "IPS du lycée", type: "seq", fmt: (v) => fr(v, 1),
      note: "Plus l'IPS est élevé, plus le milieu social des élèves est favorisé." },
    { cle: "ips_gt", groupe: SOCIAL, nom: "IPS de la voie générale et techno", court: "IPS voie GT", type: "seq", fmt: (v) => fr(v, 1) },
    { cle: "ips_pro", groupe: SOCIAL, nom: "IPS de la voie pro", court: "IPS voie pro", type: "seq", fmt: (v) => fr(v, 1) },
    { cle: "score", groupe: SYNTHESE, nom: "Score de la voie générale", court: "Score voie générale", type: "seq", fmt: (v) => fr(v, 1),
      note: "Moyenne des taux de réussite, de mentions et de mentions très bien au bac général. À lire avec précaution." },
  ];

  // Les trois calques. Chaque type d'établissement a sa forme : cercle (écoles),
  // carré (collèges), triangle (lycées), de plus en plus grands.
  const CALQUES = [
    { cle: "colleges", nom: "Collèges", pluriel: "collèges", forme: "carre", indicateurs: INDICATEURS, defaut: "taux_reussite",
      perimetre: "Collèges de France métropolitaine ; couleurs réparties sur l'ensemble de ces collèges.",
      zones: { libelle: "Secteurs des collèges publics",
        note: "Les secteurs sont ceux des collèges publics. Ils restent affichés quand seuls les privés sont visibles, avec la couleur de leur collège. Ils apparaissent en zoomant sur un département ; quelques départements absents du fichier national de carte scolaire n'en ont pas." } },
    { cle: "lycees", nom: "Lycées", pluriel: "lycées", forme: "triangle", indicateurs: INDICATEURS_LYCEES, defaut: "ips", voies: true,
      perimetre: "Lycées de France métropolitaine ; couleurs réparties sur l'ensemble de ces lycées.",
      zones: { libelle: "Secteurs des lycées", indisponible: true,
        note: "Non publiés en open data : l'affectation en lycée passe par Affelnet, avec des règles propres à chaque académie." } },
    { cle: "ecoles", nom: "Écoles", pluriel: "écoles", forme: "cercle", bientot: true },
  ];
  const calque = (cle) => CALQUES.find((c) => c.cle === cle);

  const $ = (id) => document.getElementById(id);
  const etat = $("etat");
  let donnees = null;          // collèges (GeoJSON)
  const sources = {};          // données chargées par calque

  function fr(v, nd) {
    return Number(v).toLocaleString("fr-FR", { minimumFractionDigits: nd, maximumFractionDigits: nd });
  }
  function signe(v) {
    const s = fr(Math.abs(v), 1);
    return (v > 0 ? "+" : v < 0 ? "−" : "") + s;
  }
  function signe0(v) {
    return (v > 0 ? "+" : v < 0 ? "−" : "") + fr(Math.abs(v), 0);
  }
  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  }
  function echapper(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------------------------------------------------------- réglages des calques
  // Gardés d'une visite à l'autre dans le navigateur (sans effet si le stockage est bloqué).
  const CLE_STOCKAGE = "carte-scolaire-calques-v1";
  const reglages = {};
  (function chargerReglages() {
    let lu = {};
    try { lu = JSON.parse(localStorage.getItem(CLE_STOCKAGE) || "{}") || {}; } catch (e) { lu = {}; }
    CALQUES.filter((c) => !c.bientot).forEach((c) => {
      const r = Object.assign({ actif: true, indicateur: c.defaut, public: true, prive: true, voie_gt: true, voie_pro: true, zones: true }, lu[c.cle] || {});
      if (!c.indicateurs.some((i) => i.cle === r.indicateur)) r.indicateur = c.defaut;
      reglages[c.cle] = r;
    });
  })();
  function sauverReglages() {
    try { localStorage.setItem(CLE_STOCKAGE, JSON.stringify(reglages)); } catch (e) { /* stockage indisponible */ }
  }
  const indicateurDe = (c) => c.indicateurs.find((i) => i.cle === reglages[c.cle].indicateur) || c.indicateurs[0];

  // ---------------------------------------------------------------- carte
  // Si le fond de carte ne répond pas, on garde au moins les points sur un fond uni.
  const STYLE_SECOURS = { version: 8, sources: {}, layers: [{ id: "fond", type: "background", paint: { "background-color": "#eef1f4" } }] };
  const carte = new maplibregl.Map({
    container: "carte",
    style: "https://tiles.openfreemap.org/styles/positron",
    center: [2.4, 46.6],  // France métropolitaine ; cadrer() ajuste ensuite sur les établissements
    zoom: 5,
    attributionControl: { compact: true },
  });
  window.carteScolaire = carte;  // accès pour le test automatique (tests/verifier_site.py)
  let secours = false;
  carte.on("error", () => {
    if (!secours && !carte.isStyleLoaded()) { secours = true; carte.setStyle(STYLE_SECOURS); }
  });
  carte.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  carte.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");

  // Formes : images « champ de distance » (SDF), que MapLibre peut colorer selon l'indicateur
  // et entourer d'un contour (halo) dont l'épaisseur dépend du secteur public ou privé.
  // Tailles en pixels à icon-size 1 : cercle 10, carré 13, triangle 22 de côté.
  const FORMES = {
    cercle: { demi: 5, d: (x, y) => Math.hypot(x, y) - 5 },
    carre: { demi: 6.5, d: (x, y) => {
      const r = 1.5, qx = Math.abs(x) - (6.5 - r), qy = Math.abs(y) - (6.5 - r);
      return Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
    } },
    triangle: { demi: 11, d: (x, y) => {
      // Triangle équilatéral pointe en haut, centré sur son centre de gravité (formule d'I. Quilez).
      const R = 11, k = Math.sqrt(3);
      let px = Math.abs(x) - R, py = -y + R / k;
      if (px + k * py > 0) { const nx = (px - k * py) / 2, ny = (-k * px - py) / 2; px = nx; py = ny; }
      px -= Math.min(Math.max(px, -2 * R), 0);
      return -Math.hypot(px, py) * Math.sign(py);
    } },
  };
  function ajouterFormes() {
    const ratio = 2, marge = 7;
    Object.entries(FORMES).forEach(([nom, f]) => {
      if (carte.hasImage("forme-" + nom)) return;
      const cote = Math.ceil((f.demi + marge) * 2), S = cote * ratio, data = new Uint8ClampedArray(S * S * 4);
      for (let j = 0; j < S; j++) for (let i = 0; i < S; i++) {
        const x = (i + 0.5) / ratio - cote / 2, y = (j + 0.5) / ratio - cote / 2;
        data[(j * S + i) * 4 + 3] = Math.max(0, Math.min(255, Math.round(255 * (0.75 - f.d(x, y) / 8))));
      }
      carte.addImage("forme-" + nom, { width: S, height: S, data }, { pixelRatio: ratio, sdf: true });
    });
  }
  // Petite icône de la forme, pour le panneau et les légendes.
  function iconeForme(forme, { couleur = "#7e03a8", prive = false, taille = 22, gris = false } = {}) {
    const fill = gris ? "#c9cede" : couleur;
    const trait = prive && !gris ? 'stroke="#1e2f6b" stroke-width="2.5"' : 'stroke="#ffffff" stroke-width="1.5"';
    const fig = forme === "cercle" ? `<circle cx="11" cy="11" r="7" fill="${fill}" ${trait}/>`
      : forme === "carre" ? `<rect x="3.5" y="3.5" width="15" height="15" rx="2" fill="${fill}" ${trait}/>`
      : `<path d="M11 2.5 L20 18.5 L2 18.5 Z" fill="${fill}" ${trait} stroke-linejoin="round"/>`;
    return `<svg class="forme" width="${taille}" height="${taille}" viewBox="0 0 22 22" aria-hidden="true">${fig}</svg>`;
  }

  // Échelles séquentielles : les couleurs sont posées sur les quantiles (5 %, 25 %, médiane,
  // 75 %, 95 %) pour que chaque teinte couvre à peu près autant d'établissements et que les écarts
  // restent lisibles même quand les valeurs sont serrées.
  function domaine(ind, features) {
    const vals = features.map((f) => f.properties[ind.cle]).filter((v) => typeof v === "number").sort((a, b) => a - b);
    if (ind.type === "div") {
      // Zone neutre : entre -seuil et +seuil, l'établissement fait à peu près ce qui était attendu.
      const s = Number(VA.seuils[ind.cle] ?? 2) || 0;
      const m = Math.max(Math.abs(quantile(vals, 0.05)), Math.abs(quantile(vals, 0.95)), s * 2) || 1;
      return {
        stops: [-m, -s, 0, s, m], m, s, n: vals.length,
        dessous: vals.filter((v) => v < -s).length,
        proches: vals.filter((v) => Math.abs(v) <= s).length,
        dessus: vals.filter((v) => v > s).length,
      };
    }
    const stops = [0.05, 0.25, 0.5, 0.75, 0.95].map((q) => quantile(vals, q));
    for (let i = 1; i < stops.length; i++) if (stops[i] <= stops[i - 1]) stops[i] = stops[i - 1] + 1e-6;
    return { stops, n: vals.length };
  }

  function couleur(ind, features) {
    const d = domaine(ind, features);
    const pal = ind.type === "div" ? DIVERGENTE : ECHELLE;
    if (ind.type === "div") {
      const val = ["get", ind.cle];
      const expr = ["case",
        ["!", ["has", ind.cle]], ABSENT,
        ["<=", ["abs", val], d.s], pal[2],
        ["interpolate", ["linear"], val, -d.m, pal[0], -d.s, pal[1], d.s, pal[3], d.m, pal[4]]];
      return { expr, d, pal };
    }
    const stops = pal.flatMap((c, i) => [d.stops[i], c]);
    return { expr: ["case", ["has", ind.cle], ["interpolate", ["linear"], ["get", ind.cle], ...stops], ABSENT], d, pal };
  }

  function filtreSecteur(r) {
    const secteurs = [];
    if (r.public) secteurs.push("public");
    if (r.prive) secteurs.push("privé");
    return ["in", ["get", "secteur"], ["literal", secteurs]];
  }

  // Filière des lycées, d'après leur type dans l'annuaire de l'Éducation nationale.
  // Les lycées polyvalents (et agricoles, que l'annuaire ne distingue pas) ont les deux voies :
  // ils restent visibles tant qu'une des deux voies est cochée.
  const TYPE_GT = "Lycée général et technologique", TYPE_PRO = "Lycée professionnel";
  function filtreVoie(r) {
    if (!r.voie_gt && !r.voie_pro) return false;
    const caches = [];
    if (!r.voie_gt) caches.push(TYPE_GT);
    if (!r.voie_pro) caches.push(TYPE_PRO);
    return ["!", ["in", ["get", "type"], ["literal", caches]]];
  }
  const filtreCalque = (c, r) => (c.voies ? ["all", filtreSecteur(r), filtreVoie(r)] : filtreSecteur(r));

  // Calque de points d'un type d'établissement : sa forme, colorée selon l'indicateur.
  function ajouterCalqueCarte(c, avant) {
    carte.addSource(c.cle, { type: "geojson", data: sources[c.cle] });
    const prive = ["==", ["get", "secteur"], "privé"];
    carte.addLayer({
      id: c.cle, type: "symbol", source: c.cle,
      layout: {
        "icon-image": "forme-" + c.forme,
        "icon-size": ["interpolate", ["linear"], ["zoom"], 8, 0.55, 11, 0.85, 13, 1, 16, 1.4],
        "icon-allow-overlap": true, "icon-ignore-placement": true,
      },
      paint: {
        "icon-color": ABSENT,
        "icon-halo-color": ["case", prive, "#1e2f6b", "#ffffff"],
        "icon-halo-width": ["interpolate", ["linear"], ["zoom"], 8, ["case", prive, 1.3, 0.6], 13, ["case", prive, 2.4, 1]],
      },
    }, avant);
  }

  const perimetre = (c) => (c.perimetre ? `<p class="note">${echapper(c.perimetre)}</p>` : "");

  // Légende d'un calque : courte (dégradé et bornes) et notes (affichées avec les réglages).
  function legende(c, ind, d, pal) {
    const features = sources[c.cle].features;
    const manquants = features.length - d.n;
    const sans = manquants > 0 ? `<p class="note">En gris : ${manquants} ${c.pluriel} sans donnée.</p>` : "";
    if (ind.type === "div") {
      const pos = (x) => (((x + d.m) / (2 * d.m)) * 100).toFixed(1) + "%";
      const p100 = (k) => Math.round((100 * k) / (d.n || 1));
      return {
        courte: `<div class="degrade" style="background:linear-gradient(90deg,${pal[0]} 0%,${pal[1]} ${pos(-d.s)},${pal[2]} ${pos(-d.s)},${pal[2]} ${pos(d.s)},${pal[3]} ${pos(d.s)},${pal[4]} 100%)"></div>` +
          `<div class="bornes"><span>${ind.fmt(-d.m)}</span><span>${echapper(VA.libelles.proche)}</span><span>${ind.fmt(d.m)}</span></div>`,
        notes: perimetre(c) + `<p class="note">${ind.note || ""} ${echapper(remplir(VA.texteZone, { min: ind.fmt(-d.s), max: ind.fmt(d.s), unite: ind.unite }))}</p>` +
          `<p class="note">${echapper(remplir(VA.texteRepartition, { dessous: p100(d.dessous), proches: p100(d.proches), dessus: p100(d.dessus), etablissements: c.pluriel }))}</p>` + sans,
      };
    }
    return {
      courte: `<div class="degrade" style="background:linear-gradient(90deg,${pal.join(",")})"></div>` +
        `<div class="bornes"><span>${ind.fmt(d.stops[0])}</span><span>${ind.fmt(d.stops[2])}</span><span>${ind.fmt(d.stops[4])}</span></div>`,
      notes: `<p class="note">La teinte du milieu correspond à la médiane : la moitié des ${c.pluriel} est au-dessus.</p>` +
        (ind.note ? `<p class="note">${ind.note}</p>` : "") + sans + perimetre(c),
    };
  }

  function appliquerCalque(c) {
    if (!sources[c.cle] || !carte.getLayer(c.cle)) return;
    const r = reglages[c.cle], ind = indicateurDe(c);
    const { expr, d, pal } = couleur(ind, sources[c.cle].features);
    carte.setPaintProperty(c.cle, "icon-color", expr);
    carte.setFilter(c.cle, filtreCalque(c, r));
    carte.setLayoutProperty(c.cle, "visibility", r.actif ? "visible" : "none");
    if (c.cle === "colleges" && carte.getLayer("secteurs-fond")) {
      carte.setPaintProperty("secteurs-fond", "fill-color", expr);
      const vis = r.actif && r.zones ? "visible" : "none";
      ["secteurs-fond", "secteurs-contour", "secteurs-surligne"].forEach((id) => carte.setLayoutProperty(id, "visibility", vis));
      if (carte.getLayer("secteurs-fond")) chargerSecteursVisibles();  // charge les départements visibles et met à jour l'indication
    }
    const l = legende(c, ind, d, pal);
    const el = document.querySelector(`.calque[data-calque="${c.cle}"]`);
    if (!el) return;
    el.querySelector(".calque-legende").innerHTML = r.actif
      ? `<div class="legende-ligne">${iconeForme(c.forme, { taille: 16 })}<div class="legende-corps"><span class="legende-nom">${echapper(ind.court || ind.nom)}</span>${l.courte}</div></div>`
      : "";
    el.querySelector(".legende-notes").innerHTML = l.notes;
  }

  // ---------------------------------------------------------------- panneau des calques
  const estMobile = () => window.innerWidth < 760;

  function resume(c) {
    const r = reglages[c.cle];
    if (!r.actif) return "Masqués";
    const ind = indicateurDe(c);
    const morceaux = [ind.court || ind.nom];
    morceaux.push(r.public && r.prive ? "publics et privés" : r.public ? "publics" : r.prive ? "privés" : "aucun établissement");
    if (c.voies && r.voie_gt !== r.voie_pro) morceaux.push(r.voie_gt ? "voie générale et techno" : "voie pro");
    if (c.voies && !r.voie_gt && !r.voie_pro) morceaux.push("aucune voie");
    if (c.zones && !c.zones.indisponible && r.zones) morceaux.push("zones");
    return morceaux.join(", ");
  }

  function optionsIndicateurs(c) {
    const dispo = c.indicateurs.filter((i) => sources[c.cle].features.some((f) => typeof f.properties[i.cle] === "number"));
    const opt = (i) => `<option value="${i.cle}"${i.cle === reglages[c.cle].indicateur ? " selected" : ""}>${echapper(i.nom)}</option>`;
    if (!dispo.some((i) => i.groupe)) return dispo.map(opt).join("");
    const groupes = [...new Set(dispo.map((i) => i.groupe))];
    return groupes.map((g) => `<optgroup label="${echapper(g)}">${dispo.filter((i) => i.groupe === g).map(opt).join("")}</optgroup>`).join("");
  }

  function construirePanneau() {
    const html = CALQUES.map((c) => {
      if (c.bientot || !sources[c.cle]) {
        const raison = c.bientot ? "Bientôt disponible" : "Données indisponibles pour le moment";
        return `<section class="calque calque-inactif" data-calque="${c.cle}">
          <div class="calque-tete">
            <div class="calque-ouvrir">${iconeForme(c.forme, { gris: true })}<span class="calque-titres"><span class="calque-nom">${c.nom}</span><span class="calque-resume">${raison}</span></span></div>
            <button type="button" class="interrupteur" role="switch" aria-checked="false" disabled aria-label="Afficher les ${c.pluriel} (${raison.toLowerCase()})"></button>
          </div>
        </section>`;
      }
      const r = reglages[c.cle], id = "reglages-" + c.cle;
      const z = c.zones;
      return `<section class="calque" data-calque="${c.cle}">
        <div class="calque-tete">
          <button type="button" class="calque-ouvrir" aria-expanded="false" aria-controls="${id}">
            ${iconeForme(c.forme)}
            <span class="calque-titres"><span class="calque-nom">${c.nom}</span><span class="calque-resume"></span></span>
            <svg class="chevron" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button type="button" class="interrupteur" role="switch" data-reglage="actif" aria-checked="${r.actif}" aria-label="Afficher les ${c.pluriel}"></button>
        </div>
        <div class="calque-legende" aria-live="polite"></div>
        <div class="calque-reglages" id="${id}" hidden>
          <label class="champ" for="indicateur-${c.cle}">Couleur selon</label>
          <select id="indicateur-${c.cle}" data-reglage="indicateur">${optionsIndicateurs(c)}</select>
          <div class="champ">Établissements</div>
          <div class="puces" role="group" aria-label="Établissements affichés">
            <button type="button" data-reglage="public" aria-pressed="${r.public}">${iconeForme(c.forme, { taille: 18 })}Publics</button>
            <button type="button" data-reglage="prive" aria-pressed="${r.prive}">${iconeForme(c.forme, { taille: 18, prive: true })}Privés sous contrat</button>
          </div>
          ${c.voies ? `<div class="champ">Filière</div>
          <div class="puces" role="group" aria-label="Filières affichées">
            <button type="button" data-reglage="voie_gt" aria-pressed="${r.voie_gt}">Voie générale et techno</button>
            <button type="button" data-reglage="voie_pro" aria-pressed="${r.voie_pro}">Voie pro</button>
          </div>
          <p class="note">Selon le type du lycée dans l'annuaire de l'Éducation nationale. Les lycées polyvalents et agricoles restent affichés tant qu'une des deux voies est cochée.</p>` : ""}
          ${z ? `<div class="champ">Zones</div>
          <div class="ligne-zones${z.indisponible ? " indisponible" : ""}">
            <span>${z.libelle}</span>
            <button type="button" class="interrupteur" role="switch" data-reglage="zones" aria-checked="${z.indisponible ? "false" : r.zones}"${z.indisponible ? " disabled" : ""} aria-label="${z.libelle}"></button>
          </div>
          <p class="note">${z.note}</p>` : ""}
          <div class="legende-notes"></div>
        </div>
      </section>`;
    }).join("");
    $("calques").innerHTML = html + `<p class="cle-contour"><span>${iconeForme("carre", { taille: 16 })} contour fin : public</span>
      <span>${iconeForme("carre", { taille: 16, prive: true })} contour épais : privé sous contrat</span></p>`;
    majPanneau();
    // Sur ordinateur, les réglages des calques affichés sont ouverts d'emblée.
    if (!estMobile()) CALQUES.forEach((c) => { if (reglages[c.cle] && reglages[c.cle].actif && sources[c.cle]) ouvrirReglages(c.cle, true); });
  }

  function majPanneau() {
    CALQUES.forEach((c) => {
      const el = document.querySelector(`.calque[data-calque="${c.cle}"]:not(.calque-inactif)`);
      if (!el) return;
      const r = reglages[c.cle];
      el.querySelector(".calque-resume").textContent = resume(c);
      el.querySelector('[data-reglage="actif"]').setAttribute("aria-checked", String(r.actif));
      el.querySelectorAll(".puces [data-reglage]").forEach((b) => b.setAttribute("aria-pressed", String(r[b.dataset.reglage])));
      const z = el.querySelector('[data-reglage="zones"]:not([disabled])');
      if (z) z.setAttribute("aria-checked", String(r.zones));
      el.classList.toggle("masque", !r.actif);
      appliquerCalque(c);
    });
    const n = CALQUES.filter((c) => reglages[c.cle] && reglages[c.cle].actif && sources[c.cle]).length;
    $("compte").textContent = n === 0 ? "aucun affiché" : n === 1 ? "1 affiché" : `${n} affichés`;
  }

  function ouvrirReglages(cle, ouvrir) {
    const el = document.querySelector(`.calque[data-calque="${cle}"]`);
    if (!el || el.classList.contains("calque-inactif")) return;
    const bouton = el.querySelector(".calque-ouvrir");
    if (ouvrir && estMobile()) {
      // Sur mobile, un seul calque ouvert à la fois pour garder la carte visible.
      document.querySelectorAll('.calque .calque-ouvrir[aria-expanded="true"]').forEach((b) => {
        if (b !== bouton) { b.setAttribute("aria-expanded", "false"); $(b.getAttribute("aria-controls")).hidden = true; }
      });
    }
    bouton.setAttribute("aria-expanded", String(ouvrir));
    $(bouton.getAttribute("aria-controls")).hidden = !ouvrir;
    el.classList.toggle("ouvert", ouvrir);
  }

  function initPanneau() {
    const zone = $("calques");
    zone.addEventListener("click", (e) => {
      const ouvrir = e.target.closest(".calque-ouvrir");
      if (ouvrir && ouvrir.tagName === "BUTTON") {
        ouvrirReglages(ouvrir.closest(".calque").dataset.calque, ouvrir.getAttribute("aria-expanded") !== "true");
        $("panneau").classList.remove("replie");
        $("panneau-tete").setAttribute("aria-expanded", "true");
        return;
      }
      const b = e.target.closest("button[data-reglage]");
      if (!b || b.disabled) return;
      const cle = b.closest(".calque").dataset.calque, k = b.dataset.reglage;
      reglages[cle][k] = !reglages[cle][k];
      sauverReglages();
      majPanneau();
    });
    zone.addEventListener("change", (e) => {
      const sel = e.target.closest("select[data-reglage]");
      if (!sel) return;
      const cle = sel.closest(".calque").dataset.calque;
      reglages[cle].indicateur = sel.value;
      sauverReglages();
      majPanneau();
    });
    // Le titre « Calques » replie ou déplie tout le panneau (utile sur mobile).
    $("panneau-tete").addEventListener("click", () => {
      const replie = $("panneau").classList.toggle("replie");
      $("panneau-tete").setAttribute("aria-expanded", String(!replie));
    });
    // Les contrôles de la carte (attribution) restent au-dessus du panneau sur mobile.
    if (window.ResizeObserver) new ResizeObserver(() => {
      document.documentElement.style.setProperty("--panneau-h", $("panneau").offsetHeight + "px");
    }).observe($("panneau"));
  }

  // ---------------------------------------------------------------- fiche
  // La fiche montre un graphique d'évolution à la fois ; des boutons changent d'indicateur.
  // Médianes nationales (France métropolitaine) et par académie : la fiche collège compare à son académie.
  let medianes = { brevet: {}, ips: {}, eval6e: {} };
  let medianesAcademies = {};
  const medianesCollege = (p) => Object.assign({ brevet: {}, ips: {}, eval6e: {} }, medianesAcademies[p.academie] || medianes);
  // « académie de Lyon », « académie d'Aix-Marseille ».
  const academieDe = (a) => (/^[aeiouyéèêâîô]/i.test(a || "") ? "d'" : "de ") + (a || "");
  let medianesLycees = { gt: {}, pro: {}, ips: {} };
  let medianesLyceesAcademies = {};
  // Onglet choisi, gardé pour la fiche suivante du même type.
  const ongletsChoisis = { college: "brevet", lycee: "gt" };
  let ficheCourante = null;
  const ENCRE = "#1e2f6b", MAGENTA = "#cc4778", MAGENTA_TEXTE = "#a8335f", MEDIANE = "#8a93ad", BANDE = "#ece9f2";

  function seuilVA(cle) { return Number(VA.seuils[cle]) || 0; }
  function lectureVA(cle, v) {
    if (Math.abs(v) <= seuilVA(cle)) return VA.libelles.proche;
    return v > 0 ? VA.libelles.dessus : VA.libelles.dessous;
  }
  const num = (v) => typeof v === "number" && isFinite(v);
  const dernier = (lignes, cle) => { for (let i = lignes.length - 1; i >= 0; i--) if (num(lignes[i][cle])) return lignes[i]; return null; };
  const anneeCourte = (a) => String(a).replace(/^20(\d\d)-20(\d\d)$/, "$1-$2");

  function pasJoli(etendue) {
    const brut = etendue / 4, p = Math.pow(10, Math.floor(Math.log10(brut || 1)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= brut) return m * p;
    return 10 * p;
  }
  function echelle(vals, o) {
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (o.sym) { const m = Math.max(Math.abs(lo), Math.abs(hi), o.demiMin || 1); lo = -m; hi = m; }
    if (hi - lo < (o.etendueMin || 0)) { const c = (hi + lo) / 2; lo = c - o.etendueMin / 2; hi = c + o.etendueMin / 2; }
    const pas = pasJoli(hi - lo);
    let min = Math.floor(lo / pas) * pas, max = Math.ceil(hi / pas) * pas;
    if (o.plancher !== undefined) min = Math.max(min, o.plancher);
    if (o.plafond !== undefined) max = Math.min(max, o.plafond);
    if (max <= min) max = min + pas;
    const ticks = [];
    for (let t = min; t <= max + pas / 1000; t += pas) ticks.push(Math.round(t * 1000) / 1000);
    return { min, max, ticks };
  }

  // Graphique en courbes. Un ou deux panneaux superposés partageant l'axe des années
  // (deux panneaux quand les unités diffèrent, par exemple % et note sur 20).
  // Chaque série a sa médiane en pointillés, de la même couleur.
  function graphique(g) {
    const W = 334, L = 40, R = 70, B = 26;
    const multi = g.panneaux.length > 1;
    const hPan = multi ? 120 : 176, titreH = multi ? 18 : 0, ecart = multi ? 30 : 0;
    const H = g.panneaux.length * (titreH + hPan) + (g.panneaux.length - 1) * ecart + 12 + B;
    const n = g.labels.length, pw = W - L - R;
    const x = (i) => (n > 1 ? L + (i * pw) / (n - 1) : L + pw / 2);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${echapper(g.aria)}">`;
    g.panneaux.forEach((pan, k) => {
      const top = 12 + k * (titreH + hPan + ecart) + titreH;
      const tous = [].concat(...pan.series.map((s) => s.vals.concat(s.med || [])), pan.bande || []).filter(num);
      const e = echelle(tous, pan.echelle);
      const y = (v) => top + hPan * (1 - (v - e.min) / (e.max - e.min));
      const trace = (vals) => {
        let d = "", leve = true;
        vals.forEach((v, i) => { if (!num(v)) { leve = true; return; } d += (leve ? "M" : "L") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " "; leve = false; });
        return d.trim();
      };
      if (multi) svg += `<text x="${L - 34}" y="${top - 8}" class="titre-panneau">${echapper(pan.titre)}</text>`;
      if (pan.bande) svg += `<rect x="${L}" y="${y(pan.bande[1]).toFixed(1)}" width="${pw}" height="${(y(pan.bande[0]) - y(pan.bande[1])).toFixed(1)}" fill="${BANDE}"/>`;
      e.ticks.forEach((t) => {
        svg += `<line x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="${t === 0 && pan.zero ? "#56648f" : "#e3e7f0"}" stroke-width="1"/>`;
        svg += `<text x="${L - 6}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${echapper(pan.tick(t))}</text>`;
      });
      pan.series.forEach((s) => {
        if (s.med && s.med.some(num)) svg += `<path d="${trace(s.med)}" fill="none" stroke="${s.couleur}" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="4 3"/>`;
      });
      pan.series.slice().reverse().forEach((s) => {
        svg += `<path d="${trace(s.vals)}" fill="none" stroke="${s.couleur}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
        s.vals.forEach((v, i) => { if (num(v)) svg += `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="4" fill="${s.couleur}"/>`; });
      });
      // Noms des courbes au bout des lignes, écartés s'ils se chevauchent.
      const fins = [];
      pan.series.forEach((s) => { for (let i = s.vals.length - 1; i >= 0; i--) if (num(s.vals[i])) { fins.push({ txt: s.nom, y: y(s.vals[i]), couleur: s.texte || s.couleur }); break; } });
      fins.sort((a, b) => a.y - b.y);
      for (let i = 1; i < fins.length; i++) if (fins[i].y - fins[i - 1].y < 15) fins[i].y = fins[i - 1].y + 15;
      fins.forEach((f) => { svg += `<text x="${W - R + 8}" y="${(f.y + 4).toFixed(1)}" style="fill:${f.couleur};font-weight:700">${echapper(f.txt)}</text>`; });
    });
    // Au-delà de 6 années, une étiquette sur deux (la dernière toujours affichée).
    g.labels.forEach((l, i) => { if (n <= 6 || (n - 1 - i) % 2 === 0) svg += `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${echapper(l)}</text>`; });
    return svg + "</svg>";
  }

  function tableau(colonnes, lignes) {
    if (!lignes || !lignes.length) return "";
    const th = colonnes.map((c) => `<th scope="col">${c.nom}</th>`).join("");
    const tr = lignes.map((l) => "<tr>" + colonnes.map((c, i) => {
      const v = l[c.cle];
      const txt = v === null || v === undefined ? "–" : (c.fmt ? c.fmt(v) : echapper(v));
      return i === 0 ? `<th scope="row">${txt}</th>` : `<td>${txt}</td>`;
    }).join("") + "</tr>").join("");
    return `<table class="historique"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
  }

  // Contenu de chaque onglet, à partir de l'historique du collège et des médianes.
  function onglets(p, hist) {
    const medianes = medianesCollege(p);
    const pct = (v) => fr(v, 1) + " %";
    const signe1 = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + fr(Math.abs(v), 1);
    const tickSigne = (nd) => (t) => (t > 0 ? "+" : t < 0 ? "−" : "") + fr(Math.abs(t), nd);
    const br = hist.brevet || [], ip = hist.ips || [], ev = hist.eval6e || [];
    const medB = (cle) => br.map((r) => (medianes.brevet[r.session] || {})[cle]);
    const medE = (cle) => ev.map((r) => (medianes.eval6e[r.annee] || {})[cle]);
    const col = (lignes, cle) => lignes.map((r) => r[cle]);
    const decrire = (lignes, cleA, cle, fmt) => lignes.map((r) => `${r[cleA]} ${num(r[cle]) ? fmt(r[cle]) : "non publié"}`).join(", ");
    const res = [];

    if (br.some((r) => num(r.taux_reussite) || num(r.note_ecrit))) {
      const d = dernier(br, "taux_reussite") || dernier(br, "note_ecrit"), m = medianes.brevet[d.session] || {};
      const contexte = [];
      if (num(d.taux_mentions)) contexte.push(`Mentions : ${pct(d.taux_mentions)}.`);
      if (num(d.note_ecrit)) contexte.push(`Note aux écrits : ${fr(d.note_ecrit, 1)} / 20.`);
      const meds = [];
      if (num(m.taux_reussite)) meds.push(`réussite ${pct(m.taux_reussite)}`);
      if (num(m.taux_mentions)) meds.push(`mentions ${pct(m.taux_mentions)}`);
      if (num(m.note_ecrit)) meds.push(`écrits ${fr(m.note_ecrit, 1)}`);
      if (meds.length) contexte.push(`Médianes de l'académie : ${meds.join(", ")}.`);
      res.push({
        cle: "brevet", nom: "Brevet", titre: "Résultats au brevet",
        valeur: num(d.taux_reussite) ? pct(d.taux_reussite) : "–", unite: `réussite ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session),
          aria: `Réussite au brevet : ${decrire(br, "session", "taux_reussite", pct)}. Mentions : ${decrire(br, "session", "taux_mentions", pct)}. Note aux écrits : ${decrire(br, "session", "note_ecrit", (v) => fr(v, 1))}.`,
          panneaux: [
            { titre: "Réussite et mentions (%)", tick: (t) => fr(t, 0) + " %", echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: [
              { vals: col(br, "taux_reussite"), med: medB("taux_reussite"), couleur: ENCRE, nom: "réussite" },
              { vals: col(br, "taux_mentions"), med: medB("taux_mentions"), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "mentions" },
            ] },
            { titre: "Note aux écrits (sur 20)", tick: (t) => fr(t, 0), echelle: { plancher: 0, plafond: 20, etendueMin: 4 }, series: [
              { vals: col(br, "note_ecrit"), med: medB("note_ecrit"), couleur: ENCRE, nom: "écrits" },
            ] },
          ] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "taux_reussite", nom: "Réussite", fmt: pct }, { cle: "taux_mentions", nom: "Mentions", fmt: pct },
          { cle: "note_ecrit", nom: "Écrits", fmt: (v) => fr(v, 1) }, { cle: "candidats", nom: "Candidats", fmt: (v) => fr(v, 0) }], br),
      });
    }

    if (ip.some((r) => num(r.ips))) {
      const d = dernier(ip, "ips"), m = medianes.ips[d.annee];
      const contexte = [];
      if (num(m)) contexte.push(`Médiane de l'académie : ${fr(m, 1)}.`);
      if (num(d.ecart_type)) contexte.push(`Écart-type : ${fr(d.ecart_type, 1)}.`);
      res.push({
        cle: "ips", nom: "IPS", titre: "Indice de position sociale",
        valeur: fr(d.ips, 1), unite: d.annee, contexte: contexte.join(" "),
        graphe: { labels: ip.map((r) => anneeCourte(r.annee)), aria: `IPS par année : ${decrire(ip, "annee", "ips", (v) => fr(v, 1))}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { etendueMin: 20 }, series: [
            { vals: col(ip, "ips"), med: ip.map((r) => medianes.ips[r.annee]), couleur: ENCRE, nom: "IPS" },
          ] }] },
        table: tableau([{ cle: "annee", nom: "Année" }, { cle: "ips", nom: "IPS", fmt: (v) => fr(v, 1) }, { cle: "ecart_type", nom: "Écart-type", fmt: (v) => fr(v, 1) }], ip),
      });
    }

    if (br.some((r) => num(r.va_reussite) || num(r.va_note))) {
      const sR = seuilVA("va_reussite"), sN = seuilVA("va_note");
      const dR = dernier(br, "va_reussite"), dN = dernier(br, "va_note"), d = dR || dN;
      const contexte = [];
      if (dR) contexte.push(`Réussite : ${lectureVA("va_reussite", dR.va_reussite)}.`);
      if (dN) contexte.push(`Note aux écrits : ${signe1(dN.va_note)} point, ${lectureVA("va_note", dN.va_note)}.`);
      contexte.push(`Zones grisées : écart faible (${signe1(-sR)} à ${signe1(sR)} points pour la réussite, ${signe1(-sN)} à ${signe1(sN)} pour les écrits).`);
      res.push({
        cle: "va", nom: "Valeur ajoutée", titre: "Valeur ajoutée",
        valeur: dR ? signe(dR.va_reussite) : signe1(dN.va_note), unite: dR ? `points de réussite, ${d.session}` : `point aux écrits, ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session),
          aria: `Valeur ajoutée sur la réussite : ${decrire(br, "session", "va_reussite", signe)}. Sur la note aux écrits : ${decrire(br, "session", "va_note", signe1)}.`,
          panneaux: [
            { titre: "Sur la réussite (points de %)", tick: tickSigne(0), bande: [-sR, sR], zero: true, echelle: { sym: true, demiMin: Math.max(sR * 3, 4) }, series: [
              { vals: col(br, "va_reussite"), med: medB("va_reussite"), couleur: ENCRE, nom: "réussite" },
            ] },
            { titre: "Sur la note aux écrits (points sur 20)", tick: tickSigne(1), bande: [-sN, sN], zero: true, echelle: { sym: true, demiMin: Math.max(sN * 3, 0.5) }, series: [
              { vals: col(br, "va_note"), med: medB("va_note"), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "écrits" },
            ] },
          ] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "va_reussite", nom: "Réussite", fmt: signe }, { cle: "va_note", nom: "Écrits", fmt: signe1 }], br),
      });
    }

    if (ev.some((r) => num(r.fr) || num(r.ma))) {
      const d = dernier(ev, "fr") || dernier(ev, "ma"), m = medianes.eval6e[d.annee] || {};
      const contexte = [];
      if (num(d.ma)) contexte.push(`Mathématiques : ${fr(d.ma, 0)}.`);
      const meds = [];
      if (num(m.fr)) meds.push(`français ${fr(m.fr, 0)}`);
      if (num(m.ma)) meds.push(`maths ${fr(m.ma, 0)}`);
      if (meds.length) contexte.push(`Médianes de l'académie : ${meds.join(", ")}.`);
      res.push({
        cle: "eval", nom: "Évaluations 6e", titre: "Évaluations de 6e",
        valeur: num(d.fr) ? fr(d.fr, 0) : "–", unite: `français ${d.annee}`, contexte: contexte.join(" "),
        graphe: { labels: ev.map((r) => r.annee),
          aria: `Scores moyens à l'entrée en 6e. Français : ${decrire(ev, "annee", "fr", (v) => fr(v, 0))}. Mathématiques : ${decrire(ev, "annee", "ma", (v) => fr(v, 0))}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { etendueMin: 40 }, series: [
            { vals: col(ev, "fr"), med: medE("fr"), couleur: ENCRE, nom: "français" },
            { vals: col(ev, "ma"), med: medE("ma"), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "maths" },
          ] }] },
        table: tableau([{ cle: "annee", nom: "Année" }, { cle: "fr", nom: "Français", fmt: (v) => fr(v, 0) }, { cle: "ma", nom: "Maths", fmt: (v) => fr(v, 0) }], ev),
      });
    }

    if (br.some((r) => num(r.score))) {
      const d = dernier(br, "score"), m = (medianes.brevet[d.session] || {}).score;
      const contexte = [];
      if (num(d.rang)) contexte.push(`${d.rang}e sur ${fr(d.nb, 0)} collèges de France métropolitaine en ${d.session}` +
        (num(d.rang_acad) ? `, ${d.rang_acad}e sur ${fr(d.nb_acad, 0)} dans l'académie ${academieDe(p.academie)}.` : "."));
      if (num(m)) contexte.push(`Médiane de l'académie : ${fr(m, 1)}.`);
      contexte.push("Moyenne des taux de réussite, de mentions et de mentions très bien : à lire avec précaution.");
      res.push({
        cle: "score", nom: "Score", titre: "Score",
        valeur: fr(d.score, 1), unite: d.session, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session), aria: `Score agrégé par session : ${decrire(br, "session", "score", (v) => fr(v, 1))}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: [
            { vals: col(br, "score"), med: medB("score"), couleur: ENCRE, nom: "score" },
          ] }] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "score", nom: "Score", fmt: (v) => fr(v, 1) }, { cle: "rang", nom: "Rang national", fmt: (v) => fr(v, 0) }, { cle: "nb", nom: "Sur", fmt: (v) => fr(v, 0) },
          { cle: "rang_acad", nom: "Rang académie", fmt: (v) => fr(v, 0) }, { cle: "nb_acad", nom: "Sur", fmt: (v) => fr(v, 0) }], br),
      });
    }
    return res;
  }

  // Onglets de la fiche lycée. Voie générale et technologique en bleu foncé, voie pro en magenta,
  // chaque courbe avec sa médiane (lycées des deux académies, même voie, même année).
  function tableauDetail(titre, colonnes, lignes) {
    if (!lignes || !lignes.length) return "";
    const th = colonnes.map((c) => `<th scope="col">${c.nom}</th>`).join("");
    const tr = lignes.map((l) => `<tr${l.sous ? ' class="sous"' : ""}>` + colonnes.map((c, i) => {
      const v = l[c.cle];
      const txt = v === null || v === undefined || v === "" ? "–" : (c.fmt ? c.fmt(v) : echapper(v));
      return i === 0 ? `<th scope="row">${txt}</th>` : `<td>${txt}</td>`;
    }).join("") + "</tr>").join("");
    return `<table class="historique detail"><caption>${titre}</caption><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
  }

  function ongletsLycee(p, hist) {
    const pct = (v) => fr(v, 0) + " %";
    const tickPct = (t) => fr(t, 0) + " %";
    const tickSigne = (t) => (t > 0 ? "+" : t < 0 ? "−" : "") + fr(Math.abs(t), 0);
    const M = Object.assign({ gt: {}, pro: {}, ips: {} }, medianesLyceesAcademies[p.academie] || medianesLycees);
    const gt = hist.gt || [], pro = hist.pro || [], ip = hist.ips || [], sc = hist.score || [];
    const decrire = (lignes, cleA, cle, fmt) => lignes.map((r) => `${r[cleA]} ${num(r[cle]) ? fmt(r[cle]) : "non publié"}`).join(", ");
    // Axe commun aux deux voies : toutes les sessions présentes dans l'une ou l'autre.
    const sessions = [...new Set(gt.concat(pro).map((r) => r.session))].sort();
    const parSession = (lignes) => new Map(lignes.map((r) => [r.session, r]));
    const gS = parSession(gt), pS = parSession(pro);
    const serie = (m, cle) => sessions.map((s) => (m.get(s) || {})[cle]);
    const med = (voie, cle, liste) => (liste || sessions).map((s) => ((M[voie] || {})[s] || {})[cle]);
    const res = [];
    const VOIES = [
      { cle: "gt", m: gS, lignes: gt, nom: "voie GT", couleur: ENCRE },
      { cle: "pro", m: pS, lignes: pro, nom: "voie pro", couleur: MAGENTA, texte: MAGENTA_TEXTE },
    ];

    // Bac général et technologique, puis bac pro : réussite et mentions.
    [
      { voie: VOIES[0], cle: "gt", nom: "Bac général", titre: "Bac général et technologique",
        detail: () => tableauDetail(`Par série, session ${gt[gt.length - 1].session}`,
          [{ cle: "nom", nom: "Série" }, { cle: "presents", nom: "Candidats", fmt: (v) => fr(v, 0) }, { cle: "reussite", nom: "Réussite", fmt: pct },
            { cle: "mentions", nom: "Mentions", fmt: pct }, { cle: "va", nom: "VA", fmt: signe0 }], hist.series_gt) },
      { voie: VOIES[1], cle: "pro", nom: "Bac pro", titre: "Bac professionnel",
        detail: () => tableauDetail(`Par domaine, session ${pro[pro.length - 1].session}`,
          [{ cle: "nom", nom: "Domaine" }, { cle: "presents", nom: "Candidats", fmt: (v) => fr(v, 0) }, { cle: "reussite", nom: "Réussite", fmt: pct }],
          (hist.domaines_pro || []).flatMap((d) => [d].concat((d.details || []).map((x) => Object.assign({ sous: true }, x))))) },
    ].forEach((o) => {
      const L = o.voie.lignes;
      if (!L.some((r) => num(r.reussite))) return;
      const d = dernier(L, "reussite"), m = (M[o.voie.cle] || {})[d.session] || {};
      const contexte = [];
      if (num(d.mentions)) contexte.push(`Mentions : ${pct(d.mentions)}.`);
      if (num(d.presents)) contexte.push(`${fr(d.presents, 0)} candidats.`);
      const meds = [];
      if (num(m.reussite)) meds.push(`réussite ${pct(m.reussite)}`);
      if (num(m.mentions)) meds.push(`mentions ${pct(m.mentions)}`);
      if (meds.length) contexte.push(`Médianes de l'académie : ${meds.join(", ")}.`);
      const lab = L.map((r) => r.session);
      res.push({
        cle: o.cle, nom: o.nom, titre: o.titre,
        valeur: pct(d.reussite), unite: `réussite ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: lab,
          aria: `${o.titre}. Réussite : ${decrire(L, "session", "reussite", pct)}. Mentions : ${decrire(L, "session", "mentions", pct)}.`,
          panneaux: [{ tick: tickPct, echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: [
            { vals: L.map((r) => r.reussite), med: med(o.voie.cle, "reussite", lab), couleur: ENCRE, nom: "réussite" },
            { vals: L.map((r) => r.mentions), med: med(o.voie.cle, "mentions", lab), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "mentions" },
          ] }] },
        detail: o.detail(),
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "reussite", nom: "Réussite", fmt: pct }, { cle: "mentions", nom: "Mentions", fmt: pct },
          { cle: "presents", nom: "Candidats", fmt: (v) => fr(v, 0) }], L),
      });
    });

    // Accès de la seconde au bac, les deux voies sur le même graphique.
    const voiesAcces = VOIES.filter((v) => v.lignes.some((r) => num(r.acces)));
    if (voiesAcces.length) {
      const v0 = voiesAcces[0], d = dernier(v0.lignes, "acces");
      const contexte = ["Part des élèves de seconde qui obtiennent le bac en restant dans le lycée."];
      voiesAcces.slice(1).forEach((v) => { const x = dernier(v.lignes, "acces"); contexte.push(`Voie pro : ${pct(x.acces)} en ${x.session}.`); });
      res.push({
        cle: "acces", nom: "Accès au bac", titre: "Accès de la seconde au bac",
        valeur: pct(d.acces), unite: `${v0.nom}, ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: sessions,
          aria: "Taux d'accès de la seconde au bac. " + voiesAcces.map((v) => `${v.nom} : ${decrire(v.lignes, "session", "acces", pct)}.`).join(" "),
          panneaux: [{ tick: tickPct, echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: voiesAcces.map((v) => (
            { vals: serie(v.m, "acces"), med: med(v.cle, "acces"), couleur: v.couleur, texte: v.texte, nom: v.nom })) }] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "gt", nom: "Voie GT", fmt: pct }, { cle: "pro", nom: "Voie pro", fmt: pct }],
          sessions.map((s) => ({ session: s, gt: (gS.get(s) || {}).acces, pro: (pS.get(s) || {}).acces }))),
      });
    }

    // Valeur ajoutée : un panneau pour la réussite, un pour l'accès au bac.
    const aVA = (cle) => VOIES.filter((v) => v.lignes.some((r) => num(r[cle])));
    if (aVA("va_reussite").length || aVA("va_acces").length) {
      const s = Number(VA.seuils.gt_va_reussite ?? 2);
      const v0 = aVA("va_reussite")[0] || aVA("va_acces")[0];
      const cleV = aVA("va_reussite").length ? "va_reussite" : "va_acces";
      const d = dernier(v0.lignes, cleV);
      const contexte = [];
      VOIES.forEach((v) => {
        const x = dernier(v.lignes, "va_reussite");
        if (x) contexte.push(`Réussite ${v.nom} : ${signe0(x.va_reussite)}, ${lectureVA(v.cle + "_va_reussite", x.va_reussite)}.`);
      });
      contexte.push(`Zones grisées : écart faible (${tickSigne(-s)} à ${tickSigne(s)} points).`);
      const panneau = (cle, titre) => ({ titre, tick: tickSigne, bande: [-s, s], zero: true, echelle: { sym: true, demiMin: Math.max(s * 3, 6) },
        series: aVA(cle).map((v) => ({ vals: serie(v.m, cle), med: med(v.cle, cle), couleur: v.couleur, texte: v.texte, nom: v.nom })) });
      res.push({
        cle: "va", nom: "Valeur ajoutée", titre: "Valeur ajoutée",
        valeur: signe0(d[cleV]), unite: `${cleV === "va_reussite" ? "réussite" : "accès"} ${v0.nom}, ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: sessions,
          aria: "Valeur ajoutée. " + VOIES.map((v) => `Réussite ${v.nom} : ${decrire(v.lignes, "session", "va_reussite", signe0)}. Accès ${v.nom} : ${decrire(v.lignes, "session", "va_acces", signe0)}.`).join(" "),
          panneaux: [aVA("va_reussite").length && panneau("va_reussite", "Sur la réussite (points de %)"), aVA("va_acces").length && panneau("va_acces", "Sur l'accès au bac (points de %)")].filter(Boolean) },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "gr", nom: "Réussite GT", fmt: signe0 }, { cle: "ga", nom: "Accès GT", fmt: signe0 },
          { cle: "gm", nom: "Mentions GT", fmt: signe0 }, { cle: "pr", nom: "Réussite pro", fmt: signe0 }, { cle: "pa", nom: "Accès pro", fmt: signe0 }],
          sessions.map((x) => { const g = gS.get(x) || {}, q = pS.get(x) || {}; return { session: x, gr: g.va_reussite, ga: g.va_acces, gm: g.va_mentions, pr: q.va_reussite, pa: q.va_acces }; })),
      });
    }

    // IPS : voie GT et voie pro ; à défaut, IPS du lycée entier.
    if (ip.some((r) => num(r.etab) || num(r.gt) || num(r.pro))) {
      const ans = ip.map((r) => r.annee);
      const medI = (cle) => ans.map((a) => ((M.ips || {})[a] || {})[cle]);
      const series = [];
      if (ip.some((r) => num(r.gt))) series.push({ vals: ip.map((r) => r.gt), med: medI("gt"), couleur: ENCRE, nom: "voie GT" });
      if (ip.some((r) => num(r.pro))) series.push({ vals: ip.map((r) => r.pro), med: medI("pro"), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "voie pro" });
      if (!series.length) series.push({ vals: ip.map((r) => r.etab), med: medI("etab"), couleur: ENCRE, nom: "lycée" });
      const d = ip[ip.length - 1], m = (M.ips || {})[d.annee] || {};
      const principal = num(d.gt) ? ["gt", "voie GT"] : num(d.pro) ? ["pro", "voie pro"] : ["etab", "lycée"];
      const contexte = [];
      if (num(d.gt) && num(d.pro)) contexte.push(`Voie pro : ${fr(d.pro, 1)}.`);
      if (num(d.etab)) contexte.push(`Lycée entier : ${fr(d.etab, 1)}${num(m.etab) ? ` (médiane de l'académie ${fr(m.etab, 1)})` : ""}.`);
      if (num(d.postbac)) contexte.push(`Post-bac : ${fr(d.postbac, 1)}.`);
      if (num(d.et_gt)) contexte.push(`Écart-type voie GT : ${fr(d.et_gt, 1)}.`);
      res.push({
        cle: "ips", nom: "IPS", titre: "Indice de position sociale",
        valeur: fr(d[principal[0]], 1), unite: `${principal[1]}, ${d.annee}`, contexte: contexte.join(" "),
        graphe: { labels: ans.map(anneeCourte),
          aria: `IPS par année. ${series.map((x) => `${x.nom} : ${x.vals.map((v, i) => `${ans[i]} ${num(v) ? fr(v, 1) : "non publié"}`).join(", ")}`).join(". ")}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { etendueMin: 20 }, series }] },
        table: tableau([{ cle: "annee", nom: "Année" }, { cle: "gt", nom: "Voie GT", fmt: (v) => fr(v, 1) }, { cle: "pro", nom: "Voie pro", fmt: (v) => fr(v, 1) },
          { cle: "etab", nom: "Lycée", fmt: (v) => fr(v, 1) }, { cle: "postbac", nom: "Post-bac", fmt: (v) => fr(v, 1) }], ip),
      });
    }

    // Score de la voie générale.
    if (sc.some((r) => num(r.score))) {
      const d = dernier(sc, "score"), m = ((M.gt || {})[d.session] || {}).score;
      const contexte = [];
      if (num(d.rang)) contexte.push(`${d.rang}e sur ${fr(d.nb, 0)} lycées de France métropolitaine en ${d.session}` +
        (num(d.rang_acad) ? `, ${d.rang_acad}e sur ${fr(d.nb_acad, 0)} dans l'académie ${academieDe(p.academie)}.` : "."));
      if (num(m)) contexte.push(`Médiane de l'académie : ${fr(m, 1)}.`);
      contexte.push("Moyenne des taux de réussite, de mentions et de mentions très bien au bac général : à lire avec précaution.");
      const lab = sc.map((r) => r.session);
      res.push({
        cle: "score", nom: "Score", titre: "Score de la voie générale",
        valeur: fr(d.score, 1), unite: d.session, contexte: contexte.join(" "),
        graphe: { labels: lab, aria: `Score de la voie générale par session : ${decrire(sc, "session", "score", (v) => fr(v, 1))}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: [
            { vals: sc.map((r) => r.score), med: med("gt", "score", lab), couleur: ENCRE, nom: "score" },
          ] }] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "score", nom: "Score", fmt: (v) => fr(v, 1) }, { cle: "tb", nom: "Mentions TB", fmt: (v) => fr(v, 1) + " %" },
          { cle: "rang", nom: "Rang national", fmt: (v) => fr(v, 0) }, { cle: "nb", nom: "Sur", fmt: (v) => fr(v, 0) },
          { cle: "rang_acad", nom: "Rang académie", fmt: (v) => fr(v, 0) }, { cle: "nb_acad", nom: "Sur", fmt: (v) => fr(v, 0) }], sc),
      });
    }
    return res;
  }

  function afficherOnglet() {
    const liste = ficheCourante.onglets;
    const o = liste.find((x) => x.cle === ongletsChoisis[ficheCourante.type]) || liste[0];
    document.querySelectorAll("#fiche .onglets button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.onglet === o.cle)));
    const avecMediane = o.graphe.panneaux.some((pan) => pan.series.some((s) => s.med && s.med.some(num)));
    $("fiche-graphe").innerHTML = `
      <div class="graphe-tete">
        <h3>${o.titre}</h3>
        <p class="valeur">${echapper(o.valeur)} <small>${echapper(o.unite)}</small></p>
      </div>
      <p class="graphe-contexte">${echapper(o.contexte)}</p>
      <div class="graphe">${graphique(o.graphe)}</div>
      <div class="legende-graphe" aria-hidden="true">
        <span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${ENCRE}" stroke-width="2.5" stroke-linecap="round"/></svg>Trait plein : ${ficheCourante.type === "lycee" ? "ce lycée" : "ce collège"}</span>
        ${avecMediane ? `<span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${ENCRE}" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="4 3"/></svg>Pointillés de même couleur : médiane de l'académie ${echapper(academieDe(ficheCourante.p.academie))}</span>` : ""}
      </div>
      ${o.detail || ""}
      <details class="valeurs"><summary>Valeurs par année</summary>${o.table}</details>`;
  }

  function surlignerSecteur(uai) {
    if (carte.getLayer("secteurs-surligne")) carte.setFilter("secteurs-surligne", ["==", ["get", "uai"], uai || ""]);
  }

  // Historiques des collèges et des lycées, un fichier par type et par département, chargé à la première fiche ouverte.
  const fichesDep = new Map();
  function chargerFiches(dep, type = "colleges") {
    const cle = `${type}-${dep}`;
    if (!fichesDep.has(cle)) {
      fichesDep.set(cle, fetch(`data/fiches/${cle}.json`.replace(/[^\w\-./]/g, encodeURIComponent))
        .then((r) => (r.ok ? r.json() : r.status === 404 ? {} : Promise.reject(r.status)))
        .catch((e) => { fichesDep.delete(cle); throw e; }));
    }
    return fichesDep.get(cle);
  }

  function ouvrirFiche(p) {
    surlignerSecteur(p.uai);
    const type = p.secteur === "public" ? "Collège public" : "Collège privé sous contrat";
    const tete = `
      <h2 id="fiche-nom">${echapper(p.nom)}</h2>
      <p class="lieu">${type}, ${echapper(p.commune)} (${echapper(p.departement)})</p>`;
    ficheCourante = { type: "college", p, onglets: [] };
    $("fiche-contenu").innerHTML = tete + `<p class="chargement">Chargement des indicateurs…</p>`;
    const fiche = $("fiche");
    fiche.hidden = false;
    document.body.classList.add("fiche-ouverte");
    fiche.scrollTop = 0;
    $("fermer").focus({ preventScroll: true });
    chargerFiches(p.dep).then((dep) => {
      if (!ficheCourante || ficheCourante.p.uai !== p.uai) return;  // une autre fiche a été ouverte entre-temps
      remplirFiche(p, tete, (dep[p.uai] || {}).hist || {});
    }).catch((e) => {
      console.warn("Fiches indisponibles", e);
      if (ficheCourante && ficheCourante.p.uai === p.uai)
        $("fiche-contenu").innerHTML = tete + `<p>Les indicateurs de ce collège n'ont pas pu être chargés. Vérifiez la connexion puis rouvrez la fiche.</p>`;
    });
  }

  function remplirFiche(p, tete, hist) {
    const liste = onglets(p, hist);
    ficheCourante = { type: "college", p, onglets: liste };
    $("fiche-contenu").innerHTML = tete + `
      ${liste.length ? `
        <div class="onglets" role="group" aria-label="Indicateur affiché">
          ${liste.map((o) => `<button type="button" data-onglet="${o.cle}" aria-pressed="false">${o.nom}</button>`).join("")}
        </div>
        <div id="fiche-graphe" aria-live="polite"></div>` :
        `<p>Aucun indicateur n'est publié pour ce collège. C'est souvent le cas des établissements récents ou à petit effectif.</p>`}
      <p class="renvoi"><a href="documentation-colleges.html">Comprendre ces indicateurs</a></p>`;
    if (liste.length) afficherOnglet();
  }

  $("fiche-contenu").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-onglet]");
    if (!b || !ficheCourante) return;
    ongletsChoisis[ficheCourante.type] = b.dataset.onglet;  // gardé pour la fiche suivante
    afficherOnglet();
  });

  // Fiche lycée : effectifs, puis un graphique par indicateur, comme pour les collèges.
  function ouvrirFicheLycee(p) {
    surlignerSecteur(null);
    ficheCourante = { type: "lycee", p, onglets: [] };
    $("fiche-contenu").innerHTML = `<h2 id="fiche-nom">${echapper(p.nom)}</h2><p class="chargement">Chargement des indicateurs…</p>`;
    const fiche = $("fiche");
    fiche.hidden = false;
    document.body.classList.add("fiche-ouverte");
    fiche.scrollTop = 0;
    $("fermer").focus({ preventScroll: true });
    chargerFiches(p.dep, "lycees").then((dep) => {
      if (!ficheCourante || ficheCourante.p.uai !== p.uai) return;
      remplirFicheLycee(p, (dep[p.uai] || {}).hist || {});
    }).catch((e) => {
      console.warn("Fiches indisponibles", e);
      if (ficheCourante && ficheCourante.p.uai === p.uai)
        $("fiche-contenu").innerHTML = `<h2 id="fiche-nom">${echapper(p.nom)}</h2><p>Les indicateurs de ce lycée n'ont pas pu être chargés. Vérifiez la connexion puis rouvrez la fiche.</p>`;
    });
  }

  function remplirFicheLycee(p, hist) {
    const liste = ongletsLycee(p, hist);
    ficheCourante = { type: "lycee", p, onglets: liste };
    const secteur = p.secteur === "public" ? "public" : "privé sous contrat";
    const chiffres = [];
    if (num(p.eff_gt)) chiffres.push(["Voie générale et techno", fr(p.eff_gt, 0), "élèves"]);
    if (num(p.eff_pro)) chiffres.push(["Voie professionnelle", fr(p.eff_pro, 0), "élèves"]);
    if (num(p.score)) chiffres.push(["Score voie générale", fr(p.score, 1), num(p.rang) ? `${p.rang}e sur ${fr(p.nb, 0)} en France` : p.session_score]);
    $("fiche-contenu").innerHTML = `
      <h2 id="fiche-nom">${echapper(p.nom)}</h2>
      <p class="lieu">${echapper(p.type || "Lycée")} ${secteur}, ${echapper(p.commune)} (${echapper(p.departement)})</p>
      ${chiffres.length ? `<dl class="cles">${chiffres.map(([t, v, d]) => `<div><dt>${t}</dt><dd>${v}</dd><dd class="detail">${echapper(d || "")}</dd></div>`).join("")}</dl>` : ""}
      ${liste.length ? `
        <div class="onglets" role="group" aria-label="Indicateur affiché">
          ${liste.map((o) => `<button type="button" data-onglet="${o.cle}" aria-pressed="false">${o.nom}</button>`).join("")}
        </div>
        <div id="fiche-graphe" aria-live="polite"></div>` :
        `<p>Aucun indicateur n'est publié pour ce lycée. C'est souvent le cas des établissements récents, à petit effectif, ou sans classe de terminale.</p>`}
      <p class="renvoi"><a href="documentation-lycees.html">Comprendre ces indicateurs</a></p>`;
    if (liste.length) afficherOnglet();
  }

  function fermerFiche() {
    surlignerSecteur(null);
    $("fiche").hidden = true;
    document.body.classList.remove("fiche-ouverte");
  }

  // ---------------------------------------------------------------- recherche
  // Un seul champ : collèges et communes cherchés dans les données chargées,
  // adresses via le service de géocodage de l'IGN (Géoplateforme).
  const GEOCODAGE_COMPLETION = "https://data.geopf.fr/geocodage/completion/";
  const GEOCODAGE_RECHERCHE = "https://data.geopf.fr/geocodage/search";
  // Adresses de France métropolitaine (l'outre-mer viendra plus tard).
  const enMetropole = (code) => /^(\d{2}|2[AB])/.test(code) && !/^9[78]/.test(code);
  const normaliser = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  let repereAdresse = null;

  // Centre la carte sur un point en laissant de la place à la fiche (en bas sur mobile, à droite sur ordinateur).
  function centrer(coord, zoom) {
    const mobile = window.innerWidth < 760;
    carte.flyTo({ center: coord, zoom, duration: 600,
      padding: mobile ? { top: 20, bottom: Math.round(window.innerHeight * 0.55), left: 0, right: 0 } : { top: 0, bottom: 0, left: 380, right: 420 } });
  }

  function distanceKm(a, b) {
    const R = 6371, rad = Math.PI / 180;
    const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  // Nom sans le type en tête (« Lycée polyvalent Louis Bascan » -> « louis bascan »), pour classer les résultats.
  const PREFIXE = /^(college|lycee)( (polyvalent|professionnel|general et technologique|general|technologique|des metiers|agricole|d enseignement general et technologique))? /;

  function chercherLocal(q) {
    const mots = normaliser(q).split(" ").filter(Boolean);
    const vide = { colleges: [], lycees: [], communes: [] };
    if (!mots.length) return vide;
    const trouves = { colleges: [], lycees: [] }, communes = new Map();
    ["colleges", "lycees"].forEach((type) => {
      if (!sources[type]) return;
      sources[type].features.forEach((f) => {
        const p = f.properties;
        if (mots.every((m) => normaliser(p.nom + " " + p.commune).includes(m))) {
          trouves[type].push({ f, rang: normaliser(p.nom).replace(PREFIXE, "").startsWith(mots[0]) ? 0 : 1 });
        }
        const com = normaliser(p.commune);
        if (mots.every((m) => com.includes(m))) {
          const cle = p.commune + "|" + p.dep;
          if (!communes.has(cle)) communes.set(cle, { nom: p.commune, departement: p.departement, rang: com.startsWith(mots[0]) ? 0 : 1, features: [], colleges: 0, lycees: 0 });
          const c = communes.get(cle);
          c.features.push(f);
          c[type]++;
        }
      });
    });
    const tri = (a, b) => a.rang - b.rang || a.f.properties.nom.localeCompare(b.f.properties.nom, "fr");
    const listeCom = [...communes.values()].sort((a, b) => a.rang - b.rang || a.nom.localeCompare(b.nom, "fr"));
    return {
      colleges: trouves.colleges.sort(tri).slice(0, 4).map((c) => c.f),
      lycees: trouves.lycees.sort(tri).slice(0, 4).map((c) => c.f),
      communes: listeCom.slice(0, 3),
    };
  }

  // Adresses : service d'autocomplétion, puis recherche classique en secours.
  async function chercherAdresses(q, signal) {
    try {
      const url = `${GEOCODAGE_COMPLETION}?text=${encodeURIComponent(q)}&type=StreetAddress&maximumResponses=5&terr=METROPOLE`;
      const r = await fetch(url, { signal });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      const res = (j.results || []).filter((a) => num(a.x) && num(a.y)).map((a) => ({
        libelle: a.fulltext, detail: a.zipcode && String(a.fulltext).includes(a.zipcode) ? "" : [a.zipcode, a.city].filter(Boolean).join(" "), coord: [a.x, a.y],
      }));
      if (res.length) return res;
    } catch (e) { if (e.name === "AbortError") throw e; }
    const r = await fetch(`${GEOCODAGE_RECHERCHE}?q=${encodeURIComponent(q)}&limit=8&index=address`, { signal });
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    return (j.features || [])
      .filter((f) => enMetropole(String(f.properties.postcode || f.properties.citycode || "")))
      .slice(0, 5)
      .map((f) => ({ libelle: f.properties.label, detail: f.properties.context || "", coord: f.geometry.coordinates }));
  }

  function initRecherche() {
    const champ = $("recherche"), liste = $("suggestions");
    let options = [], actif = -1, minuteur = null, controleur = null, local = { colleges: [], lycees: [], communes: [] }, adresses = [], etatAdresses = "";

    function fermerListe() {
      liste.hidden = true; champ.setAttribute("aria-expanded", "false"); champ.removeAttribute("aria-activedescendant"); actif = -1;
    }
    function rendre() {
      options = [];
      let html = "";
      const groupe = (titre, items) => {
        if (!items.length) return;
        html += `<li class="groupe" role="presentation">${titre}</li>`;
        items.forEach((it) => {
          const i = options.length;
          options.push(it);
          html += `<li role="option" id="sugg-${i}" data-i="${i}" aria-selected="false">${echapper(it.libelle)}${it.detail ? `<small>${echapper(it.detail)}</small>` : ""}</li>`;
        });
      };
      groupe("Collèges", local.colleges.map((f) => ({ type: "college", f, libelle: f.properties.nom, detail: `${f.properties.commune} (${f.properties.departement})` })));
      groupe("Lycées", local.lycees.map((f) => ({ type: "lycee", f, libelle: f.properties.nom, detail: `${f.properties.commune} (${f.properties.departement})` })));
      const nb = (n, mot) => (n ? `${n} ${mot}${n > 1 ? "s" : ""}` : "");
      groupe("Communes", local.communes.map((c) => ({ type: "commune", c, libelle: c.nom, detail: [c.departement, nb(c.colleges, "collège"), nb(c.lycees, "lycée")].filter(Boolean).join(", ") })));
      groupe("Adresses", adresses.map((a) => ({ type: "adresse", a, libelle: a.libelle, detail: a.detail })));
      if (etatAdresses) html += `<li class="info" role="presentation">${etatAdresses}</li>`;
      if (!html) html = `<li class="info" role="presentation">Aucun résultat. Essayez le nom d'un collège ou d'un lycée, une commune ou une adresse avec son numéro.</li>`;
      liste.innerHTML = html;
      liste.hidden = false;
      champ.setAttribute("aria-expanded", "true");
      actif = -1;
    }
    function surligner(i) {
      liste.querySelectorAll('[role="option"]').forEach((el) => el.setAttribute("aria-selected", "false"));
      actif = i;
      if (i < 0) { champ.removeAttribute("aria-activedescendant"); return; }
      const el = $("sugg-" + i);
      el.setAttribute("aria-selected", "true");
      el.scrollIntoView({ block: "nearest" });
      champ.setAttribute("aria-activedescendant", el.id);
    }
    function choisir(it) {
      fermerListe();
      champ.value = it.libelle;
      champ.blur();
      if (it.type === "college") {
        centrer(it.f.geometry.coordinates, Math.max(carte.getZoom(), 14));
        ouvrirFiche(it.f.properties);
      } else if (it.type === "lycee") {
        centrer(it.f.geometry.coordinates, Math.max(carte.getZoom(), 14));
        ouvrirFicheLycee(it.f.properties);
      } else if (it.type === "commune") {
        const b = new maplibregl.LngLatBounds();
        it.c.features.forEach((f) => b.extend(f.geometry.coordinates));
        carte.fitBounds(b, { padding: 80, maxZoom: 15, duration: 600 });
        fermerFiche();
      } else {
        montrerAdresse(it.a);
      }
    }
    champ.addEventListener("input", () => {
      const q = champ.value.trim();
      clearTimeout(minuteur);
      if (controleur) controleur.abort();
      if (q.length < 2) { fermerListe(); return; }
      local = chercherLocal(q);
      adresses = [];
      etatAdresses = q.length >= 3 ? "Recherche des adresses…" : "";
      rendre();
      if (q.length < 3) return;
      minuteur = setTimeout(async () => {
        controleur = new AbortController();
        try {
          adresses = await chercherAdresses(q, controleur.signal);
          etatAdresses = "";
        } catch (e) {
          if (e.name === "AbortError") return;
          adresses = [];
          etatAdresses = "La recherche d'adresses ne répond pas pour le moment. Les établissements et les communes restent cherchables.";
        }
        if (champ.value.trim() === q) rendre();
      }, 300);
    });
    champ.addEventListener("keydown", (e) => {
      if (liste.hidden && e.key !== "Escape") return;
      if (e.key === "ArrowDown") { e.preventDefault(); if (options.length) surligner((actif + 1) % options.length); }
      else if (e.key === "ArrowUp") { e.preventDefault(); if (options.length) surligner(actif <= 0 ? options.length - 1 : actif - 1); }
      else if (e.key === "Enter") { e.preventDefault(); const it = options[actif >= 0 ? actif : 0]; if (it) choisir(it); }
      else if (e.key === "Escape") { e.stopPropagation(); fermerListe(); }
    });
    liste.addEventListener("mousedown", (e) => e.preventDefault());  // garde le focus dans le champ
    liste.addEventListener("click", (e) => {
      const el = e.target.closest('[role="option"]');
      if (el) choisir(options[Number(el.dataset.i)]);
    });
    champ.addEventListener("blur", () => setTimeout(fermerListe, 100));
    champ.addEventListener("focus", () => { if (champ.value.trim().length >= 2 && options.length) { liste.hidden = false; champ.setAttribute("aria-expanded", "true"); } });
  }

  // Adresse choisie : repère sur la carte et liste des collèges publics les plus proches.
  // Les secteurs des départements autour de l'adresse sont chargés avant de chercher son secteur.
  function montrerAdresse(a) {
    Promise.all(departementsAuPoint(a.coord).map(chargerSecteursDep)).catch(() => {}).then(() => afficherAdresse(a));
  }

  function afficherAdresse(a) {
    if (!repereAdresse) {
      const el = document.createElement("div");
      el.className = "repere-adresse";
      el.setAttribute("aria-hidden", "true");
      repereAdresse = new maplibregl.Marker({ element: el });
    }
    repereAdresse.setLngLat(a.coord).addTo(carte);
    centrer(a.coord, 14);
    const uaiSecteur = secteurDe(a.coord);
    const tous = donnees.features
      .filter((f) => f.properties.secteur === "public")
      .map((f) => ({ f, d: distanceKm(a.coord, f.geometry.coordinates) }))
      .sort((x, y) => x.d - y.d);
    const deSecteur = tous.find((x) => x.f.properties.uai === uaiSecteur);
    const proches = (deSecteur ? [deSecteur] : []).concat(tous.filter((x) => x !== deSecteur).slice(0, deSecteur ? 4 : 5));
    surlignerSecteur(uaiSecteur);
    ficheCourante = null;
    const distance = (d) => (d < 1 ? fr(d * 1000, 0).replace(/\s/g, " ") + " m" : fr(d, 1) + " km");
    const lycees = sources.lycees ? sources.lycees.features
      .filter((f) => f.properties.secteur === "public")
      .map((f) => ({ f, d: distanceKm(a.coord, f.geometry.coordinates) }))
      .sort((x, y) => x.d - y.d).slice(0, 3) : [];
    // Département de l'adresse : celui du collège public le plus proche.
    const depProche = tous.length ? normDep(tous[0].f.properties.dep) : null;
    const infoDep = depProche ? indexSecteurs[depProche] : null;
    const secteursIci = Boolean(infoDep);
    // Précision moindre quand les adresses viennent d'une source de secours (BANO) ou que peu d'adresses suivent une règle du fichier.
    const precision = infoDep && (/^BANO/.test(infoDep.source_adresses || "") || (infoDep.rattachees_par_regle || 1) < 0.8)
      ? " Dans ce département, les secteurs sont reconstitués à partir d'adresses moins complètes (OpenStreetMap, en attendant le retour de la Base Adresse Nationale) : ils sont moins précis."
      : "";
    $("fiche-contenu").innerHTML = `
      <h2 id="fiche-nom">${echapper(a.libelle)}</h2>
      <p class="lieu">${deSecteur ? "Collège de secteur et collèges publics les plus proches" : "Collèges publics les plus proches"}, distances à vol d'oiseau</p>
      <ul class="proches">
        ${proches.map((x, i) => `<li${x === deSecteur ? ' class="secteur-adresse"' : ""}><button type="button" data-proche="${i}">
          <span>${x === deSecteur ? '<span class="etiquette">Collège de secteur</span><br>' : ""}${echapper(x.f.properties.nom)}<small>${echapper(x.f.properties.commune)}</small></span>
          <span class="distance">${x.d < 1 ? fr(x.d * 1000, 0).replace(/\s/g, " ") + " m" : fr(x.d, 1) + " km"}</span>
        </button></li>`).join("")}
      </ul>
      <p class="avertissement">${deSecteur
        ? "Le secteur est reconstitué à partir de la carte scolaire officielle et peut différer à la marge, notamment en limite de secteur." + precision + " Pour une inscription, la réponse qui fait foi est celle de l'inspection académique."
        : secteursIci
          ? "Aucun secteur n'a été trouvé pour cette adresse. Le collège le plus proche n'est pas forcément le collège de secteur."
          : "Ce département ne figure pas dans le fichier national de carte scolaire : ses secteurs ne sont pas dessinés. Le collège le plus proche n'est pas forcément le collège de secteur : la mairie ou le conseil départemental indiquent le collège de rattachement."}</p>
      ${lycees.length ? `<h3>Lycées publics les plus proches</h3>
      <ul class="proches">
        ${lycees.map((x, i) => `<li><button type="button" data-lycee="${i}">
          <span>${echapper(x.f.properties.nom)}<small>${echapper(x.f.properties.commune)}</small></span>
          <span class="distance">${distance(x.d)}</span>
        </button></li>`).join("")}
      </ul>
      <p class="avertissement">L'affectation en lycée passe par Affelnet : le lycée le plus proche n'est pas forcément celui obtenu.</p>` : ""}`;
    $("fiche-contenu").querySelectorAll("[data-lycee]").forEach((b) => b.addEventListener("click", () => {
      const f = lycees[Number(b.dataset.lycee)].f;
      centrer(f.geometry.coordinates, Math.max(carte.getZoom(), 14));
      ouvrirFicheLycee(f.properties);
    }));
    $("fiche-contenu").querySelectorAll("[data-proche]").forEach((b) => b.addEventListener("click", () => {
      const f = proches[Number(b.dataset.proche)].f;
      centrer(f.geometry.coordinates, Math.max(carte.getZoom(), 14));
      ouvrirFiche(f.properties);
    }));
    const fiche = $("fiche");
    fiche.hidden = false;
    document.body.classList.add("fiche-ouverte");
    fiche.scrollTop = 0;
  }

  // ---------------------------------------------------------------- secteurs
  // Zones calculées à partir de la carte scolaire officielle (voir pipeline/secteurs.py).
  // Un fichier par département (data/secteurs/<dep>.geojson), chargé quand le département est visible
  // à partir du zoom ZOOM_SECTEURS, ou quand une adresse y est cherchée. index.json donne l'emprise de chacun.
  // Zoom 7 : une région à l'écran. En dessous, aucun secteur n'est affiché et une indication invite à zoomer.
  const ZOOM_SECTEURS = 7;
  let secteurs = { type: "FeatureCollection", features: [] };
  let indexSecteurs = {};  // département normalisé ("3", "2A", "75") -> { fichier, bbox, source_adresses, ... }
  const secteursDep = new Map();
  // Les collèges ont "3" ; les fichiers de secteurs, "03".
  const normDep = (d) => (/^\d+$/.test(String(d)) ? String(Number(d)) : String(d || ""));

  function dansAnneau(pt, anneau) {
    let dedans = false;
    for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
      const [xi, yi] = anneau[i], [xj, yj] = anneau[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) dedans = !dedans;
    }
    return dedans;
  }
  function dansPolygone(pt, poly) { return dansAnneau(pt, poly[0]) && !poly.slice(1).some((trou) => dansAnneau(pt, trou)); }
  function secteurDe(pt) {
    for (const f of secteurs.features) {
      const g = f.geometry;
      const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      if (polys.some((poly) => dansPolygone(pt, poly))) return f.properties.uai;
    }
    return null;
  }

  // Chaque zone reçoit les indicateurs de son collège, pour être colorée comme lui.
  function enrichir(features) {
    const parUai = new Map(donnees.features.map((f) => [f.properties.uai, f.properties]));
    features.forEach((f) => {
      const p = parUai.get(f.properties.uai);
      if (p) INDICATEURS.forEach((i) => { if (typeof p[i.cle] === "number") f.properties[i.cle] = p[i.cle]; });
    });
    return features;
  }

  let majPrevue = false;
  function majSecteurs() {
    if (majPrevue) return;
    majPrevue = true;
    requestAnimationFrame(() => {
      majPrevue = false;
      const src = carte.getSource("secteurs");
      if (src) src.setData(secteurs);
      if (ficheCourante && ficheCourante.type === "college") surlignerSecteur(ficheCourante.p.uai);
    });
  }

  function chargerSecteursDep(dep) {
    const info = indexSecteurs[dep];
    if (!info) return Promise.resolve();
    if (!secteursDep.has(dep)) {
      secteursDep.set(dep, fetch(`data/secteurs/${encodeURIComponent(info.fichier)}.geojson?v=${info.date || ""}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((geo) => { secteurs.features.push(...enrichir(geo.features)); majSecteurs(); })
        .catch((e) => { secteursDep.delete(dep); console.warn(`Secteurs du département ${dep} indisponibles`, e); }));
    }
    return secteursDep.get(dep);
  }

  const dansBbox = (b, lon, lat, marge = 0) => b && lon >= b[0] - marge && lon <= b[2] + marge && lat >= b[1] - marge && lat <= b[3] + marge;
  function departementsAuPoint(pt) {
    return Object.keys(indexSecteurs).filter((d) => dansBbox(indexSecteurs[d].bbox, pt[0], pt[1], 0.01));
  }
  function chargerSecteursVisibles() {
    const actifs = carte.getLayer("secteurs-fond") && carte.getLayoutProperty("secteurs-fond", "visibility") !== "none";
    $("indice-secteurs").hidden = !(actifs && carte.getZoom() < ZOOM_SECTEURS);
    if (!actifs || carte.getZoom() < ZOOM_SECTEURS) return;
    const v = carte.getBounds();
    Object.keys(indexSecteurs).forEach((d) => {
      const b = indexSecteurs[d].bbox;
      if (b && b[0] <= v.getEast() && b[2] >= v.getWest() && b[1] <= v.getNorth() && b[3] >= v.getSouth()) chargerSecteursDep(d);
    });
  }

  function chargerSecteurs() {
    fetch("data/secteurs/index.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((index) => {
      indexSecteurs = Object.fromEntries(Object.entries(index).map(([d, v]) => [normDep(d), Object.assign({ fichier: d }, v)]));
      carte.addSource("secteurs", { type: "geojson", data: secteurs });
      carte.addLayer({ id: "secteurs-fond", type: "fill", source: "secteurs", minzoom: ZOOM_SECTEURS, paint: { "fill-color": ABSENT, "fill-opacity": 0.35 } }, "colleges");
      carte.addLayer({ id: "secteurs-contour", type: "line", source: "secteurs", minzoom: ZOOM_SECTEURS, paint: { "line-color": "#1e2f6b", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.3, 14, 1.2], "line-opacity": 0.55 } }, "colleges");
      carte.addLayer({ id: "secteurs-surligne", type: "line", source: "secteurs", minzoom: ZOOM_SECTEURS, filter: ["==", ["get", "uai"], ""], paint: { "line-color": "#1e2f6b", "line-width": 3 } }, "colleges");
      appliquerCalque(calque("colleges"));
      carte.on("moveend", chargerSecteursVisibles);
      chargerSecteursVisibles();
    }).catch((e) => console.warn("Secteurs indisponibles", e));
  }

  // ---------------------------------------------------------------- démarrage
  function cadrer() {
    const b = new maplibregl.LngLatBounds();
    donnees.features.forEach((f) => b.extend(f.geometry.coordinates));
    if (!b.isEmpty()) carte.fitBounds(b, { padding: { top: 40, bottom: estMobile() ? 260 : 40, left: estMobile() ? 20 : 400, right: 40 }, duration: 0 });
  }

  const charger = (url) => fetch(url).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  initPanneau();
  Promise.all([
    charger("data/colleges.geojson"),
    charger("data/lycees.geojson").catch((e) => { console.warn("Lycées indisponibles", e); return null; }),
    new Promise((res) => carte.on("load", res)),
    fetch("data/meta.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
  ]).then(([geo, lyc, , meta]) => {
    donnees = geo;
    sources.colleges = geo;
    if (lyc) sources.lycees = lyc;
    if (meta && meta.medianes) medianes = Object.assign(medianes, meta.medianes);
    if (meta && meta.medianes_academies) medianesAcademies = meta.medianes_academies;
    if (meta && meta.lycees && meta.lycees.medianes) medianesLycees = Object.assign(medianesLycees, meta.lycees.medianes);
    if (meta && meta.lycees && meta.lycees.medianes_academies) medianesLyceesAcademies = meta.lycees.medianes_academies;
    ajouterFormes();
    ajouterCalqueCarte(calque("colleges"));
    if (lyc) ajouterCalqueCarte(calque("lycees"));  // au-dessus des collèges
    construirePanneau();
    cadrer();
    initRecherche();
    chargerSecteurs();
    etat.textContent = "";
    const couches = () => ["lycees", "colleges"].filter((id) => carte.getLayer(id));
    carte.on("click", (e) => {
      // Petite marge autour du doigt : les formes sont petites sur mobile.
      const zone = [[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]];
      const pt = carte.queryRenderedFeatures(zone, { layers: couches() })[0];
      if (pt) { if (pt.layer.id === "lycees") ouvrirFicheLycee(pt.properties); else ouvrirFiche(pt.properties); return; }
      if (!carte.getLayer("secteurs-fond") || carte.getLayoutProperty("secteurs-fond", "visibility") === "none") return;
      const z = carte.queryRenderedFeatures(e.point, { layers: ["secteurs-fond"] })[0];
      const f = z && donnees.features.find((x) => x.properties.uai === z.properties.uai);
      if (f) ouvrirFiche(f.properties);
    });
    couches().forEach((id) => {
      carte.on("mouseenter", id, () => (carte.getCanvas().style.cursor = "pointer"));
      carte.on("mouseleave", id, () => (carte.getCanvas().style.cursor = ""));
    });
  }).catch((err) => {
    etat.textContent = "Les données n'ont pas pu être chargées. Rechargez la page ; si le problème continue, les données sont peut-être en cours de mise à jour.";
    console.error(err);
  });

  $("fermer").addEventListener("click", fermerFiche);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fermerFiche(); });
})();
