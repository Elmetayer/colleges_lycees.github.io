/* Documentation : valeurs calculées (seuils, sources, contrôle des secteurs, résumé des données) et sommaire des pages. */
(function () {

// Sommaire de la page, construit à partir de ses sous-titres (à partir de trois).
const nav = document.querySelector(".doc-sommaire");
const titres = [...document.querySelectorAll("main h2[id]")];
if (nav && titres.length >= 3) {
  nav.innerHTML = "<p>Sur cette page</p><ol>" + titres.map((h) => `<li><a href="#${h.id}">${h.textContent}</a></li>`).join("") + "</ol>";
  nav.hidden = false;
}
  const va = (window.PARAMETRES && window.PARAMETRES.valeurAjoutee) || null;
  if (va) {
    const n = (v) => Number(v).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
    const borne = (v) => `−${n(v)} et +${n(v)}`;
    const poser = (cle, txt) => document.querySelectorAll(`[data-param="${cle}"]`).forEach((e) => { e.textContent = txt; });
    if (va.seuils && va.seuils.va_reussite != null) poser("seuil-reussite", borne(va.seuils.va_reussite));
    if (va.seuils && va.seuils.va_note != null) poser("seuil-note", borne(va.seuils.va_note));
    if (va.libelles && va.libelles.proche) poser("libelle-proche", va.libelles.proche);
    if (va.seuils && va.seuils.gt_va_reussite != null) poser("seuil-lycee", borne(va.seuils.gt_va_reussite));
  }
  const date = (s) => s ? new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "Non renseignée";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  fetch("data/meta.json").then((r) => r.json()).then((m) => {
    const sourcesEl = document.getElementById("liste-sources");
    if (sourcesEl) sourcesEl.innerHTML = m.sources.map((s) =>
      `<tr><td>${s.page ? `<a href="${esc(s.page)}">${esc(s.titre)}</a>` : esc(s.titre)}</td><td>${date(s.mise_a_jour)}${s.version_reprise ? `<br><small>Source injoignable lors du dernier calcul : version téléchargée le ${date(s.version_reprise)} conservée</small>` : ""}</td></tr>`).join("");
    const ctrl = m.secteurs && m.secteurs.controle;
    if (ctrl && Object.keys(ctrl).length && document.getElementById("controle-secteurs")) {
      const pc = (v) => Math.round(v * 100) + " %";
      document.getElementById("controle-secteurs").textContent =
        "Pour contrôler la méthode, les zones obtenues sont comparées aux secteurs officiels dessinés par la Ville de Paris et par le département des Hauts-de-Seine. " +
        Object.entries(ctrl).map(([nom, v]) => `${nom} : ${pc(v.taux_surface)} de la surface est attribuée au même collège`).join(" ; ") + "." +
        " Si cette part descend sous 85 % pour l'un des deux, les nouveaux secteurs ne sont pas publiés et le site garde sa version précédente.";
    }
    const sb = m.colleges && m.colleges.sans_brevet;
    if (sb && document.getElementById("colleges-sans-brevet")) {
      const n = (k) => (sb[k] || 0).toLocaleString("fr-FR");
      const total = Object.values(sb).reduce((a, b) => a + b, 0);
      document.getElementById("colleges-sans-brevet").textContent =
        `${total.toLocaleString("fr-FR")} collèges sur ${m.colleges.total.toLocaleString("fr-FR")} n'ont pas de résultats au brevet dans les données publiques : ` +
        `${n("hors_contrat")} privés hors contrat, ${n("recent")} ouverts récemment, ${n("annexe")} sites rattachés à un autre collège et ${n("non_publie")} petits collèges. La fiche du collège en donne la raison :`;
    }
    const c = m.colleges, p = m.periodes;
    const liste = (a) => a && a.length ? a.join(", ") : "aucune";
    const resume = document.getElementById("resume-donnees");
    if (resume) resume.textContent =
      `Données générées le ${date(m.genere_le)} : ${c.total} collèges (${c.publics} publics, ${c.prives} privés). ` +
      `Sessions du brevet : ${liste(p.brevet)}. IPS : ${liste(p.ips)}. Évaluations de 6e : ${liste(p.eval6e)}.` +
      (m.lycees ? ` ${m.lycees.total} lycées (${m.lycees.publics} publics, ${m.lycees.prives} privés). Sessions du bac : ${liste(m.lycees.periodes.gt)}. IPS des lycées : ${liste(m.lycees.periodes.ips)}.` : "") +
      (m.ecoles ? ` ${m.ecoles.total} écoles (${m.ecoles.publics} publiques, ${m.ecoles.prives} privées). IPS des écoles : ${liste(m.ecoles.periodes.ips)}. Effectifs : rentrée ${m.ecoles.periodes.effectifs || "non disponible"}. Taille des classes : ${m.ecoles.periodes.classes || "non disponible"}.` : "");
    const ec = m.ecoles, ecEl = document.getElementById("ecoles-chiffres");
    if (ec && ecEl) {
      const n = (v) => Number(v || 0).toLocaleString("fr-FR"), cv = ec.couverture || {}, nv = ec.niveaux || {};
      ecEl.textContent = `${n(ec.total)} écoles sur la carte : ${n(nv.maternelle)} maternelles, ${n(nv.elementaire)} élémentaires et ${n(nv.primaire)} primaires ; ` +
        `${n(ec.publics)} publiques et ${n(ec.prives)} privées, dont ${n(ec.hors_contrat)} hors contrat. IPS connu pour ${n(cv.ips)} écoles, ` +
        `effectifs pour ${n(cv.eleves)}, taille des classes pour ${n(cv.classe)}.`;
    }
  }).catch(() => {
    const sourcesEl = document.getElementById("liste-sources");
    if (sourcesEl) sourcesEl.innerHTML = "<tr><td colspan='2'>La liste des sources n'a pas pu être chargée.</td></tr>";
    const resume = document.getElementById("resume-donnees");
    if (resume) resume.textContent = "Le résumé des données n'a pas pu être chargé.";
  });
})();
