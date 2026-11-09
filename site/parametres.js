/*
 * Paramètres de la carte scolaire.
 * Modifiez les valeurs ci-dessous puis enregistrez : la carte et la page Documentation
 * les prennent en compte au prochain chargement. Pas besoin de toucher à app.js.
 *
 * Dans les textes, les mots entre accolades sont remplacés automatiquement :
 *   {min} et {max}  bornes de la zone neutre (ex. −2,0 et +2,0)
 *   {unite}         unité de l'indicateur (points ou point)
 *   {dessous}, {proches}, {dessus}  part des collèges dans chaque catégorie, en %
 */
window.PARAMETRES = {
  valeurAjoutee: {
    // Largeur de la zone neutre « proche de l'attendu », de part et d'autre de zéro.
    // Un collège dont la valeur ajoutée est comprise entre -seuil et +seuil est affiché en gris très clair.
    seuils: {
      va_reussite: 2,   // en points de pourcentage (réussite au brevet)
      va_note: 0.3,     // en points sur 20 (note aux écrits)
    },

    // Libellés affichés dans la légende et dans la fiche d'un collège.
    libelles: {
      proche: "proche de l'attendu",
      dessous: "en dessous de l'attendu",
      dessus: "au-dessus de l'attendu",
    },

    // Phrases de la légende.
    texteZone: "Entre {min} et {max} {unite}, l'écart est considéré comme faible.",
    texteRepartition: "{dessous} % des collèges en dessous de l'attendu, {proches} % proches, {dessus} % au-dessus.",
  },
};
