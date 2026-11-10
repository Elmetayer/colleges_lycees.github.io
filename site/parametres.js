/*
 * Paramètres de la carte scolaire.
 * Modifiez les valeurs ci-dessous puis enregistrez : la carte et la page Documentation
 * les prennent en compte au prochain chargement. Pas besoin de toucher à app.js.
 *
 * Dans les textes, les mots entre accolades sont remplacés automatiquement :
 *   {min} et {max}  bornes de la zone neutre (ex. −2,0 et +2,0)
 *   {unite}         unité de l'indicateur (points ou point)
 *   {dessous}, {proches}, {dessus}  part des établissements dans chaque catégorie, en %
 *   {etablissements} « collèges » ou « lycées »
 */
window.PARAMETRES = {
  valeurAjoutee: {
    // Largeur de la zone neutre « proche de l'attendu », de part et d'autre de zéro.
    // Un établissement dont la valeur ajoutée est comprise entre -seuil et +seuil est affiché en gris très clair.
    seuils: {
      va_reussite: 2,   // en points de pourcentage (réussite au brevet)
      va_note: 0.3,     // en points sur 20 (note aux écrits)
      // Lycées, en points de pourcentage
      gt_va_reussite: 2,  // réussite au bac, voie générale et technologique
      gt_va_acces: 2,     // accès de la seconde au bac, voie générale et technologique
      pro_va_reussite: 2, // réussite au bac professionnel
      pro_va_acces: 2,    // accès de la seconde au bac, voie professionnelle
    },

    // Libellés affichés dans la légende et dans la fiche d'un établissement.
    libelles: {
      proche: "proche de l'attendu",
      dessous: "en dessous de l'attendu",
      dessus: "au-dessus de l'attendu",
    },

    // Phrases de la légende.
    texteZone: "Entre {min} et {max} {unite}, l'écart est considéré comme faible.",
    texteRepartition: "{dessous} % des {etablissements} en dessous de l'attendu, {proches} % proches, {dessus} % au-dessus.",
  },
};
