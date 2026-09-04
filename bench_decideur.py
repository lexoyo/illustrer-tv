#!/usr/bin/env python3
"""Mesure un décideur local sur `cas.json`. À lancer SUR le Pi.

    ./.venv/bin/python bench_decideur.py ~/bench/models/qwen25-05b-q4.gguf

⚠️ **Ce banc ne mesure plus une décision, parce qu'il n'y en a plus.** Depuis le
04/09/2026 au soir le modèle n'a plus ni consigne ni grammaire : on lui donne la
transcription du bloc, ce qu'il écrit ensuite est la requête d'image, et
`illustrer` vaut toujours vrai (cf. `decideur_local.py`). Les colonnes faux
positifs / faux négatifs sont donc mortes, et l'`attendu` de `cas.json` avec
elles.

Ce qu'il mesure encore, et qui reste utile : **la latence par bloc** et **ce que
le modèle écrit** sur des textes propres. Le jeu de 17 cas garde son intérêt de
non-régression : ils sont courts et connus, donc un chiffre de latence qui bouge
ici vient de la machine ou du modèle, pas du texte. Pour juger de ce que ça donne
en vrai, il faut des blocs de longueur réelle — les 17 cas font 5 à 10 fois moins
de tokens qu'un bloc de 45 s, et la latence en dépend directement.
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

    d = dl.Decideur(modele=a.modele, threads=a.threads, port=a.port, ctx=a.ctx)
    lignes, lat = [], []
    try:
        for c in cas:
            t0 = time.monotonic()
            try:
                v = d(c["texte"])
                err = None
            except Exception as e:
                v, err = {"requete": ""}, str(e)
            dt = time.monotonic() - t0
            lat.append(dt)
            req = v.get("requete", "")
            lignes.append({"id": c["id"], "requete": req, "s": round(dt, 2),
                           "erreur": err, "temp": temp()})
            print(f"  {c['id']:22s} {dt:5.1f}s  {req!r}", flush=True)
    finally:
        d.fermer()

    # Pas de score agrégé, et cette fois pour une raison de plus qu'avant : il
    # n'y a plus de bonne réponse à laquelle comparer. Ce qui se lit ici, ce
    # sont les latences et les requêtes, cas par cas — à l'œil.
    res = {
        "modele": Path(a.modele).name, "threads": a.threads,
        "premiere_passe_s": round(d.chauffe_s, 1),
        "n": len(lignes),
        "n_predict": dl.N_PREDICT,
        "requetes_vides": sum(1 for l in lignes if not l["requete"].strip()),
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
