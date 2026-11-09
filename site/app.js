/* Carte scolaire : collèges des académies de Paris et de Versailles. */
(function () {
  "use strict";

  // Plasma, du plus bas (jaune) au plus haut (bleu nuit). Lisible pour les daltoniens.
  const ECHELLE = ["#f0f921", "#f89540", "#cc4778", "#7e03a8", "#0d0887"];
  // Valeur ajoutée, dans la logique de Plasma : valeurs basses côté orange, valeurs hautes côté violet,
  // zéro en gris très clair. Les extrêmes ont une clarté proche pour ne favoriser aucun côté.
  const DIVERGENTE = ["#c4500f", "#f4ad73", "#f3f1f6", "#b48ad9", "#6a0d9e"];
  const ABSENT = "#a7adba";

  // Indicateurs proposés. "doc" pointe vers la section de documentation.
  const INDICATEURS = [
    { cle: "ips", nom: "Indice de position sociale (IPS)", type: "seq", fmt: (v) => fr(v, 1), doc: "ips",
      note: "Plus l'IPS est élevé, plus le milieu social des élèves est favorisé." },
    { cle: "taux_reussite", nom: "Réussite au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "taux_mentions", nom: "Mentions au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "note_ecrit", nom: "Note aux écrits du brevet", type: "seq", fmt: (v) => fr(v, 1) + " / 20", doc: "brevet" },
    { cle: "va_reussite", nom: "Valeur ajoutée (réussite)", type: "div", fmt: signe, doc: "valeur-ajoutee",
      note: "Écart entre la réussite obtenue et celle attendue au vu du profil des élèves." },
    { cle: "va_note", nom: "Valeur ajoutée (note écrite)", type: "div", fmt: signe, doc: "valeur-ajoutee",
      note: "Écart entre la note obtenue et celle attendue au vu du profil des élèves." },
    { cle: "eval_fr", nom: "Évaluations 6e (français)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "eval_ma", nom: "Évaluations 6e (maths)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "score", nom: "Score agrégé (optionnel)", type: "seq", fmt: (v) => fr(v, 1), doc: "score",
      note: "Moyenne des taux de réussite, de mentions et de mentions très bien. À lire avec précaution." },
  ];

  const $ = (id) => document.getElementById(id);
  const etat = $("etat");
  let donnees = null;
  let indicateur = INDICATEURS[0];

  function fr(v, nd) {
    return Number(v).toLocaleString("fr-FR", { minimumFractionDigits: nd, maximumFractionDigits: nd });
  }
  function signe(v) {
    const s = fr(Math.abs(v), 1);
    return (v > 0 ? "+" : v < 0 ? "−" : "") + s;
  }
  function quantile(sorted, q) {
    if (!sorted.length) return 0;
    const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
  }
  function echapper(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------------------------------------------------------- carte
  // Si le fond de carte ne répond pas, on garde au moins les points sur un fond uni.
  const STYLE_SECOURS = { version: 8, sources: {}, layers: [{ id: "fond", type: "background", paint: { "background-color": "#eef1f4" } }] };
  const carte = new maplibregl.Map({
    container: "carte",
    style: "https://tiles.openfreemap.org/styles/positron",
    center: [2.25, 48.8],
    zoom: 9,
    attributionControl: { compact: true },
  });
  let secours = false;
  carte.on("error", () => {
    if (!secours && !carte.isStyleLoaded()) { secours = true; carte.setStyle(STYLE_SECOURS); }
  });
  carte.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  carte.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }), "top-right");

  // Échelles séquentielles : les couleurs sont posées sur les quantiles (5 %, 25 %, médiane,
  // 75 %, 95 %) pour que chaque teinte couvre à peu près autant de collèges et que les écarts
  // restent lisibles même quand les valeurs sont serrées.
  function domaine(ind) {
    const vals = donnees.features.map((f) => f.properties[ind.cle]).filter((v) => typeof v === "number").sort((a, b) => a - b);
    if (ind.type === "div") {
      const m = Math.max(Math.abs(quantile(vals, 0.05)), Math.abs(quantile(vals, 0.95))) || 1;
      return { stops: [-m, -m / 2, 0, m / 2, m], n: vals.length };
    }
    const stops = [0.05, 0.25, 0.5, 0.75, 0.95].map((q) => quantile(vals, q));
    for (let i = 1; i < stops.length; i++) if (stops[i] <= stops[i - 1]) stops[i] = stops[i - 1] + 1e-6;
    return { stops, n: vals.length };
  }

  function couleur(ind) {
    const d = domaine(ind);
    const pal = ind.type === "div" ? DIVERGENTE : ECHELLE;
    const stops = pal.flatMap((c, i) => [d.stops[i], c]);
    return { expr: ["case", ["has", ind.cle], ["interpolate", ["linear"], ["get", ind.cle], ...stops], ABSENT], d, pal };
  }

  function filtre() {
    const secteurs = [];
    if ($("voir-public").checked) secteurs.push("public");
    if ($("voir-prive").checked) secteurs.push("privé");
    return ["in", ["get", "secteur"], ["literal", secteurs]];
  }

  function appliquer() {
    const { expr, d, pal } = couleur(indicateur);
    carte.setPaintProperty("colleges", "circle-color", expr);
    carte.setFilter("colleges", filtre());
    const manquants = donnees.features.length - d.n;
    $("legende").innerHTML =
      `<div class="degrade" style="background:linear-gradient(90deg,${pal.join(",")})"></div>` +
      `<div class="bornes"><span>${indicateur.fmt(d.stops[0])}</span><span>${indicateur.fmt(d.stops[2])}</span><span>${indicateur.fmt(d.stops[4])}</span></div>` +
      (indicateur.type === "seq" ? `<p class="note">La teinte du milieu correspond à la médiane : la moitié des collèges est au-dessus.</p>` : "") +
      (indicateur.note ? `<p class="note">${indicateur.note}</p>` : "") +
      (manquants > 0 ? `<p class="note">En gris : ${manquants} collège${manquants > 1 ? "s" : ""} sans donnée.</p>` : "");
  }

  // ---------------------------------------------------------------- fiche
  function chiffre(p, ind, suffixe) {
    const v = p[ind.cle];
    if (typeof v !== "number") return `<div class="chiffre vide"><dt>${ind.nom}</dt><dd>Non publié</dd></div>`;
    return `<div class="chiffre"><dt>${ind.nom}</dt><dd>${ind.fmt(v)}${suffixe ? ` <small>${suffixe}</small>` : ""}</dd></div>`;
  }

  function tableau(titre, colonnes, lignes) {
    if (!lignes || !lignes.length) return "";
    const th = colonnes.map((c) => `<th scope="col">${c.nom}</th>`).join("");
    const tr = lignes.map((l) => "<tr>" + colonnes.map((c, i) => {
      const v = l[c.cle];
      const txt = v === null || v === undefined ? "–" : (c.fmt ? c.fmt(v) : echapper(v));
      return i === 0 ? `<th scope="row">${txt}</th>` : `<td>${txt}</td>`;
    }).join("") + "</tr>").join("");
    return `<h3>${titre}</h3><table class="historique"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
  }

  function ouvrirFiche(p) {
    const ind = Object.fromEntries(INDICATEURS.map((i) => [i.cle, i]));
    const hist = JSON.parse(p.hist || "{}");
    const type = p.secteur === "public" ? "Collège public" : "Collège privé sous contrat";
    const rang = typeof p.rang === "number" ? `${p.rang}e sur ${fr(p.nb, 0)}` : "";
    const sess = p.session_brevet ? `session ${echapper(p.session_brevet)}` : "";
    const pct = (v) => fr(v, 1) + " %";
    $("fiche-contenu").innerHTML = `
      <h2 id="fiche-nom">${echapper(p.nom)}</h2>
      <p class="lieu">${type}, ${echapper(p.commune)} (${echapper(p.departement)})</p>
      ${INDICATEURS.some((i) => typeof p[i.cle] === "number") ? "" : `<p>Aucun indicateur n'est publié pour ce collège. C'est souvent le cas des établissements récents ou à petit effectif.</p>`}
      <dl class="chiffres"${INDICATEURS.some((i) => typeof p[i.cle] === "number") ? "" : " hidden"}>
        ${chiffre(p, ind.ips, p.annee_ips ? echapper(p.annee_ips) : "")}
        ${chiffre(p, ind.taux_reussite, sess)}
        ${chiffre(p, ind.taux_mentions)}
        ${chiffre(p, ind.va_reussite, "points")}
        ${chiffre(p, ind.note_ecrit)}
        ${chiffre(p, ind.va_note, "point")}
        ${chiffre(p, ind.eval_fr, p.annee_eval ? echapper(p.annee_eval) : "")}
        ${chiffre(p, ind.eval_ma)}
        ${chiffre(p, ind.score, rang)}
      </dl>
      ${tableau("Brevet, par session", [
        { cle: "session", nom: "Session" },
        { cle: "taux_reussite", nom: "Réussite", fmt: pct },
        { cle: "taux_mentions", nom: "Mentions", fmt: pct },
        { cle: "va_reussite", nom: "Val. ajoutée", fmt: signe },
        { cle: "candidats", nom: "Candidats", fmt: (v) => fr(v, 0) },
      ], hist.brevet)}
      ${tableau("Indice de position sociale", [
        { cle: "annee", nom: "Année" },
        { cle: "ips", nom: "IPS", fmt: (v) => fr(v, 1) },
        { cle: "ecart_type", nom: "Écart-type", fmt: (v) => fr(v, 1) },
      ], hist.ips)}
      ${tableau("Évaluations de 6e", [
        { cle: "annee", nom: "Année" },
        { cle: "fr", nom: "Français", fmt: (v) => fr(v, 0) },
        { cle: "ma", nom: "Mathématiques", fmt: (v) => fr(v, 0) },
      ], hist.eval6e)}
      <p class="renvoi"><a href="documentation.html#indicateurs">Comprendre ces indicateurs</a></p>`;
    const fiche = $("fiche");
    fiche.hidden = false;
    document.body.classList.add("fiche-ouverte");
    fiche.scrollTop = 0;
    $("fermer").focus({ preventScroll: true });
  }

  function fermerFiche() {
    $("fiche").hidden = true;
    document.body.classList.remove("fiche-ouverte");
  }

  // ---------------------------------------------------------------- démarrage
  function remplirSelecteur() {
    const sel = $("indicateur");
    const dispo = INDICATEURS.filter((i) => donnees.features.some((f) => typeof f.properties[i.cle] === "number"));
    sel.innerHTML = dispo.map((i) => `<option value="${i.cle}">${i.nom}</option>`).join("");
    indicateur = dispo[0] || INDICATEURS[0];
    sel.addEventListener("change", () => {
      indicateur = INDICATEURS.find((i) => i.cle === sel.value);
      appliquer();
    });
  }

  function cadrer() {
    const b = new maplibregl.LngLatBounds();
    donnees.features.forEach((f) => b.extend(f.geometry.coordinates));
    if (!b.isEmpty()) carte.fitBounds(b, { padding: { top: 40, bottom: window.innerWidth < 760 ? 220 : 40, left: window.innerWidth < 760 ? 20 : 360, right: 40 }, duration: 0 });
  }

  Promise.all([
    fetch("data/colleges.geojson").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
    new Promise((res) => carte.on("load", res)),
  ]).then(([geo]) => {
    donnees = geo;
    carte.addSource("colleges", { type: "geojson", data: geo });
    carte.addLayer({
      id: "colleges",
      type: "circle",
      source: "colleges",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3.5, 12, 7, 15, 11],
        "circle-color": ABSENT,
        "circle-stroke-color": "#1e2f6b",
        "circle-stroke-width": ["case", ["==", ["get", "secteur"], "privé"], 2, 0.5],
      },
    });
    remplirSelecteur();
    appliquer();
    cadrer();
    etat.textContent = "";
    carte.on("click", "colleges", (e) => ouvrirFiche(e.features[0].properties));
    carte.on("mouseenter", "colleges", () => (carte.getCanvas().style.cursor = "pointer"));
    carte.on("mouseleave", "colleges", () => (carte.getCanvas().style.cursor = ""));
  }).catch((err) => {
    etat.textContent = "Les données des collèges n'ont pas pu être chargées. Rechargez la page ; si le problème continue, les données sont peut-être en cours de mise à jour.";
    console.error(err);
  });

  $("voir-public").addEventListener("change", () => donnees && appliquer());
  $("voir-prive").addEventListener("change", () => donnees && appliquer());
  $("fermer").addEventListener("click", fermerFiche);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fermerFiche(); });
})();
