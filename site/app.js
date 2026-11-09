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
    { cle: "taux_reussite", nom: "Réussite au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "taux_mentions", nom: "Mentions au brevet", type: "seq", fmt: (v) => fr(v, 1) + " %", doc: "brevet" },
    { cle: "note_ecrit", nom: "Note aux écrits du brevet", type: "seq", fmt: (v) => fr(v, 1) + " / 20", doc: "brevet" },
    { cle: "va_reussite", nom: "Valeur ajoutée (réussite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "points",
      note: "Écart entre la réussite obtenue et celle attendue au vu du profil des élèves." },
    { cle: "va_note", nom: "Valeur ajoutée (note écrite)", type: "div", fmt: signe, doc: "valeur-ajoutee", unite: "point",
      note: "Écart entre la note obtenue et celle attendue au vu du profil des élèves." },
    { cle: "ips", nom: "Indice de position sociale (IPS)", type: "seq", fmt: (v) => fr(v, 1), doc: "ips",
      note: "Plus l'IPS est élevé, plus le milieu social des élèves est favorisé." },
    { cle: "eval_fr", nom: "Évaluations 6e (français)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "eval_ma", nom: "Évaluations 6e (maths)", type: "seq", fmt: (v) => fr(v, 0), doc: "evaluations" },
    { cle: "score", nom: "Score agrégé", type: "seq", fmt: (v) => fr(v, 1), doc: "score",
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
    if (carte.getLayer("secteurs-fond")) {
      carte.setPaintProperty("secteurs-fond", "fill-color", expr);
      const vis = $("voir-zones").checked ? "visible" : "none";
      ["secteurs-fond", "secteurs-contour", "secteurs-surligne"].forEach((id) => carte.setLayoutProperty(id, "visibility", vis));
    }
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
    g.labels.forEach((l, i) => { svg += `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${echapper(l)}</text>`; });
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
      if (meds.length) contexte.push(`Médianes : ${meds.join(", ")}.`);
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
      if (num(m)) contexte.push(`Médiane des deux académies : ${fr(m, 1)}.`);
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
      if (meds.length) contexte.push(`Médianes : ${meds.join(", ")}.`);
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
      if (num(d.rang)) contexte.push(`${d.rang}e sur ${fr(d.nb, 0)} collèges des deux académies en ${d.session}.`);
      if (num(m)) contexte.push(`Médiane : ${fr(m, 1)}.`);
      contexte.push("Moyenne des taux de réussite, de mentions et de mentions très bien : à lire avec précaution.");
      res.push({
        cle: "score", nom: "Score", titre: "Score agrégé (optionnel)",
        valeur: fr(d.score, 1), unite: d.session, contexte: contexte.join(" "),
        graphe: { labels: br.map((r) => r.session), aria: `Score agrégé par session : ${decrire(br, "session", "score", (v) => fr(v, 1))}.`,
          panneaux: [{ tick: (t) => fr(t, 0), echelle: { plancher: 0, plafond: 100, etendueMin: 20 }, series: [
            { vals: col(br, "score"), med: medB("score"), couleur: ENCRE, nom: "score" },
          ] }] },
        table: tableau([{ cle: "session", nom: "Session" }, { cle: "score", nom: "Score", fmt: (v) => fr(v, 1) }, { cle: "rang", nom: "Rang", fmt: (v) => fr(v, 0) }, { cle: "nb", nom: "Sur", fmt: (v) => fr(v, 0) }], br),
      });
    }
    return res;
  }

  function afficherOnglet() {
    const liste = ficheCourante.onglets;
    const o = liste.find((x) => x.cle === ongletChoisi) || liste[0];
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
        <span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${ENCRE}" stroke-width="2.5" stroke-linecap="round"/></svg>Trait plein : ce collège</span>
        ${avecMediane ? `<span><svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 4H21" stroke="${ENCRE}" stroke-opacity="0.55" stroke-width="2" stroke-dasharray="4 3"/></svg>Pointillés de même couleur : médiane Paris et Versailles</span>` : ""}
      </div>
      <details class="valeurs"><summary>Valeurs par année</summary>${o.table}</details>`;
  }

  function surlignerSecteur(uai) {
    if (carte.getLayer("secteurs-surligne")) carte.setFilter("secteurs-surligne", ["==", ["get", "uai"], uai || ""]);
  }

  function ouvrirFiche(p) {
    surlignerSecteur(p.uai);
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
    surlignerSecteur(null);
    $("fiche").hidden = true;
    document.body.classList.remove("fiche-ouverte");
  }

  // ---------------------------------------------------------------- recherche
  // Un seul champ : collèges et communes cherchés dans les données chargées,
  // adresses via le service de géocodage de l'IGN (Géoplateforme).
  const GEOCODAGE_COMPLETION = "https://data.geopf.fr/geocodage/completion/";
  const GEOCODAGE_RECHERCHE = "https://data.geopf.fr/geocodage/search";
  const DEPS = ["75", "78", "91", "92", "95"];
  const normaliser = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  let repereAdresse = null;

  // Centre la carte sur un point en laissant de la place à la fiche (en bas sur mobile, à droite sur ordinateur).
  function centrer(coord, zoom) {
    const mobile = window.innerWidth < 760;
    carte.flyTo({ center: coord, zoom, duration: 600,
      padding: mobile ? { top: 20, bottom: Math.round(window.innerHeight * 0.55), left: 0, right: 0 } : { top: 0, bottom: 0, left: 340, right: 420 } });
  }

  function distanceKm(a, b) {
    const R = 6371, rad = Math.PI / 180;
    const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function chercherLocal(q) {
    const mots = normaliser(q).split(" ").filter(Boolean);
    if (!mots.length) return { colleges: [], communes: [] };
    const colleges = [], communes = new Map();
    donnees.features.forEach((f) => {
      const p = f.properties;
      const texte = normaliser(p.nom + " " + p.commune);
      if (mots.every((m) => texte.includes(m))) {
        const nomN = normaliser(p.nom).replace(/^college /, "");
        colleges.push({ f, rang: nomN.startsWith(mots[0]) ? 0 : 1 });
      }
      const com = normaliser(p.commune);
      if (mots.every((m) => com.includes(m))) {
        const cle = p.commune + "|" + p.dep;
        if (!communes.has(cle)) communes.set(cle, { nom: p.commune, departement: p.departement, rang: com.startsWith(mots[0]) ? 0 : 1, features: [] });
        communes.get(cle).features.push(f);
      }
    });
    colleges.sort((a, b) => a.rang - b.rang || a.f.properties.nom.localeCompare(b.f.properties.nom, "fr"));
    const listeCom = [...communes.values()].sort((a, b) => a.rang - b.rang || a.nom.localeCompare(b.nom, "fr"));
    return { colleges: colleges.slice(0, 5).map((c) => c.f), communes: listeCom.slice(0, 3) };
  }

  // Adresses : service d'autocomplétion, puis recherche classique en secours.
  async function chercherAdresses(q, signal) {
    try {
      const url = `${GEOCODAGE_COMPLETION}?text=${encodeURIComponent(q)}&type=StreetAddress&maximumResponses=5&terr=${DEPS.join(",")}`;
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
      .filter((f) => DEPS.includes(String(f.properties.postcode || f.properties.citycode || "").slice(0, 2)))
      .slice(0, 5)
      .map((f) => ({ libelle: f.properties.label, detail: f.properties.context || "", coord: f.geometry.coordinates }));
  }

  function initRecherche() {
    const champ = $("recherche"), liste = $("suggestions");
    let options = [], actif = -1, minuteur = null, controleur = null, local = { colleges: [], communes: [] }, adresses = [], etatAdresses = "";

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
      groupe("Communes", local.communes.map((c) => ({ type: "commune", c, libelle: c.nom, detail: `${c.departement}, ${c.features.length} collège${c.features.length > 1 ? "s" : ""}` })));
      groupe("Adresses", adresses.map((a) => ({ type: "adresse", a, libelle: a.libelle, detail: a.detail })));
      if (etatAdresses) html += `<li class="info" role="presentation">${etatAdresses}</li>`;
      if (!html) html = `<li class="info" role="presentation">Aucun résultat. Essayez le nom d'un collège, une commune ou une adresse avec son numéro.</li>`;
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
          etatAdresses = "La recherche d'adresses ne répond pas pour le moment. Les collèges et les communes restent cherchables.";
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
  function montrerAdresse(a) {
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
        ? "Le secteur est reconstitué à partir de la carte scolaire officielle et peut différer à la marge, notamment en limite de secteur. Pour une inscription, la réponse qui fait foi est celle de l'inspection académique."
        : "Aucun secteur n'a été trouvé pour cette adresse. Le collège le plus proche n'est pas forcément le collège de secteur."}</p>`;
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
  let secteurs = null;

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
    if (!secteurs) return null;
    for (const f of secteurs.features) {
      const g = f.geometry;
      const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      if (polys.some((poly) => dansPolygone(pt, poly))) return f.properties.uai;
    }
    return null;
  }

  function chargerSecteurs() {
    fetch("data/secteurs.geojson").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((geo) => {
      // Chaque zone reçoit les indicateurs de son collège, pour être colorée comme lui.
      const parUai = new Map(donnees.features.map((f) => [f.properties.uai, f.properties]));
      geo.features.forEach((f) => {
        const p = parUai.get(f.properties.uai);
        if (p) INDICATEURS.forEach((i) => { if (typeof p[i.cle] === "number") f.properties[i.cle] = p[i.cle]; });
      });
      secteurs = geo;
      carte.addSource("secteurs", { type: "geojson", data: geo });
      carte.addLayer({ id: "secteurs-fond", type: "fill", source: "secteurs", paint: { "fill-color": ABSENT, "fill-opacity": 0.35 } }, "colleges");
      carte.addLayer({ id: "secteurs-contour", type: "line", source: "secteurs", paint: { "line-color": "#1e2f6b", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.3, 14, 1.2], "line-opacity": 0.55 } }, "colleges");
      carte.addLayer({ id: "secteurs-surligne", type: "line", source: "secteurs", filter: ["==", ["get", "uai"], ""], paint: { "line-color": "#1e2f6b", "line-width": 3 } }, "colleges");
      appliquer();
      if (ficheCourante) surlignerSecteur(ficheCourante.p.uai);
    }).catch((e) => console.warn("Secteurs indisponibles", e));
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
    initRecherche();
    chargerSecteurs();
    etat.textContent = "";
    carte.on("click", (e) => {
      const pt = carte.queryRenderedFeatures(e.point, { layers: ["colleges"] })[0];
      if (pt) { ouvrirFiche(pt.properties); return; }
      if (!carte.getLayer("secteurs-fond") || !$("voir-zones").checked) return;
      const z = carte.queryRenderedFeatures(e.point, { layers: ["secteurs-fond"] })[0];
      const f = z && donnees.features.find((x) => x.properties.uai === z.properties.uai);
      if (f) ouvrirFiche(f.properties);
    });
    carte.on("mouseenter", "colleges", () => (carte.getCanvas().style.cursor = "pointer"));
    carte.on("mouseleave", "colleges", () => (carte.getCanvas().style.cursor = ""));
  }).catch((err) => {
    etat.textContent = "Les données des collèges n'ont pas pu être chargées. Rechargez la page ; si le problème continue, les données sont peut-être en cours de mise à jour.";
    console.error(err);
  });

  $("voir-public").addEventListener("change", () => donnees && appliquer());
  $("voir-prive").addEventListener("change", () => donnees && appliquer());
  $("voir-zones").addEventListener("change", () => donnees && appliquer());
  $("fermer").addEventListener("click", fermerFiche);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") fermerFiche(); });
})();
