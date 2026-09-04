#!/usr/bin/env python3
"""Le décideur, en local sur le Pi — rien de la conversation ne sort de la machine.

    Decideur(...)(texte) -> {"illustrer": True, "requete": "<ce que le modèle a écrit>"}

**Il n'a plus de consigne, plus d'exemples, plus de catégories et plus de
grammaire.** C'est une décision d'Alex du 04/09/2026 au soir, et elle défait
exprès tout ce que `MESURES-DECIDEUR.md` avait construit. Ce qui l'a décidée est
une soirée : six heures d'écoute, 136 cycles, **une seule image affichée**, et
les trois « oui » du modèle étaient dégénérés — « musique de la musique »,
« video de la vidéo », « tarte Tatin aube etApplication ». Sur « j'aime le
vélo… au sacré cœur », il a rendu `oui|objet|vélo et vélo partageur` : il rate
« Sacré-Cœur », le seul mot cherchable de la phrase, et invente « partageur »,
absent de la transcription. Ce résultat-là coûtait ~600 tokens de préfixe et 5 à
19 s par bloc.

Ce qui reste tient en deux lignes : **une ligne d'instruction, puis la
transcription. Ce que le modèle écrit ensuite est la requête d'image,
verbatim.** Le modèle ne décide plus s'il faut illustrer — c'est `ecouter.py`
qui déclenche, sur du son et des mots (cf. son § « niveau ») — il dit seulement
quoi montrer. `illustrer` vaut donc TOUJOURS vrai dès qu'on l'a appelé, et le
dict du contrat ne change pas pour autant : les deux voies, locale et distante,
doivent rester interchangeables sur les mêmes blocs.

La ligne d'instruction a été remise **après** un premier essai entièrement nu, et
c'est cet essai qui l'a justifiée : sans elle, un modèle de base *continue* le
texte au lieu d'en extraire quoi que ce soit (« J'aime le vélo… au sacré cœur »
→ « . C'est un bon moyen »), et les quatorze essais donnaient zéro pertinence.
**Une ligne, et rien d'autre** : pas d'exemples, pas de catégories, pas de
grammaire, pas de nombre de mots imposé. Le pari reste le même — on regarde ce
que le modèle fait, on ne lui apprend pas à le faire.

Ce que ça change, et ce que ça ne change pas — mesuré le 04/09/2026 sur ce Pi,
14 blocs réels relevés dans le journal du service :

- **la latence tombe** : 1 à 6 s par bloc (2,1 s de médiane à n_predict=6)
  contre 10,5 s de médiane au banc et 5 à 19 s en service. Le prompt ne pèse
  plus 600 tokens mais 12 à 28, donc la lecture du prompt — le poste
  principal sur un Cortex-A53, c'était le résultat n° 1 de `MESURES-DECIDEUR.md`
  — a simplement disparu. Ce qui reste est de la génération pure.
- **sans la ligne d'instruction, le modèle ne produisait PAS des requêtes : il
  continuait la conversation.** « J'aime le vélo… au sacré cœur partout » →
  « . C'est un bon moyen » ; les éléphants d'Asie → « C'est une propriété de
  la ». Un modèle de base complète du texte, il ne le résume pas. 10 de ces 14
  suites trouvaient quand même une image sur Commons — un mot de la suite tombe
  sur un titre — donc l'écran bougeait, avec **zéro pertinence**. C'est ce
  résultat qui a fait remettre la ligne.
- **avec la ligne**, voir la mesure en tête de `ecouter.py` § décision et le
  `JOURNAL.md` : c'est la seule chose qui a changé entre les deux relevés, sur
  les mêmes blocs et le même `n_predict`.

Ce qui SURVIT de `MESURES-DECIDEUR.md`, et qu'il ne faut pas défaire :
`llama-server` plutôt qu'un process par bloc (le rechargement du modèle coûtait
toujours autant), le serveur qui n'écoute que sur `127.0.0.1`, et le contexte à
1024 tokens.
"""
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

LLAMA_SERVER = Path(os.environ.get("ILLUSTRER_LLAMA_SERVER",
                                   Path.home() / "lcpp/build/bin/llama-server"))
MODELE = Path(os.environ.get("ILLUSTRER_MODELE_LOCAL",
                             Path.home() / "bench/models/qwen25-05b-q4.gguf"))
PORT = int(os.environ.get("ILLUSTRER_PORT", "8099"))

# **Une ligne, et strictement rien d'autre.** Elle est écrite sans accents : le
# tokenizer d'un 0,5 B les rend plus chers, et la consigne supprimée le faisait
# déjà pour cette raison. Elle est en français parce que la requête doit sortir
# en français — la recherche d'images se fait sur Commons en français.
#
# Ce qui n'y est PAS, et qui ne doit pas y revenir : les douze exemples, les huit
# catégories, la grammaire GBNF, un nombre de mots imposé, la règle « déjà à
# l'écran ». Chacun a été mesuré et supprimé le 04/09/2026 ; les remettre parce
# que « ça marcherait mieux » referait la machinerie qu'une soirée de six heures
# et une seule image ont condamnée.
INSTRUCTION = "Ecris les mots-cles d'une recherche d'image sur ce dont on parle."

# La SEULE borne qui reste, et ce n'est pas une consigne déguisée : le modèle
# écrit ce qu'il veut, on limite seulement le temps qu'il a le droit d'y passer.
# Sans borne, un 0,5 B qui reçoit du texte brut le CONTINUE, et il le continue
# jusqu'au bout du contexte — 1024 tokens à ~3 t/s font six minutes pour un bloc
# de 45 s.
#
# Mesuré le 04/09/2026, 14 blocs réels, Pi entre 72 et 86 °C :
#
# | n_predict | latence médiane | images trouvées /14 |
# |---|---|---|
# | 4  | 1,2 s | 11 |
# | **6** | **2,1 s** | **10** |
# | 10 | 3,6 s | 7 |
#
# Les deux colonnes vont dans le même sens et disent la même chose : plus la
# suite est longue, moins elle ressemble à une requête. Une phrase française
# entière ne rencontre aucun mot-clé de Commons ; trois mots, si. 4 et 6 sont à
# égalité à un cas près, ce qui ne conclut rien sur 14 cas (règle du dépôt) ;
# 6 est pris parce que 4 tronque au milieu d'un mot une fois sur trois
# (« aveur de la », « ix, si tu »).
N_PREDICT = 6

# Le modèle continue la conversation : un saut de ligne est le seul endroit où
# il change de locuteur de lui-même. Mesuré, il ne s'y arrête presque jamais —
# 13 blocs sur 14 sont coupés par N_PREDICT. C'est une ceinture, pas la borne.
ARRETS = ["\n", "\n\n"]


class Decideur:
    """Un `llama-server` local, démarré ici et tué à la fermeture.

    Le serveur n'écoute que sur 127.0.0.1 : ce n'est pas une précaution de
    principe, c'est la contrainte du projet — la transcription ne doit pas
    pouvoir sortir, même par accident de configuration réseau."""

    # ctx=1024 : il n'y a plus de préfixe de 600 tokens à loger, mais un bloc de
    # 45 s de whisper peut en faire 150 à 400 quand il répète, et il reste
    # 905 Mio de RAM à partager avec whisper. Le cache KV qu'on n'alloue pas est
    # de la RAM que whisper n'aura pas à disputer.
    def __init__(self, modele=MODELE, threads=4, port=PORT, ctx=1024,
                 binaire=LLAMA_SERVER, journal=print, demarrage_max=180):
        self.modele = Path(modele)
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.journal = journal
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
        # Une passe à vide, pour que le premier bloc de la soirée ne paie pas
        # l'allocation du cache KV. Elle ne « chauffe » plus rien d'autre : il
        # n'y a plus de préfixe commun à mettre en cache.
        t0 = time.monotonic()
        self._appeler("bonjour")
        self.chauffe_s = time.monotonic() - t0
        self.journal(f"décideur local prêt ({self.modele.name}, sans consigne, "
                     f"première passe en {self.chauffe_s:.1f} s)")

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

    def _appeler(self, prompt, n=N_PREDICT, timeout=180):
        # `cache_prompt` est resté à True, et c'est une non-décision assumée :
        # le préfixe commun d'un bloc à l'autre est désormais la ligne
        # d'INSTRUCTION, soit ~16 tokens — il n'a quasiment rien à économiser.
        # Mesuré en A/B/A sur 14 blocs quand il n'y avait aucun préfixe du tout
        # (True, False, True) : 11,8 s / 11,8 s / 2,3 s de médiane. L'écart entre
        # les deux passes True est cinq fois celui entre True et False — c'est la
        # température du Pi qu'on mesure (86 °C, bridé), pas le cache. Il ne
        # coûte rien, il ne rapporte rien, on ne touche pas.
        corps = json.dumps({
            "prompt": prompt, "n_predict": n, "temperature": 0.0,
            "cache_prompt": True, "stop": ARRETS,
        }).encode()
        req = urllib.request.Request(
            self.url + "/completion", data=corps,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    # ------------------------------------------------------- le contrat public
    def __call__(self, texte, *_, **__):
        """La transcription entre, la suite du modèle sort — verbatim.

        Pas de nettoyage, pas de validation, pas de reformatage, et surtout pas
        de traduction : la requête part en français dans la recherche d'images.
        Une sortie vide n'est pas un cas particulier — elle ne trouvera rien, et
        « rien trouvé » veut déjà dire « on ne touche pas à l'écran »."""
        d = self._appeler(INSTRUCTION + "\n" + texte)
        return {"illustrer": True, "requete": d.get("content", ""),
                "pourquoi": "sans consigne (local)"}

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


def _port_pris(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
