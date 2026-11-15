/* Page de suivi des données : rapport du dernier build (pipeline/suivi.py).
   Deux sources : data/suivi.json, le rapport du build qui a produit ce site ; et la branche suivi-donnees du dépôt
   (dernier.json, historique.json), où chaque build de main range son rapport, même en échec. Le plus récent
   des deux est affiché ; un build en échec plus récent que le site est signalé en tête. */
(function () {
  "use strict";
  const DEPOT = "https://raw.githubusercontent.com/Elmetayer/colleges_lycees.github.io/suivi-donnees/suivi/";
  const ETATS = {
    ok: { label: "OK", icone: "M3.5 8.5 L6.5 11.5 L12.5 4.5" },
    partiel: { label: "Partiel", icone: "M8 3.5 V9 M8 12 V12.2" },
    ko: { label: "Pas OK", icone: "M4.5 4.5 L11.5 11.5 M11.5 4.5 L4.5 11.5" },
  };
  const GLOBAL = { ok: "Tout est à jour", partiel: "Mise à jour partielle", ko: "Données manquantes" };
  const $ = (id) => document.getElementById(id);
  const echapper = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nombre = (n) => (typeof n === "number" ? n.toLocaleString("fr-FR") : n == null ? "—" : String(n));
  const date = (iso, heure) => {
    if (!iso) return "—";
    const d = new Date(String(iso).length === 10 ? iso + "T12:00:00" : iso);
    if (isNaN(d)) return String(iso);
    const j = d.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Paris" });
    return heure ? `${j} à ${d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" })}` : j;
  };
  const court = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? "—" : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", timeZone: "Europe/Paris" })
      + " " + d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });
  };
  const icone = (e, t) => `<svg width="${t}" height="${t}" viewBox="0 0 16 16" aria-hidden="true"><path d="${ETATS[e].icone}" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  const pastille = (e) => `<span class="s-etat s-etat-${e}">${icone(e, 14)}${ETATS[e].label}</span>`;
  const charger = (url) => fetch(url, { cache: "no-store" }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

  let rapport = null, filtre = "tout";
  const ouverts = new Set();

  function afficherGroupes() {
    $("suivi-groupes").innerHTML = rapport.groupes.map((g) => {
      const n = { ok: 0, partiel: 0, ko: 0 };
      g.lignes.forEach((l) => n[l.etat]++);
      const resume = [n.ok && `${n.ok} OK`, n.partiel && `${n.partiel} partiel${n.partiel > 1 ? "s" : ""}`, n.ko && `${n.ko} pas OK`].filter(Boolean).join(" · ");
      const lignes = g.lignes.filter((l) => filtre === "tout" || l.etat === filtre);
      return `<section class="suivi-bloc">
        <div class="suivi-titre-bloc"><h2 id="${echapper(g.cle)}">${echapper(g.titre)}</h2><span>${resume || "aucune source"}</span></div>
        <div class="suivi-table"><table class="table-sources">
          <thead><tr><th scope="col">Source</th><th scope="col" class="nb">Lignes récupérées</th><th scope="col">Sur la carte</th><th scope="col">Mise à jour</th><th scope="col">État</th><th scope="col"><span class="visually-hidden">Détails</span></th></tr></thead>
          <tbody>${lignes.length ? lignes.map(ligne).join("") : `<tr><td colspan="6" class="vide">Aucune source dans cet état.</td></tr>`}</tbody>
        </table></div></section>`;
    }).join("");
    document.querySelectorAll("[data-details]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.details;
      if (ouverts.has(k)) ouverts.delete(k); else ouverts.add(k);
      afficherGroupes();
      const nb = document.querySelector(`[data-details="${CSS.escape(k)}"]`);
      if (nb) nb.focus();
    }));
  }

  function ligne(l) {
    const ouvert = ouverts.has(l.cle);
    const titre = l.page ? `<a href="${echapper(l.page)}">${echapper(l.titre)}</a>` : echapper(l.titre);
    const maj = [l.mise_a_jour && `producteur : ${date(l.mise_a_jour)}`, l.telecharge_le && `téléchargée le ${court(l.telecharge_le)}`].filter(Boolean);
    const details = ouvert ? `<tr class="suivi-details"><td colspan="6"><dl>${(l.details || []).map((d) =>
      `<div><dt>${echapper(d[0])}</dt><dd class="${d[2] ? "ton-" + d[2] : ""}">${echapper(d[1])}</dd></div>`).join("")}</dl></td></tr>` : "";
    return `<tr class="suivi-ligne">
      <td><span class="suivi-source">${titre}</span><small>${echapper(l.producteur)}</small></td>
      <td class="nb">${nombre(l.lignes)}</td>
      <td>${echapper(l.carte)}</td>
      <td class="maj">${maj.map((m, i) => (i ? `<small>${echapper(m)}</small>` : `<span>${echapper(m)}</span>`)).join("") || "—"}</td>
      <td>${pastille(l.etat)}</td>
      <td><button type="button" class="suivi-bouton" data-details="${echapper(l.cle)}" aria-expanded="${ouvert}">${ouvert ? "Masquer" : "Détails"}</button></td>
    </tr>${details}`;
  }

  function afficherFiltres() {
    const toutes = rapport.groupes.flatMap((g) => g.lignes);
    const n = (e) => toutes.filter((l) => l.etat === e).length;
    $("suivi-filtres").innerHTML = [["tout", `Toutes (${toutes.length})`], ["ok", `OK (${n("ok")})`], ["partiel", `Partiel (${n("partiel")})`], ["ko", `Pas OK (${n("ko")})`]]
      .map(([k, t]) => `<button type="button" class="suivi-filtre" data-filtre="${k}" aria-pressed="${k === filtre}">${t}</button>`).join("");
    document.querySelectorAll("[data-filtre]").forEach((b) => b.addEventListener("click", () => {
      filtre = b.dataset.filtre;
      afficherFiltres();
      afficherGroupes();
      document.querySelector(`[data-filtre="${filtre}"]`).focus();
    }));
  }

  function afficherControles() {
    const c = rapport.controles || [];
    $("suivi-controles").innerHTML = c.length ? c.map((x) => {
      const pct = !!x.unite;
      const max = pct ? 100 : Math.max(x.valeur || 0, x.seuil) * 1.25;
      const f = (v) => (pct ? `${nombre(v)} %` : nombre(v));
      return `<div class="suivi-controle${x.ok ? "" : " rate"}" role="img" aria-label="${echapper(`${x.libelle} : ${f(x.valeur)}, seuil ${f(x.seuil)}${x.ok ? "" : ", sous le seuil"}`)}">
        <span>${echapper(x.libelle)}</span>
        <span class="jauge" aria-hidden="true"><span style="width:${Math.min(100, Math.round(((x.valeur || 0) / max) * 100))}%"></span><i style="left:${Math.round((x.seuil / max) * 100)}%"></i></span>
        <span class="nb"><b>${f(x.valeur)}</b><small>seuil ${f(x.seuil)}</small></span>
      </div>`;
    }).join("") : `<p class="vide">${rapport.statut === "en_cours" ? "Les contrôles n'ont pas encore été passés pour ce rapport provisoire." : "Aucun contrôle consigné : la vérification ne s'est pas lancée."}</p>`;
    const nav = rapport.navigateur || {};
    const appareils = Object.keys(nav);
    $("suivi-navigateur").textContent = "Barre : valeur obtenue ; trait vertical : seuil. Test dans un navigateur (ordinateur et téléphone) : "
      + (appareils.length ? appareils.map((a) => `${a} ${nav[a].ok ? "réussi" : "en échec"}`).join(", ") : "non passé") + "."
      + (rapport.erreurs && rapport.erreurs.length ? ` Problèmes bloquants : ${rapport.erreurs.join(" ; ")}.` : "");
  }

  function afficherHistorique(hist) {
    if (!hist || !hist.length) {
      $("suivi-historique").innerHTML = `<p class="vide">L'historique commence avec la prochaine mise à jour automatique.</p>`;
      return;
    }
    const builds = hist.slice(0, 10).reverse();
    const titres = {};
    builds.forEach((b) => Object.assign(titres, b.titres || {}));
    const cles = Object.keys(titres);
    const cellule = (e) => (e ? `<span class="carre s-etat-${e}" title="${ETATS[e].label}">${icone(e, 12)}<span class="visually-hidden">${ETATS[e].label}</span></span>` : `<span class="carre absent" title="absente">–</span>`);
    $("suivi-historique").innerHTML = `<div class="suivi-table"><table>
      <thead><tr><th scope="col">Source</th>${builds.map((b) => `<th scope="col" class="col-build">${b.lien ? `<a href="${echapper(b.lien)}">${court(b.genere_le)}</a>` : court(b.genere_le)}<small>${b.statut === "publie" ? "publié" : b.statut === "echec" ? "non publié" : "en cours"}</small></th>`).join("")}</tr></thead>
      <tbody>
        <tr class="ligne-global"><th scope="row">Ensemble</th>${builds.map((b) => `<td>${cellule(b.statut === "echec" ? "ko" : b.etat)}</td>`).join("")}</tr>
        ${cles.map((k) => `<tr><th scope="row">${echapper(titres[k])}</th>${builds.map((b) => `<td>${cellule((b.sources || {})[k])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div>`;
  }

  function afficher(local, hist) {
    const ch = rapport.chiffres || {};
    const n = rapport.compte || {};
    const echec = rapport.statut === "echec";
    const e = echec ? "ko" : rapport.etat;
    $("suivi-etat").className = `s-etat s-etat-${e} s-etat-grand`;
    $("suivi-etat").innerHTML = `${icone(e, 16)}${echec ? "Dernière mise à jour en échec" : GLOBAL[e]}`;
    $("suivi-quand").textContent = (rapport.statut === "en_cours" ? "Rapport provisoire du " : "Mise à jour du ") + date(rapport.genere_le, true);
    const alertes = [];
    if (echec && local && local !== rapport) alertes.push(`La mise à jour du ${date(rapport.genere_le, true)} a échoué et n'a pas été publiée : la carte affichée date du ${date(local.genere_le, true)}.`);
    else if (echec) alertes.push("Cette mise à jour a échoué et n'a pas été publiée : la carte garde sa version précédente.");
    const manquantes = rapport.groupes.flatMap((g) => g.lignes).filter((l) => l.etat === "ko").map((l) => l.titre);
    const reprises = rapport.groupes.flatMap((g) => g.lignes).filter((l) => l.etat === "partiel").map((l) => l.titre);
    if (manquantes.length) alertes.push(`Absentes de cette mise à jour : ${manquantes.join(", ")}.`);
    if (reprises.length) alertes.push(`Partielles : ${reprises.join(", ")} (voir les détails).`);
    $("suivi-alerte").hidden = !alertes.length;
    $("suivi-alerte").textContent = alertes.join(" ");
    const tuile = (l, v, u) => `<div class="suivi-tuile"><span>${echapper(l)}</span><b>${echapper(v)}</b><small>${echapper(u)}</small></div>`;
    const villes = ch.villes_ecoles || [];
    $("suivi-tuiles").innerHTML = [
      tuile("Sources", nombre((n.ok || 0) + (n.partiel || 0) + (n.ko || 0)), `${n.ok || 0} OK · ${n.partiel || 0} partielle${(n.partiel || 0) > 1 ? "s" : ""} · ${n.ko || 0} pas OK`),
      tuile("Établissements sur la carte", nombre((ch.colleges || 0) + (ch.lycees || 0) + (ch.ecoles || 0)), `${nombre(ch.colleges)} collèges, ${nombre(ch.lycees)} lycées, ${nombre(ch.ecoles)} écoles`),
      tuile("Secteurs des collèges", `${nombre(ch.secteurs_departements)} / ${ch.departements || 96}`, "départements (les autres sont absents de la carte scolaire nationale)"),
      tuile("Secteurs des écoles", `${villes.length} ville${villes.length > 1 ? "s" : ""}`, villes.join(", ") || "aucune"),
    ].join("");
    if (rapport.build && rapport.build.lien) $("suivi-journal").href = rapport.build.lien;
    afficherFiltres();
    afficherGroupes();
    afficherControles();
    afficherHistorique(hist);
    $("suivi").setAttribute("data-pret", "");
  }

  Promise.allSettled([charger("data/suivi.json"), charger(DEPOT + "dernier.json"), charger(DEPOT + "historique.json")]).then(([l, d, h]) => {
    const local = l.status === "fulfilled" ? l.value : null;
    const dernier = d.status === "fulfilled" ? d.value : null;
    rapport = dernier && (!local || dernier.genere_le > local.genere_le) ? dernier : local;
    if (!rapport) {
      $("suivi-etat").textContent = "Rapport indisponible";
      $("suivi-alerte").hidden = false;
      $("suivi-alerte").textContent = "Le rapport de la dernière mise à jour n'a pas pu être chargé.";
      $("suivi").setAttribute("data-pret", "");
      return;
    }
    afficher(local, h.status === "fulfilled" ? h.value : null);
  });
})();
