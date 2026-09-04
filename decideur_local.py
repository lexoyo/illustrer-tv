#!/usr/bin/env python3
"""Le décideur, en local sur le Pi — rien de la conversation ne sort de la machine.

Même contrat que `ecouter.decider()`, mais servi par un `llama.cpp` local :

    Decideur(...)(texte, dernier_sujet) -> {"illustrer": bool, ...}

Trois choix portent tout le reste, et chacun vient d'une mesure faite sur ce Pi
(cf. `MESURES-DECIDEUR.md`) :

1. **Un serveur, pas un appel par bloc.** Sur un Cortex-A53 la lecture du prompt
   plafonne à 8-29 tokens/s selon le modèle. Une consigne avec ses exemples
   pèse ~600 tokens : la relire à chaque bloc coûterait 20 à 75 s, plus le
   rechargement du modèle. `llama-server` garde le cache KV du PRÉFIXE commun
   d'un appel à l'autre — donc la consigne n'est lue qu'une fois, au démarrage,
   et un bloc ne fait plus payer que ses ~80 tokens à lui. C'est un facteur 5
   à 8 sur la latence, et c'est ce qui rend l'affaire jouable.
   Corollaire : **ce qui varie d'un appel à l'autre doit être en FIN de prompt.**
   Le sujet déjà affiché est donc après les exemples, pas dans la consigne.

2. **Une grammaire GBNF, pas du JSON demandé poliment.** Un modèle de 135 M à
   500 M ne tient pas un format sur consigne. La grammaire rend le format
   *impossible à rater* — et surtout elle réduit la génération à 1 token pour un
   « non » (le cas courant) contre une trentaine pour un objet JSON complet.
   Le format n'est pas du JSON : `non`, ou `oui|<catégorie>|<requête>`. Le JSON
   du contrat est reconstruit en Python. La grammaire peut en plus être
   RECONSTRUITE À CHAQUE BLOC pour n'autoriser, dans la requête, que des mots
   présents dans la transcription (`ancrage=True`) — mesuré utile sur la requête,
   mesuré CONTRE-PRODUCTIF sur la décision, donc pas le défaut. Cf. `grammaire()`
   et `MESURES-DECIDEUR.md`.

3. **La catégorie avant la requête.** Le modèle doit nommer la classe de ce
   qu'il veut montrer, choisie dans une liste fermée, AVANT d'écrire la requête.
   C'est le critère de retenue rendu obligatoire par la grammaire plutôt que
   suggéré par la consigne.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LLAMA_SERVER = Path(os.environ.get("ILLUSTRER_LLAMA_SERVER",
                                  Path.home() / "lcpp/build/bin/llama-server"))
MODELE = Path(os.environ.get("ILLUSTRER_MODELE_LOCAL",
                             Path.home() / "bench/models/qwen25-05b-q4.gguf"))
PORT = int(os.environ.get("ILLUSTRER_PORT", "8099"))

# ------------------------------------------------------------------ la consigne
# Volontairement plus courte que `CONSIGNE` de ecouter.py : ce qu'un gros modèle
# comprend d'une phrase abstraite (« sois avare »), un petit modèle ne l'apprend
# que d'exemples. Le budget de tokens est donc mis dans les exemples.
CONSIGNE = """\
Tu lis la transcription d'une conversation dans une piece. Personne ne te parle.
Tu dis s'il y a UNE chose concrete et visuelle a montrer sur l'ecran.
Presque toujours la reponse est: non.
non -- bavardage, organisation, opinions, sentiments, blagues, argent, rendez-vous,
       phrase abimee ou tu n'es pas sur du sujet, sujet deja affiche, simple nom
       de rue ou de gare cite en passant.
oui -- un monument, un lieu remarquable, un animal, un objet, un plat, une
       personne celebre, une oeuvre, un phenomene naturel, dont on PARLE VRAIMENT.
Format: non
    ou: oui|categorie|requete d'image de 2 a 4 mots decrivant la CHOSE
"""

# Exemples — aucun n'est repris du jeu de test `cas.json` (sinon la mesure ne
# mesurerait que la mémoire du prompt). Neuf « non » pour trois « oui » : le
# déséquilibre est la leçon à apprendre.
EXEMPLES = [
    ("Attends je te rappelle, la je suis dans le metro, on se capte apres.", "rien", "non"),
    ("Il faudrait qu'on parte avant sept heures sinon on va se retrouver dans les bouchons.", "rien", "non"),
    ("Moi je pense qu'il a completement tort sur ce coup-la, mais bon.", "rien", "non"),
    ("mais du coup le... enfin tu vois le machin qu'on avait... bref laisse tomber.", "rien", "non"),
    ("Elle a l'air vraiment contente de son nouveau boulot en tout cas.", "rien", "non"),
    ("On a paye trois cents euros de plus que l'an dernier, tu te rends compte.", "rien", "non"),
    ("Ils se sont mis a rire quand il est tombe de sa chaise, c'etait terrible.", "rien", "non"),
    ("Je descends a Republique et je prends la ligne cinq apres.", "rien", "non"),
    ("Le mont Fuji, c'est vraiment aussi impressionnant qu'on le dit ?", "Mont Fuji", "non"),
    ("On a visite le Taj Mahal a l'aube, le marbre devient rose, c'est irreel.", "rien", "oui|monument|Taj Mahal aube"),
    ("Il parait que le pangolin est le mammifere le plus braconne au monde.", "rien", "oui|animal|pangolin"),
    ("Elle nous a sorti une tarte Tatin maison, avec les pommes caramelisees dessous.", "rien", "oui|plat|tarte Tatin"),
]

CATEGORIES = ["monument", "lieu", "animal", "objet", "plat", "personne", "oeuvre", "nature"]

# La grammaire. Le découpage de la réponse ne peut pas être ambigu : `mot`
# n'admet ni guillemet ni barre verticale. 4 mots au plus dans la requête —
# au-delà, Commons renvoie moins de choses, pas plus.
# Le " " initial n'est pas décoratif : les exemples s'écrivent « R: non », donc
# à l'inférence le modèle doit pouvoir produire l'espace qu'il a vu douze fois.
# Sans lui, la grammaire force « non » collé aux deux points — une forme que le
# préfixe ne montre nulle part, et " non" est de toute façon UN seul token là où
# ":"+"non" en fait deux.
_ENTETE = ('root ::= " " ("non" | ("oui|" cat "|" requete))\n'
           'cat ::= ' + " | ".join(f'"{c}"' for c in CATEGORIES) + "\n"
           "requete ::= mot (\" \" mot){0,3}\n")
_MOT_LIBRE = "mot ::= [A-Za-zÀ-ÖØ-öø-ÿ0-9'’\\-]{2,24}\n"


def grammaire(texte=None):
    """Sans `texte`, le modèle écrit la requête qu'il veut. Avec, il ne peut
    choisir QUE des mots présents dans la transcription.

    Mesuré sur `cas.json`, un modèle de cette taille recopie des morceaux de ses
    propres exemples dans la requête (« tarte Tatin » pour un couscous). Ancrer
    la requête dans les mots du bloc rend cette hallucination littéralement
    improductible — et ça marche : plus un mot venu des exemples.

    **Mais ce n'est PAS le défaut, et c'est une mesure qui le dit.** Sur les douze
    « non » du jeu, l'ancrage fait passer les faux positifs de 2 à 3 : la
    grammaire ne contraint que ce qui vient après `oui|`, elle ne peut pas rendre
    le « oui » plus coûteux, et un vocabulaire tiré du bloc rend au contraire un
    « oui » plausible plus facile à écrire. Le défaut reste donc la grammaire
    libre, qui est la configuration entièrement mesurée. Rallumer l'ancrage quand
    la qualité de la requête devient le sujet — pas avant.

    Autre prix, assumé : une faute de whisper passe telle quelle dans la
    requête, et la recherche d'image ne trouvera rien — le bon échec."""
    if texte is None:
        return _ENTETE + _MOT_LIBRE
    mots = sorted({m for m in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'’\-]{3,24}", texte)},
                  key=str.lower)
    if not mots:
        return 'root ::= " non"\n'
    litteraux = " | ".join('"' + m.replace("\\", "").replace('"', "") + '"' for m in mots)
    return _ENTETE + "mot ::= " + litteraux + "\n"


def _bloc(texte, sujet, reponse=None):
    """Un exemple, ou la question en cours. `D:` est présent partout — un format
    uniforme évite au modèle d'avoir à deviner que la ligne a disparu."""
    t = " ".join(texte.split())
    s = "T: " + t + "\nD: " + (sujet or "rien") + "\nR:"
    return s + (" " + reponse + "\n\n" if reponse else "")


PREFIXE = (CONSIGNE + "\nT = transcription, D = sujet deja a l'ecran, R = ta reponse.\n\n"
           + "".join(_bloc(t, s, r) for t, s, r in EXEMPLES))


class Decideur:
    """Un `llama-server` local, démarré ici et tué à la fermeture.

    Le serveur n'écoute que sur 127.0.0.1 : ce n'est pas une précaution de
    principe, c'est la contrainte du projet — la transcription ne doit pas
    pouvoir sortir, même par accident de configuration réseau."""

    # ctx=1024 et non 2048 : le préfixe pèse ~600 tokens, un bloc ~150, et il
    # reste 905 Mio de RAM sur cette machine à partager avec whisper. Le cache KV
    # qu'on n'alloue pas est de la RAM que whisper n'aura pas à disputer.
    def __init__(self, modele=MODELE, threads=4, port=PORT, ctx=1024,
                 binaire=LLAMA_SERVER, journal=print, demarrage_max=180,
                 ancrage=False):
        self.modele = Path(modele)
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.journal = journal
        self.ancrage = ancrage
        self.proc = None
        if not self.modele.exists():
            raise RuntimeError(f"modèle absent : {self.modele}")
        if _port_pris(port):
            # Un serveur déjà là (mesures répétées) : on s'en sert, on ne le tue pas.
            self.journal(f"llama-server déjà sur {port}, réutilisé")
        else:
            if not Path(binaire).exists():
                raise RuntimeError(f"llama-server absent : {binaire}")
            self.proc = subprocess.Popen(
                [str(binaire), "-m", str(self.modele), "-t", str(threads),
                 "-c", str(ctx), "--host", "127.0.0.1", "--port", str(port),
                 "-np", "1", "--no-warmup"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self._attendre(demarrage_max)
        # Le préfixe est lu une fois pour toutes : sans cette passe, c'est le
        # premier bloc de la soirée qui la paierait (30 à 60 s selon le modèle).
        t0 = time.monotonic()
        self._appeler(PREFIXE, n=1)
        self.chauffe_s = time.monotonic() - t0
        self.journal(f"décideur local prêt ({self.modele.name}, "
                     f"préfixe lu en {self.chauffe_s:.1f} s)")

    def _attendre(self, limite):
        t0 = time.monotonic()
        while time.monotonic() - t0 < limite:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server s'est arrêté (code {self.proc.returncode})")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(1)
        raise RuntimeError(f"llama-server n'a pas répondu en {limite} s")

    def _appeler(self, prompt, n=24, timeout=180, gram=None):
        # `n` n'est qu'un plafond : c'est la GRAMMAIRE qui arrête la génération,
        # dès que `root` est complet. Un plafond trop bas tronquerait une requête
        # de quatre mots accentués, et la tronquer silencieusement.
        corps = json.dumps({
            "prompt": prompt, "n_predict": n, "temperature": 0.0,
            "grammar": gram if gram is not None else grammaire(), "cache_prompt": True,
            "stop": ["\n", "T:"],
        }).encode()
        req = urllib.request.Request(
            self.url + "/completion", data=corps,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    # ------------------------------------------------------- le contrat public
    def __call__(self, texte, dernier_sujet, **_):
        gram = grammaire(texte if self.ancrage else None)
        d = self._appeler(PREFIXE + _bloc(texte, dernier_sujet), gram=gram)
        return lire(d.get("content", ""), dernier_sujet)

    def fermer(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()


def lire(brut, dernier_sujet=None):
    """La réponse du modèle → le dict du contrat.

    La grammaire garantit la forme, mais pas la pertinence : le garde-fou qui
    reste utile ici est le REFUS du sujet déjà affiché. Un modèle de cette taille
    y retombe, et c'est le faux positif le plus visible sur la télé — la même
    image qui se recharge."""
    s = brut.strip()
    if not s.startswith("oui|"):
        return {"illustrer": False, "pourquoi": "rien de visuel (local)"}
    parts = s.split("|")
    if len(parts) < 3 or not parts[2].strip():
        return {"illustrer": False, "pourquoi": f"réponse inutilisable : {s[:40]!r}"}
    cat, requete = parts[1].strip(), " ".join(parts[2].split())
    if dernier_sujet and _proche(requete, dernier_sujet):
        return {"illustrer": False,
                "pourquoi": f"déjà à l'écran ({dernier_sujet})"}
    return {"illustrer": True, "requete": requete,
            "titre": " ".join(requete.split()[:3]),
            "pourquoi": f"{cat} (local)"}


def _proche(a, b):
    def n(x):
        return set(re.findall(r"\w{4,}", x.lower()))
    ma, mb = n(a), n(b)
    return bool(ma & mb)


def _port_pris(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
