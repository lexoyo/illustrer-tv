#!/usr/bin/env python3
"""Mesure un décideur local sur `cas.json`. À lancer SUR le Pi.

    ./.venv/bin/python bench_decideur.py ~/bench/models/qwen25-05b-q4.gguf

Le chiffre qui décide n'est pas la justesse globale : le jeu est déséquilibré
exprès (12 « non » pour 5 « oui »), donc un modèle qui répond toujours non
obtient 12/17 = 0,71 sans rien comprendre. **Ce qui tranche, ce sont les FAUX
POSITIFS** — chacun est une image sans rapport sur la télé — puis, seulement
ensuite, le rappel sur les « oui ».
"""
import argparse, json, re, statistics, subprocess, sys, time
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import decideur_local as dl


def temp():
    try:
        out = subprocess.run(["/usr/bin/vcgencmd", "measure_temp"],
                             capture_output=True, text=True, timeout=5).stdout
        return float(re.search(r"([\d.]+)", out).group(1))
    except Exception:
        return float("nan")


def throttled():
    try:
        return subprocess.run(["/usr/bin/vcgencmd", "get_throttled"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("modele")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--port", type=int, default=dl.PORT)
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--sortie", default=None, help="fichier JSON de résultats")
    ap.add_argument("--ancrage", action="store_true",
                    help="limiter la requête aux mots présents dans le bloc "
                         "(mesuré : meilleures requêtes, +1 faux positif)")
    ap.add_argument("--attendre-froid", type=float, default=60.0,
                    help="ne pas commencer au-dessus de cette température")
    a = ap.parse_args()

    cas = json.loads((ICI / "cas.json").read_text())["cas"]

    t = temp()
    while t > a.attendre_froid:
        print(f"  {t:.1f} °C — on attend {a.attendre_froid} °C…", flush=True)
        time.sleep(20)
        t = temp()
    print(f"départ à {t:.1f} °C · {throttled()}", flush=True)

    d = dl.Decideur(modele=a.modele, threads=a.threads, port=a.port, ctx=a.ctx,
                    ancrage=a.ancrage)
    lignes, lat = [], []
    try:
        for c in cas:
            t0 = time.monotonic()
            try:
                v = d(c["texte"], c["sujet"])
                err = None
            except Exception as e:
                v, err = {"illustrer": False, "pourquoi": f"ERREUR {e}"}, str(e)
            dt = time.monotonic() - t0
            lat.append(dt)
            got = bool(v.get("illustrer"))
            req = v.get("requete", "")
            pertinent = None
            if c["attendu"] and got:
                pertinent = any(m in req.lower() for m in c.get("attendu_requete", []))
            lignes.append({"id": c["id"], "attendu": c["attendu"], "obtenu": got,
                           "requete": req, "pourquoi": v.get("pourquoi", ""),
                           "pertinent": pertinent, "s": round(dt, 2),
                           "piege": c.get("piege", False), "erreur": err,
                           "temp": temp()})
            marque = "ok " if got == c["attendu"] else ("FP!" if got else "FN ")
            print(f"  {marque} {c['id']:22s} {dt:5.1f}s  "
                  f"{'OUI ' + req if got else 'non'}"
                  f"{'' if pertinent is None else ('  [requête juste]' if pertinent else '  [requête à côté]')}",
                  flush=True)
    finally:
        d.fermer()

    non = [l for l in lignes if not l["attendu"]]
    oui = [l for l in lignes if l["attendu"]]
    fp = [l for l in non if l["obtenu"]]
    fn = [l for l in oui if not l["obtenu"]]
    justes = [l for l in oui if l["obtenu"] and l["pertinent"]]
    res = {
        "modele": Path(a.modele).name, "threads": a.threads,
        "ancrage": a.ancrage,
        "prefixe_s": round(d.chauffe_s, 1),
        "n": len(lignes), "n_non": len(non), "n_oui": len(oui),
        "faux_positifs": len(fp), "faux_positifs_ids": [l["id"] for l in fp],
        "faux_negatifs": len(fn), "faux_negatifs_ids": [l["id"] for l in fn],
        "justesse": round(sum(1 for l in lignes if l["obtenu"] == l["attendu"]) / len(lignes), 3),
        "rappel_oui": round(len(oui) - len(fn), 3),
        "requetes_pertinentes": len(justes),
        "erreurs": sum(1 for l in lignes if l["erreur"]),
        "latence_med_s": round(statistics.median(lat), 1),
        "latence_max_s": round(max(lat), 1),
        "temp_fin": temp(), "throttled": throttled(),
        "lignes": lignes,
    }
    print(json.dumps({k: v for k, v in res.items() if k != "lignes"},
                     ensure_ascii=False, indent=1))
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"→ {a.sortie}")


if __name__ == "__main__":
    main()
