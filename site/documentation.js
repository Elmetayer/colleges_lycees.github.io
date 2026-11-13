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
        Object.entries(ctrl).map(([nom, v]) => `${nom} : ${pc(v.taux_surface)} de la surface est attribuée au même collège`).join(" ; ") + ".";
    }
    const c = m.colleges, p = m.periodes;
    const liste = (a) => a && a.length ? a.join(", ") : "aucune";
    const resume = document.getElementById("resume-donnees");
    if (resume) resume.textContent =
      `Données générées le ${date(m.genere_le)} : ${c.total} collèges (${c.publics} publics, ${c.prives} privés). ` +
      `Sessions du brevet : ${liste(p.brevet)}. IPS : ${liste(p.ips)}. Évaluations de 6e : ${liste(p.eval6e)}.` +
      (m.lycees ? ` ${m.lycees.total} lycées (${m.lycees.publics} publics, ${m.lycees.prives} privés). Sessions du bac : ${liste(m.lycees.periodes.gt)}. IPS des lycées : ${liste(m.lycees.periodes.ips)}.` : "");
  }).catch(() => {
    const sourcesEl = document.getElementById("liste-sources");
    if (sourcesEl) sourcesEl.innerHTML = "<tr><td colspan='2'>La liste des sources n'a pas pu être chargée.</td></tr>";
    const resume = document.getElementById("resume-donnees");
    if (resume) resume.textContent = "Le résumé des données n'a pas pu être chargé.";
  });
})();
