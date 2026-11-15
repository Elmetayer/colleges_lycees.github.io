"""Diagnostic 7b : pipeline des écoles et des secteurs de Paris seulement (vraies données)."""
import sys
from pathlib import Path
sys.path.insert(0, "pipeline")
import build, ecoles, secteurs_ecoles
frames, pb = {}, []
for k in ["etablissements", "annuaire_education", "secteurs_paris_elementaires", "ecoles_paris_elementaires", "secteurs_paris_maternelles", "ecoles_paris_maternelles"]:
    print("==", k)
    src = build.resolve(k)
    frames[k], p = build.obtenir(k, src, None)
    print("   page", src.get("page"), "maj", src.get("maj"))
tous = build.load_etablissements(frames["etablissements"])
out = Path("/tmp/out"); out.mkdir(exist_ok=True)
meta, df = ecoles.construire(tous, frames, out, pb)
print("== secteurs")
m = secteurs_ecoles.construire(df, frames, out, pb)
import json; print(json.dumps(m, ensure_ascii=False)[:3000]); print("problèmes", pb)
