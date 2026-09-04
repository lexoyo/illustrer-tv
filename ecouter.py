#!/usr/bin/env python3
"""Écoute la pièce et illustre sur la télé ce dont on parle.

Un cycle : 45 s de micro → niveau sonore → whisper → un LLM qui dit QUOI
montrer → recherche d'image → framebuffer.

**Ce qui déclenche un changement d'image, ce sont deux conditions mécaniques et
rien d'autre : du son au-dessus du fond de la pièce, ET des mots.** Le modèle ne
décide plus s'il faut illustrer — décision d'Alex du 04/09/2026, prise après une
soirée de six heures qui n'a produit qu'une seule image. Il n'a plus ni consigne
ni grammaire : on lui donne la transcription du bloc, ce qu'il écrit ensuite
devient la requête d'image verbatim. Le raisonnement complet et les mesures sont
dans `decideur_local.py`.

**Il n'y a plus non plus de règle « déjà à l'écran ».** C'est elle qui avait figé
la télé cinq heures d'affilée. Quand la requête ramène des images déjà montrées,
on en prend une AUTRE ; quand elle ne ramène rien, on laisse l'écran tranquille.

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
import collections
import contextlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
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
# Trois blocs de contexte, ~2 min de pièce. Alex y tient, et la raison est
# mesurée : sur cette machine whisper met 79 à 416 s pour 45 s d'audio, donc les
# fenêtres sourdes sont longues et un bloc sur deux revient mal transcrit
# (« un éduciel », « ça te veuille »). Garder les deux blocs précédents fait
# **survivre le sujet à un bloc raté**. Le prix est connu : ce qu'on donne au
# modèle n'est plus « ce qui vient d'être dit » mais « ce qui s'est dit dans les
# dernières minutes », et l'image peut donc parler d'un sujet déjà quitté.
FENETRE = 3
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


# ----------------------------------------------------------------- niveau
# « Du son au-dessus du fond » : la première des deux conditions qui font
# changer l'image (l'autre est `parole_utile`, plus bas). Mesurée sur le WAV
# AVANT whisper — c'est ce qui permet de ne pas payer 70 à 220 s de
# transcription pour une pièce vide, et le 04/09 la pièce était vide 95 cycles
# sur 136.
#
# 🔴 **Un seuil absolu ne tient pas**, et c'est mesuré deux fois dans la même
# pièce. Le 04/09 au matin le plancher était à -41 dBFS RMS ; le soir, trois
# blocs de 45 s pris à vide donnent **-34,6 dBFS**. Six décibels d'écart d'un
# jour à l'autre : une constante calée sur l'un classe tout de travers sur
# l'autre.
#
# 🔴 **Et le RMS du bloc entier ne sépare rien du tout.** Les WAV de voix du
# corpus (Alex à deux mètres) contre les trois blocs de pièce vide :
#
# | bloc | RMS global | p10 | p90 | p90 - p10 |
# |---|---|---|---|---|
# | pièce vide ×3 | -34,6 / -34,6 / -34,3 | -35,2 | -34,1 | **1,1** |
# | base-01 (voix) | -35,7 | -41,2 | -31,5 | 9,7 |
# | essai (voix) | -34,1 | -44,4 | -28,5 | 15,9 |
# | ref-loin2 (voix) | -32,1 | -44,6 | -27,3 | 17,3 |
# | ref-loin (voix) | -30,2 | -43,6 | -26,2 | 17,3 |
#
# Le RMS d'un bloc de voix (-30 à -36) recouvre ENTIÈREMENT celui d'un bloc vide
# (-34,6) : une voix n'occupe qu'une fraction des 45 s, et la moyenne la noie.
# Ce qui sépare, c'est l'écart entre les moments forts et le fond — 1,1 dB quand
# la pièce souffle toute seule, 9,7 à 17,3 dB dès qu'une voix passe.
#
# D'où la mesure retenue : `fort` = p90 des trames de 200 ms du bloc, comparé à
# une **référence de fond** qui est le plus haut de deux planchers :
#
# - le **plancher glissant** de la pièce, 25e centile des `fond` (p10) des vingt
#   derniers blocs. Le 25e centile et pas la médiane : un quart de blocs calmes
#   suffit à le tenir au niveau de la pièce, donc une longue conversation ne
#   referme pas la porte derrière elle ;
# - le **fond du bloc lui-même**, parce que le silence de la pièce ne peut pas
#   être plus bas que ce que ce bloc-ci a entendu pendant ses creux.
#
# Prendre le plus haut des deux n'est pas une ceinture de plus, c'est ce qui fait
# tenir la mesure : sans lui, un plancher hérité d'une soirée plus calme laisse
# passer une pièce vide. Vérifié sur les sept blocs disponibles (trois de pièce
# vide pris ce soir, quatre de voix pris la nuit du 03 au 04, plancher 9 dB plus
# bas) dans trois ordres de présentation — dont un qui mélange exprès les deux
# soirées, ce qui simule un saut de plancher de 9 dB en 45 s :
#
# | ordre | classement |
# |---|---|
# | pièce puis voix | 7/7 |
# | entrelacé | 7/7 |
# | voix puis pièce (pire cas) | 7/7 |
#
# Avec le seul plancher glissant, les deux derniers ordres se trompaient sur les
# trois blocs de pièce vide. La marge restante est mince et il faut le dire :
# 3,9 dB de garde sur le bloc vide le plus fort, 4,7 dB sur la voix la plus
# faible, et **sept blocs ne mesurent presque rien** (un cas vaut 14 points).
TRAME_MS = 200          # assez long pour lisser une consonne, assez court pour
                        # qu'une syllabe ne soit pas noyée dans 45 s de souffle
MARGE_DB = 5.0          # entre 1,1 (pièce vide) et 9,7 (la voix la plus faible)
MEMOIRE_FOND = 20       # ~40 min de pièce, le temps qu'un fond dérive


def niveau(wav):
    """(fort, fond) du bloc en dBFS : p90 et p10 des trames de 200 ms."""
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    k = int(sr * TRAME_MS / 1000)
    if len(x) < k:
        return float("nan"), float("nan")
    trames = x[:len(x) // k * k].reshape(-1, k)
    db = 20 * np.log10(np.sqrt((trames * trames).mean(axis=1)) + 1e-9)
    return float(np.percentile(db, 90)), float(np.percentile(db, 10))


def plancher(fonds):
    """Le niveau de la pièce quand personne ne parle, tel qu'on l'a vu récemment."""
    import numpy as np
    if len(fonds) < 4:
        return min(fonds)          # trop tôt pour un centile : on prend au plus bas,
    return float(np.percentile(list(fonds), 25))   # donc au plus permissif


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
# **Une ligne d'instruction, puis la transcription. Rien d'autre.** La voie
# distante suit la voie locale à la lettre — même ligne, même ordre, même sortie
# verbatim (`decideur_local.py`, qui porte le raisonnement et les mesures). Les
# deux voies doivent rester interchangeables sur les mêmes blocs, sinon les
# comparer ne veut plus rien dire : c'est une règle du projet depuis le premier
# jour.
#
# `response_format: json_object` est parti avec l'ancienne consigne : sans schéma
# à remplir, exiger du JSON n'aurait plus rien à décrire.
def decider(texte, *_, modele=MODELE_LLM, timeout=20, jetons=32):
    # `decideur_local` est importé ici et pas en tête : sur le Pi la voie locale
    # démarre un llama-server, et ce module ne doit pas être chargé pour rien
    # quand on tourne en distant. Seule la ligne d'INSTRUCTION est partagée —
    # c'est exactement ce qui garde les deux voies comparables.
    import decideur_local
    """Même contrat que `decideur_local.Decideur` : la transcription entre, la
    suite du modèle sort verbatim, et `illustrer` est toujours vrai.

    `jetons` vaut 32 et non 6 comme en local : ici la latence est celle du
    réseau, pas d'une génération à 3 t/s sur un Cortex-A53, et la borne n'est
    plus là que pour empêcher un modèle bavard de raconter la soirée."""
    import requests
    cle = cle_openrouter()
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
        json={"model": modele, "temperature": 0, "max_tokens": jetons,
              "messages": [{"role": "user",
                            "content": decideur_local.INSTRUCTION + "\n" + texte}]},
        timeout=timeout)
    r.raise_for_status()
    return {"illustrer": True,
            "requete": r.json()["choices"][0]["message"]["content"],
            "pourquoi": "sans consigne (distant)"}


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
# **Un moteur = une fonction `requete -> [(url, identifiant), …]`, du meilleur au
# pire.** Deux raisons pour cette forme, et aucune n'est de l'élégance :
#
# 1. **Changer de moteur ne doit toucher qu'ici.** Commons et Openverse sont des
#    fonds documentaires indexés par mots-clés : ils rendent « rien » dès que la
#    requête est bancale. Mesuré le 04/09 sur 14 blocs réels avec le décideur nu,
#    4 requêtes sur 14 ne ramènent rien du tout, et l'écran reste alors figé — le
#    défaut même qu'on est en train de corriger. Un moteur généraliste (Pexels,
#    Unsplash, DuckDuckGo images) rend toujours quelque chose. Le jour où Alex
#    bascule, il écrit une fonction, il l'ajoute à `MOTEURS`, il change `CHAINE` :
#    la boucle ne bouge pas d'une ligne. **Aucun moteur généraliste n'est écrit
#    ici — la place est préparée, rien de plus.**
# 2. **Une LISTE de candidats, pas un seul.** « Même sujet, autre image » demande
#    de pouvoir descendre dans le classement quand le premier a déjà été montré.
#    Un moteur qui ne rendrait que son meilleur résultat rendrait la mémoire des
#    images vues inutilisable.


def moteur_commons(requete, timeout):
    """Wikimedia Commons. Sans clé, mais il impose un User-Agent identifiable :
    sans lui les requêtes sont refusées, et le refus ressemble à « aucun
    résultat »."""
    import requests
    # 20 résultats et non 8 : le classement paysage + résolution en repousse
    # beaucoup, et il vaut mieux chercher large que se rabattre sur un portrait.
    p = {"action": "query", "format": "json", "generator": "search",
         "gsrsearch": f"{requete} filetype:bitmap", "gsrnamespace": "6",
         "gsrlimit": "20", "prop": "imageinfo",
         "iiprop": "url|mime|size", "iiurlwidth": "1920"}
    d = requests.get("https://commons.wikimedia.org/w/api.php", params=p,
                     headers={"User-Agent": UA}, timeout=timeout).json()
    candidats = []
    for page in (d.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if utilisable(info):
            candidats.append((rang(info), info["thumburl"],
                              f"commons:{page.get('title', '?')}"))
    candidats.sort(key=lambda c: c[0])
    return [(url, ident) for _, url, ident in candidats]


def moteur_openverse(requete, timeout):
    """Le secours quand Commons ne trouve rien. Il est lent : le 04/09 il a
    dépassé les 15 s de délai, d'où l'ordre — Commons d'abord, toujours."""
    import requests
    d = requests.get("https://api.openverse.org/v1/images/",
                     params={"q": requete, "page_size": 5},
                     headers={"User-Agent": UA}, timeout=timeout).json()
    return [(r["url"], f"openverse:{r.get('id') or r.get('title', '?')}")
            for r in (d.get("results") or []) if r.get("url")]


MOTEURS = {"commons": moteur_commons, "openverse": moteur_openverse}
CHAINE = ("commons", "openverse")


def chercher_image(requete, deja=(), chaine=CHAINE, timeout=15):
    """La première image que cette pièce n'a pas déjà vue, ou (None, None).

    L'identité d'une image est celle du FICHIER, jamais celle de la requête :
    deux blocs qui produisent la même requête doivent pouvoir montrer deux
    photos différentes — c'est exactement ce qu'Alex a demandé le 04/09 après
    cinq heures d'écran figé. Rien trouvé de neuf = on ne touche pas à l'écran ;
    l'image en place vaut mieux que pas d'image."""
    for nom in chaine:
        try:
            for url, ident in MOTEURS[nom](requete, timeout):
                if ident not in deja:
                    return url, ident
        except Exception as e:
            journal(f"   {nom} a échoué : {e}")
    return None, None


# Combien d'images on se souvient d'avoir montrées. 300, soit à peu près deux
# soirées : au-delà on oublie les plus anciennes, et la plus ancienne est de
# toute façon celle qu'on peut remontrer sans que ça se voie.
VUES_MAX = 300


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
    # Le déclencheur, en deux conditions ET, décidées par Alex le 04/09 : du son
    # au-dessus du fond de la pièce, et des mots. Rien d'autre — plus de « le
    # modèle a-t-il trouvé un sujet », plus de « ce sujet est-il déjà à
    # l'écran ». C'est cette dernière règle qui avait figé la télé cinq heures
    # sur « musique de la », et le mécanisme d'oubli qui la rattrapait part avec
    # elle : on ne rattrape pas une règle qu'on supprime.
    fort, fond = niveau(wav)
    if fort == fort:                     # NaN = WAV illisible : on ne bloque pas
        etat["fonds"].append(fond)       # sur une mesure qu'on n'a pas
        seuil = max(plancher(etat["fonds"]), fond) + MARGE_DB
        if fort < seuil:
            journal(f"[{n}] {fort:.1f} dBFS sous le seuil {seuil:.1f} "
                    f"(fond du bloc {fond:.1f}, pièce {plancher(etat['fonds']):.1f}) "
                    f"— la pièce se tait, pas de whisper")
            return
    d = CHRONO(); texte = stt(wav);                           t["stt"] = CHRONO() - d
    journal(f"[{n}] {t['stt']:.1f}s stt · {temperature():.1f}°C · "
            f"fort {fort:.1f} dBFS · {texte[:70]!r}")
    texte = parole_utile(texte)
    if not texte:
        # Du son, mais whisper n'y a entendu que du bruit qu'il ÉTIQUETTE
        # (« [Musique] », « [bruits de la porte] »). Ce ne sont pas des mots
        # prononcés dans la pièce, et la deuxième condition n'est pas remplie.
        journal("    du son, mais aucune parole — on passe")
        return

    etat["fenetre"] = (etat["fenetre"] + [texte])[-FENETRE:]
    d = CHRONO()
    verdict = etat["decide"]("\n".join(etat["fenetre"]))
    t["llm"] = CHRONO() - d
    # Le modèle ne décide plus rien : `illustrer` est toujours vrai, et ce qu'il
    # a écrit part tel quel dans la recherche. Ce qui est jeté, c'est la
    # RECHERCHE quand elle ne trouve rien, plus jamais le bloc.
    requete = verdict.get("requete", "")
    journal(f"    ({t['llm']:.1f}s) requête {requete!r}")
    if trace:
        (trace / f"{n:04d}.json").write_text(json.dumps(
            {"texte": texte, "verdict": verdict, "temps": t,
             "fort": fort, "fond": fond},
            ensure_ascii=False, indent=1))
    url, source = chercher_image(requete, etat["vues"])
    if not url:
        journal("    aucune image nouvelle — l'écran ne bouge pas")
        return
    d = CHRONO(); octets = telecharger(url); t["dl"] = CHRONO() - d
    if ecran:
        d = CHRONO(); afficher(octets, ecran); t["ecran"] = CHRONO() - d
    if trace:
        (trace / f"{n:04d}.jpg").write_bytes(octets)
    etat["vues"][source] = None
    while len(etat["vues"]) > VUES_MAX:
        etat["vues"].popitem(last=False)
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

    # `fonds` : les p10 des derniers blocs, d'où sort le plancher glissant.
    # `vues` : les fichiers image déjà montrés, dans l'ordre — c'est ce qui
    # permet de rendre une AUTRE image quand la requête ne change pas.
    etat = {"carte": None if a.wav else carte_micro(),
            "fenetre": [],
            "fonds": collections.deque(maxlen=MEMOIRE_FOND),
            "vues": collections.OrderedDict()}
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
        etat["decide"] = lambda t: decider(t, modele=a.modele)
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
