#!/usr/bin/env python3
"""Écoute la pièce et illustre sur la télé ce dont on parle.

Un cycle : 45 s de micro → whisper → un LLM qui décide s'il y a quelque chose à
montrer → recherche d'image → framebuffer.

**Le décideur est local par défaut** (`--decideur local`, `decideur_local.py`) :
ce qu'on lui donne à lire, c'est la transcription d'une conversation privée, et
elle ne doit pas quitter la machine. La voie distante reste là, derrière
`--decideur distant`, uniquement pour comparer les deux sur les mêmes blocs —
l'utiliser envoie la transcription à un tiers, et le journal le dit.

**Le temps réel n'est pas un objectif, et c'est la décision qui tient tout le
reste.** On transcrit un bloc pendant que le suivant n'est pas capturé, donc on
rate environ la moitié de ce qui se dit. Assumé : le sujet d'une conversation
survit à un trou de 40 s, et c'est ce qui permet de tenir sur un Pi 3B sans
jamais courir après l'horloge. Un ASR en flux (sherpa) entendrait tout, au prix
d'un texte sans ponctuation et d'une machinerie qu'on n'a pas besoin de payer.
"""
import argparse
import contextlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fb as fbmod
import temoin as temoinmod

BLOC_S = 45
# ⚠ `tiny` est DISQUALIFIÉ, mesuré le 04/09/2026 sur un vrai enregistrement du
# micro : il rend « les élèves fonds d'Asie » là où `base` rend « les éléphants
# d'Asie ». **Les noms concrets ne survivent pas** — or ce sont exactement eux que
# le décideur cherche. `base` q5 est le modèle du projet ; il n'est pas encore
# installé sur le Pi, et ce chemin reste donc celui d'une chaîne qu'on sait
# fausse. À corriger avant toute mesure de qualité de bout en bout.
MODELE_STT = Path(__file__).parent / "models/ggml-base-q5_1.bin"
MODELE_LLM = "google/gemini-2.5-flash-lite"   # le défaut mesuré de microturn
MODELE_LOCAL = Path.home() / "bench/models/qwen25-05b-q4.gguf"
FENETRE = 3                                    # blocs de contexte gardés (~2 min)
OUBLI = 12                                     # cycles avant qu'un sujet affiché
                                               # cesse de bloquer les suivants
UA = "illustrer-tv/0.1 (prototype; alex@lexoyo.me)"
CHRONO = time.monotonic


def journal(msg):
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def temperature():
    """La grandeur à surveiller : ce Pi bride à 80 °C, et whisper le chauffe."""
    try:
        out = subprocess.run(["/usr/bin/vcgencmd", "measure_temp"],
                             capture_output=True, text=True, timeout=5).stdout
        return float(re.search(r"([\d.]+)", out).group(1))
    except Exception:
        return float("nan")


# ---------------------------------------------------------------- capture
def carte_micro(motif=None):
    """Trouve la carte ALSA par son NOM.

    L'index n'est pas stable : ce micro est passé de card 1 à card 2 entre deux
    redémarrages. Un script figé sur `hw:2,0` casse au reboot suivant."""
    motif = motif or os.environ.get("ILLUSTRER_MIC", "0x46d")
    out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    for ligne in out.splitlines():
        m = re.match(r"card (\d+):", ligne)
        if m and motif in ligne:
            return int(m.group(1))
    raise RuntimeError(f"aucune carte de capture ne contient {motif!r} :\n{out}")


def enregistrer(dest, secondes, carte):
    """Le micro de la webcam est figé en 16 kHz mono — le format natif de
    whisper. Aucune conversion, donc pas besoin de ffmpeg dans la boucle."""
    subprocess.run(
        ["arecord", "-q", "-D", f"plughw:{carte},0", "-f", "S16_LE",
         "-r", "16000", "-c", "1", "-d", str(secondes), "-t", "wav", str(dest)],
        check=True)


# ------------------------------------------------------------ transcription
class Transcripteur:
    """whisper.cpp, modèle résident.

    Le modèle charge en 0,33 s sur le Pi : le garder en vie ne change pas la
    face du monde, mais le recharger à chaque cycle serait payer pour rien."""

    def __init__(self, modele=MODELE_STT, threads=2):
        from pywhispercpp.model import Model
        # PAS de greedy ici, et c'est mesuré : `-bo 1 -bs 1` fait tomber le RTF
        # de 1,96 à ~1,2 sur cette machine, mais « architecture » devient
        # « séptéculture ». Tout ce projet repose sur les noms concrets, donc le
        # beam search par défaut n'est pas négociable.
        #
        # Une version antérieure passait `greedy_best_of` et `temperature_inc` :
        # ces attributs n'existent pas dans pywhispercpp 1.5.1, et l'erreur est
        # une AttributeError — que le repli ne rattrapait pas.
        self.m = Model(str(modele), n_threads=threads, language="fr",
                       translate=False, print_progress=False,
                       print_realtime=False)

    def __call__(self, wav):
        return " ".join(s.text.strip() for s in self.m.transcribe(str(wav))).strip()


# Whisper ÉTIQUETTE le bruit au lieu de se taire : « [Musique] », « *musique* »,
# « [bruits de la porte] », « (rires) ». Ce ne sont pas des mots prononcés dans
# la pièce — c'est sa façon de dire qu'il n'entend pas de parole.
#
# Le seuil `len(texte) < 15` ne les arrête pas : « [Musique] [Musique] » fait
# dix-neuf caractères. Le 04/09, le bloc « de la même chose. [Musique] » a donc
# atteint le décideur, qui a produit la requête « musique de la musique » et
# affiché la Cité de la Musique — la seule image de la soirée, et elle est
# fausse. Sur les 136 cycles de cette soirée, 95 ne contenaient QUE des
# étiquettes ; 32 d'entre eux ont payé un appel au décideur (5 à 19 s à 81 °C)
# pour rien.
#
# Le filtre audio ne remplace pas ce nettoyage : sur le même enregistrement de
# pièce vide, whisper rend « *musique* » brut, « [Musique] [Bruit de feu] »
# après passe-haut à 120 Hz, et « [Musique] » après passe-haut ET gain. C'est
# du texte à jeter, pas du son à corriger.
ETIQUETTE = re.compile(r"[\[(*][^\])*]{0,60}(?:[\])*]|$)")


def parole_utile(texte):
    """Ce qui reste du bloc une fois les étiquettes de bruit retirées.

    On ne rabote la ponctuation qu'aux DEUX BOUTS : un premier jet nettoyait
    aussi l'intérieur et « Montre-moi » y perdait son trait d'union."""
    t = re.sub(r"\s+", " ", ETIQUETTE.sub(" ", texte)).strip(" .…·-–—,;:!?")
    return t if re.search(r"\w", t) else ""


# ---------------------------------------------------------------- décision
CONSIGNE = """Tu écoutes une conversation dans une pièce. On te donne sa \
transcription automatique : elle est imparfaite, parfois tronquée, et personne \
ne s'adresse à toi.

Ton seul travail : dire si un sujet CONCRET et VISUEL vient d'apparaître, qui \
gagnerait à être montré sur l'écran de la pièce.

Tu réponds par un objet JSON, et rien d'autre :
  {"illustrer": false, "pourquoi": "en quelques mots"}
  {"illustrer": true, "requete": "2 à 5 mots, comme une requête d'image", \
"titre": "le sujet en 3 mots", "pourquoi": "en quelques mots"}

Les règles, dans l'ordre :
- SOIS AVARE. Par défaut, c'est non. Du bavardage, de l'organisation, des \
opinions, des sentiments, des blagues : rien à illustrer.
- Ce qui s'illustre : un lieu, un monument, un animal, un objet, un plat, une \
personne célèbre, une œuvre, un phénomène naturel.
- Si la transcription est trop abîmée pour que tu sois SÛR du sujet, c'est non. \
Une image sans rapport est pire que pas d'image.
- Ne répète pas le sujet déjà affiché. S'il n'y a rien de neuf, c'est non.
- La requête décrit la CHOSE, pas la conversation : « tour Eiffel de nuit », \
pas « ils parlent de Paris »."""


def decider(texte, dernier_sujet, modele=MODELE_LLM, timeout=20):
    import requests
    cle = cle_openrouter()
    contexte = CONSIGNE
    if dernier_sujet:
        contexte += f"\n\nSujet DÉJÀ affiché à l'écran : « {dernier_sujet} »."
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
        json={"model": modele, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": contexte},
                           {"role": "user", "content": texte}]},
        timeout=timeout)
    r.raise_for_status()
    brut = r.json()["choices"][0]["message"]["content"]
    # Le modèle encadre parfois son JSON de ```json — on prend le premier objet
    # plutôt que d'exiger une sortie propre.
    m = re.search(r"\{.*\}", brut, re.S)
    if not m:
        raise ValueError(f"réponse non JSON : {brut[:120]!r}")
    return json.loads(m.group(0))


def cle_openrouter():
    """La clé de la machine d'abord ; le .env de microturn en secours (lecture
    seule — ce dépôt appartient à une autre session)."""
    p = Path.home() / ".config/openrouter.key"
    if p.exists():
        return p.read_text().strip()
    env = Path.home() / "microturn/.env"
    if env.exists():
        m = re.search(r"OPENROUTER_API_KEY\s*=\s*(\S+)", env.read_text())
        if m:
            return m.group(1).strip("'\"")
    raise RuntimeError("pas de clé OpenRouter (~/.config/openrouter.key)")


# ------------------------------------------------------------------ image
def chercher_image(requete, timeout=15):
    """Wikimedia Commons d'abord, Openverse en secours. Les deux sans clé.

    Commons impose un User-Agent identifiable : sans lui, les requêtes sont
    refusées, et le refus ressemble à « aucun résultat »."""
    import requests
    api = "https://commons.wikimedia.org/w/api.php"
    # 20 résultats et non 8 : le filtre paysage + résolution en écarte
    # beaucoup, et il vaut mieux chercher large que se rabattre sur un portrait.
    p = {"action": "query", "format": "json", "generator": "search",
         "gsrsearch": f"{requete} filetype:bitmap", "gsrnamespace": "6",
         "gsrlimit": "20", "prop": "imageinfo",
         "iiprop": "url|mime|size", "iiurlwidth": "1920"}
    try:
        d = requests.get(api, params=p, headers={"User-Agent": UA},
                         timeout=timeout).json()
        candidats = []
        for page in (d.get("query", {}).get("pages") or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            if utilisable(info):
                candidats.append((rang(info), info, page.get("title", "?")))
        if candidats:
            candidats.sort(key=lambda c: c[0])
            _, info, titre = candidats[0]
            return info["thumburl"], f"commons:{titre}"
    except Exception as e:
        journal(f"   commons a échoué : {e}")
    try:
        d = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": requete, "page_size": 5},
                         headers={"User-Agent": UA}, timeout=timeout).json()
        for r in d.get("results") or []:
            if r.get("url"):
                return r["url"], f"openverse:{r.get('title', '?')}"
    except Exception as e:
        journal(f"   openverse a échoué : {e}")
    return None, None


# L'écran est une télé : 1920×1080, donc du 16/9 posé à l'horizontale.
LARGEUR_MIN = 1280      # en dessous, l'agrandissement se voit sur 1920 px
RATIO_PREFERE = 1.2     # 1,0 = carré ; en dessous on est en portrait
RATIO_PLANCHER = 0.55   # plus étroit que ça, `cover` ne garde qu'un bandeau


def utilisable(info):
    """Peut-on afficher cette image du tout ? Format, taille, et pas un rouleau."""
    if info.get("mime") not in ("image/jpeg", "image/png"):
        return False
    if not info.get("thumburl"):
        return False
    l, h = info.get("width") or 0, info.get("height") or 1
    return l >= LARGEUR_MIN and l / h >= RATIO_PLANCHER


def rang(info):
    """Ordre de préférence : le paysage d'abord, un portrait plutôt que rien.

    La première version ÉCARTAIT les portraits. Alex a vu le contraire sur sa
    télé — `cover` sur un portrait garde la bande centrale, ce qui donne un gros
    plan quand le sujet est centré, et c'était mieux que l'image de référence.
    Et le filtre coûtait cher : il ne laissait passer que cinq résultats sur
    vingt. On classe donc au lieu d'exclure. Ne restent écartés que les rouleaux
    (ratio sous 0,55), où il ne resterait qu'un bandeau vertical.

    À ratio équivalent, la plus grande image gagne : elle survit mieux au
    rognage."""
    l, h = info.get("width") or 0, info.get("height") or 1
    return (0 if l / h >= RATIO_PREFERE else 1, -l)


def telecharger(url, timeout=20):
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.content


def afficher(octets, ecran):
    from PIL import Image
    img = Image.open(io.BytesIO(octets))
    img.load()
    ecran.show_image(img)


# ------------------------------------------------------------------- boucle
def cycle(n, ecran, stt, etat, args, trace):
    t = {}
    wav = trace / f"{n:04d}.wav" if trace else Path("/tmp/illustrer-bloc.wav")
    if args.wav:
        # Un bloc pris dans un fichier au lieu du micro. C'est ce qui rend un
        # cycle complet REJOUABLE : sans ça, mesurer la chaîne demande quelqu'un
        # qui parle dans la pièce, et deux mesures ne portent jamais sur le même
        # son. Le reste du cycle est identique, micro compris dans le chrono.
        wav = Path(args.wav)
        t["micro"] = 0.0
    else:
        # Le témoin est allumé exactement le temps de la prise, jamais plus :
        # c'est sa seule utilité, faire voir les 45 s où parler sert à quelque
        # chose au milieu des 80 à 220 s où la machine est sourde (temoin.py).
        d = CHRONO()
        with etat["temoin"]:
            enregistrer(wav, args.bloc, etat["carte"])
        t["micro"] = CHRONO() - d
    d = CHRONO(); texte = stt(wav);                           t["stt"] = CHRONO() - d
    journal(f"[{n}] {t['stt']:.1f}s stt · {temperature():.1f}°C · {texte[:70]!r}")
    texte = parole_utile(texte)
    if len(texte) < 15:
        journal("    rien d'audible, on passe")           # bloc quasi muet
        return

    # Un sujet affiché finit par se périmer. Sans ça, une image posée par erreur
    # bloque toutes les suivantes : le 04/09, « musique de la » a fait répondre
    # « déjà à l'écran » neuf fois pendant cinq heures.
    etat["age"] = etat.get("age", 0) + 1
    if etat["sujet"] and etat["age"] > OUBLI:
        journal(f"    on oublie « {etat['sujet']} » ({OUBLI} cycles)")
        etat["sujet"] = None

    etat["fenetre"] = (etat["fenetre"] + [texte])[-FENETRE:]
    d = CHRONO(); verdict = etat["decide"]("\n".join(etat["fenetre"]),
                                          etat["sujet"]); t["llm"] = CHRONO() - d
    if trace:
        (trace / f"{n:04d}.json").write_text(json.dumps(
            {"texte": texte, "verdict": verdict, "temps": t},
            ensure_ascii=False, indent=1))
    if not verdict.get("illustrer"):
        journal(f"    non ({t['llm']:.1f}s) — {verdict.get('pourquoi', '')}")
        return
    requete = verdict.get("requete", "").strip()
    journal(f"    OUI ({t['llm']:.1f}s) « {requete} » — {verdict.get('pourquoi', '')}")
    url, source = chercher_image(requete)
    if not url:
        journal("    aucune image trouvée")
        return
    d = CHRONO(); octets = telecharger(url); t["dl"] = CHRONO() - d
    if ecran:
        d = CHRONO(); afficher(octets, ecran); t["ecran"] = CHRONO() - d
    if trace:
        (trace / f"{n:04d}.jpg").write_bytes(octets)
    etat["sujet"] = verdict.get("titre") or requete
    etat["age"] = 0
    journal(f"    affiché {source} ({len(octets)//1024} Ko, "
            f"dl {t.get('dl', 0):.1f}s, écran {t.get('ecran', 0):.1f}s)")


def arret_propre(signum, frame):
    """systemd arrête le service par SIGTERM, que Python honore en tuant le
    process **sans dérouler les `finally`**. Le témoin resterait alors peint sur
    la télé — et pire, le cycle suivant relirait ce point comme s'il faisait
    partie de l'image, puis le remettrait à chaque extinction : il deviendrait
    permanent. On transforme donc le signal en KeyboardInterrupt, que la boucle
    sait déjà traiter."""
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, arret_propre)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bloc", type=int, default=BLOC_S, help="durée d'un bloc (s)")
    ap.add_argument("--une-fois", action="store_true", help="un seul cycle")
    ap.add_argument("--sans-ecran", action="store_true",
                    help="ne rien afficher (mise au point du texte seule)")
    ap.add_argument("--decideur", choices=("local", "distant"), default="local",
                    help="local = llama.cpp sur cette machine, rien ne sort ; "
                         "distant = OpenRouter (la transcription QUITTE la machine)")
    ap.add_argument("--modele", default=MODELE_LLM,
                    help="le modèle distant (--decideur distant)")
    ap.add_argument("--modele-local", default=str(MODELE_LOCAL),
                    help="le .gguf du décideur local")
    ap.add_argument("--threads", type=int, default=2,
                    help="whisper : au-delà de 2 le Pi bride plus qu'il ne gagne")
    ap.add_argument("--threads-llm", type=int, default=4,
                    help="le décideur local, lui, est seul à tourner : 4 cœurs")
    ap.add_argument("--wav", metavar="FICHIER",
                    help="lire ce wav 16 kHz mono au lieu du micro (mesure rejouable)")
    ap.add_argument("--trace", metavar="DOSSIER",
                    help="garder wav, texte, verdict et image de chaque cycle")
    a = ap.parse_args()

    trace = None
    if a.trace:
        trace = Path(a.trace) / time.strftime("%Y%m%d-%H%M%S")
        trace.mkdir(parents=True)
        journal(f"trace dans {trace}")

    etat = {"fenetre": [], "sujet": None,
            "carte": None if a.wav else carte_micro()}
    # Le décideur est construit ici, pas appelé par son nom dans la boucle : les
    # deux voies doivent rester interchangeables pour être comparables sur les
    # mêmes blocs, et c'est le seul endroit où le choix se lit.
    if a.decideur == "local":
        import decideur_local
        dec = decideur_local.Decideur(modele=a.modele_local,
                                      threads=a.threads_llm, journal=journal)
        etat["decide"] = dec
        quoi = f"local {Path(a.modele_local).name} (rien ne sort de la machine)"
    else:
        dec = None
        etat["decide"] = lambda t, s: decider(t, s, modele=a.modele)
        quoi = f"DISTANT {a.modele} — la transcription quitte la machine"
    source = f"wav {a.wav}" if a.wav else f"micro sur card {etat['carte']}"
    journal(f"{source} · blocs de {a.bloc}s · décideur {quoi}")
    journal(f"chargement de whisper ({MODELE_STT.name})…")
    stt = Transcripteur(threads=a.threads)

    ecran = None
    # `nullcontext` quand il n'y a pas d'écran (--sans-ecran) : le `with` de la
    # boucle reste écrit une seule fois, sans « if » dans le chemin chaud.
    etat["temoin"] = contextlib.nullcontext()
    if not a.sans_ecran:
        journal(fbmod.unblank())
        ecran = fbmod.Framebuffer()
        journal(f"écran {ecran.info}")
        if not a.wav:                      # en rejeu il n'y a pas de micro à signaler
            etat["temoin"] = temoinmod.Temoin(ecran)
    try:
        n = 0
        while True:
            n += 1
            try:
                cycle(n, ecran, stt, etat, a, trace)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Un cycle qui casse ne doit pas tuer la soirée : le réseau
                # tombe, Commons renvoie du HTML, une image est corrompue.
                journal(f"    ⚠ cycle {n} abandonné : {type(e).__name__}: {e}")
            if a.une_fois:
                break
    except KeyboardInterrupt:
        journal("arrêt")
    finally:
        if ecran:
            ecran.close()
        if dec is not None:
            dec.fermer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
