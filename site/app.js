/* Carte scolaire : collèges des académies de Paris et de Versailles. */
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

  // Indicateurs proposés. "doc" pointe vers la section de documentation.
  const INDICATEURS = [
    { cle: "ips", nom: "Indice de position sociale (IPS)", type: "seq", fmt: (v) => fr(v, 1), doc: "ips",
      note: "Plus l'IPS est élevé, plus le milieu social des élèves est favorisé." },
    { cle: "taux_reussite", nom: "Réussite au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "taux_mentions", nom: "Mentions au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "note_ecrit", nom: "Note aux écrits du brevet", type: "seq", fmt: (v) => fr(v, 1) + " / 20", doc: "brevet" },
    { cle: "va_reussite", nom: "Valeur ajoutée (réussite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "points",
      note: "Écart entre la réussite obtenue et celle attendue au vu du profil des élèves." },
    { cle: "va_note", nom: "Valeur ajoutée (note écrite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "point",
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
      // Zone neutre : entre -seuil et +seuil, le collège fait à peu près ce qui était attendu.
      const s = Number(VA.seuils[ind.cle]) || 0;
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

  function couleur(ind) {
    const d = domaine(ind);
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
    if (indicateur.type === "div") {
      const pos = (x) => (((x + d.m) / (2 * d.m)) * 100).toFixed(1) + "%";
      const pct = (k) => Math.round((100 * k) / d.n);
      $("legende").innerHTML =
        `<div class="degrade" style="background:linear-gradient(90deg,${pal[0]} 0%,${pal[1]} ${pos(-d.s)},${pal[2]} ${pos(-d.s)},${pal[2]} ${pos(d.s)},${pal[3]} ${pos(d.s)},${pal[4]} 100%)"></div>` +
        `<div class="bornes"><span>${indicateur.fmt(-d.m)}</span><span>${echapper(VA.libelles.proche)}</span><span>${indicateur.fmt(d.m)}</span></div>` +
        `<p class="note">${indicateur.note} ${echapper(remplir(VA.texteZone, { min: indicateur.fmt(-d.s), max: indicateur.fmt(d.s), unite: indicateur.unite }))}</p>` +
        `<p class="note">${echapper(remplir(VA.texteRepartition, { dessous: pct(d.dessous), proches: pct(d.proches), dessus: pct(d.dessus) }))}</p>` +
        (manquants > 0 ? `<p class="note">En gris foncé : ${manquants} collège${manquants > 1 ? "s" : ""} sans donnée.</p>` : "");
      return;
    }
    $("legende").innerHTML =
      `<div class="degrade" style="background:linear-gradient(90deg,${pal.join(",")})"></div>` +
      `<div class="bornes"><span>${indicateur.fmt(d.stops[0])}</span><span>${indicateur.fmt(d.stops[2])}</span><span>${indicateur.fmt(d.stops[4])}</span></div>` +
      (indicateur.type === "seq" ? `<p class="note">La teinte du milieu correspond à la médiane : la moitié des collèges est au-dessus.</p>` : "") +
      (indicateur.note ? `<p class="note">${indicateur.note}</p>` : "") +
      (manquants > 0 ? `<p class="note">En gris : ${manquants} collège${manquants > 1 ? "s" : ""} sans donnée.</p>` : "");
  }

  // ---------------------------------------------------------------- fiche
  // La fiche montre un graphique d'évolution à la fois ; des boutons changent d'indicateur.
  let medianes = { brevet: {}, ips: {}, eval6e: {} };
  let ongletChoisi = "brevet";
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

  // Graphique en ligne : séries du collège, médiane en pointillés, bande neutre éventuelle.
  function graphique(g) {
    const W = 334, H = 200, L = 40, R = 70, T = 12, B = 26, pw = W - L - R, ph = H - T - B;
    const n = g.labels.length;
    const tous = [].concat(...g.series.map((s) => s.vals), g.med || [], g.bande || []).filter(num);
    const e = echelle(tous, g.echelle);
    const x = (i) => (n > 1 ? L + (i * pw) / (n - 1) : L + pw / 2);
    const y = (v) => T + ph * (1 - (v - e.min) / (e.max - e.min));
    const trace = (vals) => {
      let d = "", leve = true;
      vals.forEach((v, i) => { if (!num(v)) { leve = true; return; } d += (leve ? "M" : "L") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " "; leve = false; });
      return d.trim();
    };
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${echapper(g.aria)}">`;
    if (g.bande) svg += `<rect x="${L}" y="${y(g.bande[1]).toFixed(1)}" width="${pw}" height="${(y(g.bande[0]) - y(g.bande[1])).toFixed(1)}" fill="${BANDE}"/>`;
    e.ticks.forEach((t) => {
      svg += `<line x1="${L}" x2="${W - R}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}" stroke="${t === 0 && g.zero ? "#56648f" : "#e3e7f0"}" stroke-width="1"/>`;
      svg += `<text x="${L - 6}" y="${(y(t) + 4).toFixed(1)}" text-anchor="end">${echapper(g.tick(t))}</text>`;
    });
    g.labels.forEach((l, i) => { svg += `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${echapper(l)}</text>`; });
    if (g.med && g.med.some(num)) svg += `<path d="${trace(g.med)}" fill="none" stroke="${MEDIANE}" stroke-width="2" stroke-dasharray="4 3"/>`;
    g.series.slice().reverse().forEach((s) => {
      svg += `<path d="${trace(s.vals)}" fill="none" stroke="${s.couleur}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
      s.vals.forEach((v, i) => { if (num(v)) svg += `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="4" fill="${s.couleur}"/>`; });
    });
    // Noms des courbes au bout des lignes, écartés s'ils se chevauchent.
    const fins = [];
    const fin = (vals, txt, couleur, gras) => { for (let i = vals.length - 1; i >= 0; i--) if (num(vals[i])) { fins.push({ txt, y: y(vals[i]), couleur, gras }); return; } };
    g.series.forEach((s) => fin(s.vals, s.nom, s.texte || s.couleur, true));
    if (g.med) fin(g.med, "médiane", "#56648f", false);
    fins.sort((a, b) => a.y - b.y);
    for (let i = 1; i < fins.length; i++) if (fins[i].y - fins[i - 1].y < 15) fins[i].y = fins[i - 1].y + 15;
    fins.forEach((f) => { svg += `<text x="${W - R + 8}" y="${(f.y + 4).toFixed(1)}" style="fill:${f.couleur};font-weight:${f.gras ? 700 : 400}">${echapper(f.txt)}</text>`; });
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
    const pct = (v) => fr(v, 1) + " %";
    const br = hist.brevet || [], ip = hist.ips || [], ev = hist.eval6e || [];
    const medB = (cle) => br.map((r) => (medianes.brevet[r.session] || {})[cle]);
    const res = [];
    if (br.some((r) => num(r.taux_reussite))) {
      const d = dernier(br, "taux_reussite"), m = (medianes.brevet[d.session] || {}).taux_reussite;
      const contexte = [];
      if (num(d.taux_mentions)) contexte.push(`Mentions : ${pct(d.taux_mentions)}.`);
      if (num(d.note_ecrit)) contexte.push(`Note aux écrits : ${fr(d.note_ecrit, 1)} / 20.`);
      if (num(m)) contexte.push(`Médiane de réussite : ${pct(m)}.`);
      if (num(d.score)) contexte.push(`Score agrégé : ${fr(d.score, 1)} (${d.rang}e sur ${fr(d.nb, 0)}).`);
      res.push({
        cle: "brevet", nom: "Brevet", titre: "Réussite et mentions au brevet",
        valeur: pct(d.taux_reussite), unite: `réussite ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session), series: [
          { vals: br.map((r) => r.taux_reussite), couleur: ENCRE, nom: "réussite" },
          { vals: br.map((r) => r.taux_mentions), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "mentions" },
        ], med: medB("taux_reussite"), tick: (t) => fr(t, 0) + " %", echelle: { plancher: 0, plafond: 100, etendueMin: 20 },
          aria: "Réussite au brevet par session : " + br.map((r) => `${r.session} ${num(r.taux_reussite) ? pct(r.taux_reussite) : "non publié"}`).join(", ") + "." },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "taux_reussite", nom: "Réussite", fmt: pct }, { cle: "taux_mentions", nom: "Mentions", fmt: pct },
          { cle: "note_ecrit", nom: "Écrits", fmt: (v) => fr(v, 1) }, { cle: "candidats", nom: "Candidats", fmt: (v) => fr(v, 0) }], br),
      });
    }
    if (ip.some((r) => num(r.ips))) {
      const d = dernier(ip, "ips"), m = medianes.ips[d.annee];
      const contexte = [];
      if (num(m)) contexte.push(`Médiane des deux académies : ${fr(m, 1)}.`);
      if (num(d.ecart_type)) contexte.push(`Écart-type : ${fr(d.ecart_type, 1)}.`);
      res.push({
        cle: "ips", nom: "IPS", titre: "Indice de position sociale",
        valeur: fr(d.ips, 1), unite: d.annee, contexte: contexte.join(" "),
        graphe: { labels: ip.map((r) => anneeCourte(r.annee)), series: [{ vals: ip.map((r) => r.ips), couleur: ENCRE, nom: "IPS" }],
          med: ip.map((r) => medianes.ips[r.annee]), tick: (t) => fr(t, 0), echelle: { etendueMin: 20 },
          aria: "IPS par année : " + ip.map((r) => `${r.annee} ${num(r.ips) ? fr(r.ips, 1) : "non publié"}`).join(", ") + "." },
        table: tableau([{ cle: "annee", nom: "Année" }, { cle: "ips", nom: "IPS", fmt: (v) => fr(v, 1) }, { cle: "ecart_type", nom: "Écart-type", fmt: (v) => fr(v, 1) }], ip),
      });
    }
    if (br.some((r) => num(r.va_reussite))) {
      const d = dernier(br, "va_reussite"), s = seuilVA("va_reussite");
      const unite = Math.abs(d.va_reussite) > 1 ? "points" : "point";
      const contexte = [lectureVA("va_reussite", d.va_reussite).replace(/^./, (c) => c.toUpperCase()) + "."];
      const dn = dernier(br, "va_note");
      if (dn) contexte.push(`Sur la note aux écrits : ${signe(dn.va_note)} (${lectureVA("va_note", dn.va_note)}).`);
      contexte.push(`Zone grisée : entre ${signe(-s)} et ${signe(s)} points.`);
      res.push({
        cle: "va", nom: "Valeur ajoutée", titre: "Valeur ajoutée (réussite)",
        valeur: signe(d.va_reussite), unite: `${unite}, ${d.session}`, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session), series: [{ vals: br.map((r) => r.va_reussite), couleur: ENCRE, nom: "collège" }],
          med: medB("va_reussite"), bande: [-s, s], zero: true, tick: (t) => (t > 0 ? "+" : t < 0 ? "−" : "") + fr(Math.abs(t), 0),
          echelle: { sym: true, demiMin: Math.max(s * 3, 4) },
          aria: "Valeur ajoutée sur la réussite par session : " + br.map((r) => `${r.session} ${num(r.va_reussite) ? signe(r.va_reussite) : "non publié"}`).join(", ") + "." },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "va_reussite", nom: "Réussite", fmt: signe }, { cle: "va_note", nom: "Note écrite", fmt: signe }], br),
      });
    }
    if (ev.some((r) => num(r.fr) || num(r.ma))) {
      const d = dernier(ev, "fr") || dernier(ev, "ma"), m = (medianes.eval6e[d.annee] || {}).fr;
      const contexte = [];
      if (num(d.ma)) contexte.push(`Mathématiques : ${fr(d.ma, 0)}.`);
      if (num(m)) contexte.push(`Médiane en français : ${fr(m, 0)}.`);
      res.push({
        cle: "eval", nom: "Évaluations 6e", titre: "Évaluations de 6e",
        valeur: num(d.fr) ? fr(d.fr, 0) : "–", unite: `français ${d.annee}`, contexte: contexte.join(" "),
        graphe: { labels: ev.map((r) => r.annee), series: [
          { vals: ev.map((r) => r.fr), couleur: ENCRE, nom: "français" },
          { vals: ev.map((r) => r.ma), couleur: MAGENTA, texte: MAGENTA_TEXTE, nom: "maths" },
        ], med: ev.map((r) => (medianes.eval6e[r.annee] || {}).fr), tick: (t) => fr(t, 0), echelle: { etendueMin: 40 },
          aria: "Scores moyens à l'entrée en 6e. Français : " + ev.map((r) => `${r.annee} ${num(r.fr) ? fr(r.fr, 0) : "non publié"}`).join(", ") + "." },
        table: tableau([{ cle: "annee", nom: "Année" }, { cle: "fr", nom: "Français", fmt: (v) => fr(v, 0) }, { cle: "ma", nom: "Maths", fmt: (v) => fr(v, 0) }], ev),
      });
    }
    return res;
  }

  function afficherOnglet() {
    const liste = ficheCourante.onglets;
    const o = liste.find((x) => x.cle === ongletChoisi) || liste[0];
    document.querySelectorAll("#fiche .onglets button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.onglet === o.cle)));
    const avecMediane = o.graphe.med && o.graphe.med.some(num);
    $("fiche-graphe").innerHTML = `
      <div class="graphe-tete">
        <h3>${o.titre}</h3>
        <p class="valeur">${echapper(o.valeur)} <small>${echapper(o.unite)}</small></p>
      </div>
      <p class="graphe-contexte">${echapper(o.contexte)}</p>
      <div class="graphe">${graphique(o.graphe)}</div>
      <div class="legende-graphe" aria-hidden="true">
        <span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${ENCRE}" stroke-width="2.5" stroke-linecap="round"/></svg>Ce collège</span>
        ${avecMediane ? `<span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${MEDIANE}" stroke-width="2" stroke-dasharray="4 3"/></svg>Médiane Paris et Versailles</span>` : ""}
      </div>
      <details class="valeurs"><summary>Valeurs par année</summary>${o.table}</details>`;
  }

  function ouvrirFiche(p) {
    const hist = JSON.parse(p.hist || "{}");
    const liste = onglets(p, hist);
    ficheCourante = { p, onglets: liste };
    const type = p.secteur === "public" ? "Collège public" : "Collège privé sous contrat";
    $("fiche-contenu").innerHTML = `
      <h2 id="fiche-nom">${echapper(p.nom)}</h2>
      <p class="lieu">${type}, ${echapper(p.commune)} (${echapper(p.departement)})</p>
      ${liste.length ? `
        <div class="onglets" role="group" aria-label="Indicateur affiché">
          ${liste.map((o) => `<button type="button" data-onglet="${o.cle}" aria-pressed="false">${o.nom}</button>`).join("")}
        </div>
        <div id="fiche-graphe" aria-live="polite"></div>` :
        `<p>Aucun indicateur n'est publié pour ce collège. C'est souvent le cas des établissements récents ou à petit effectif.</p>`}
      <p class="renvoi"><a href="documentation.html#indicateurs">Comprendre ces indicateurs</a></p>`;
    if (liste.length) afficherOnglet();
    const fiche = $("fiche");
    fiche.hidden = false;
    document.body.classList.add("fiche-ouverte");
    fiche.scrollTop = 0;
    $("fermer").focus({ preventScroll: true });
  }

  $("fiche-contenu").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-onglet]");
    if (!b || !ficheCourante) return;
    ongletChoisi = b.dataset.onglet;  // gardé pour la fiche suivante
    afficherOnglet();
  });

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
    fetch("data/meta.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({})),
  ]).then(([geo, , meta]) => {
    donnees = geo;
    if (meta && meta.medianes) medianes = Object.assign(medianes, meta.medianes);
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
