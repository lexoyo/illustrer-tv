#!/usr/bin/env python3
"""Le témoin d'écoute : un point dans un coin de la télé pendant que le micro tourne.

**Pourquoi ça existe.** La boucle est strictement séquentielle : `enregistrer`
45 s, *puis* whisper, *puis* le décideur. **Rien n'enregistre pendant la
transcription.** Le système entend donc 45 s sur ~122 en régime nominal (37 %) —
et sur les cycles réels du 04/09 au soir, whisper est monté à 175 et 220 s, ce
qui fait tomber la part écoutée à 20 %.

C'est le compromis assumé du projet, mais il était **invisible** : Alex a parlé
trois fois d'éléphants devant la télé sans réaction, parce que ses phrases sont
tombées dans les fenêtres sourdes, et il a perdu dix minutes à parler dans le
vide sans pouvoir le savoir.

Le témoin ne dit donc qu'une chose : **c'est maintenant qu'on peut parler.** Pas
de niveau d'entrée, pas de compteur, pas de texte. C'est un objet de salon posé
sur une photo, pas un instrument — s'il informe, il dérange.

    ./temoin.py --duree 6       # l'allumer 6 s, puis l'effacer
    ./temoin.py --verifier      # preuve que l'image dessous ressort intacte

**Coût mesuré sur le Pi 3B**, sur un bloc de 45 s (le cadre réel) : **3,9 ms de
CPU par seconde**, soit 0,4 % d'un cœur, sur une machine déjà bridée à 1,03 GHz
par sa température. Reproductible par `--verifier`.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb as fbmod  # noqa: E402

# --------------------------------------------------------------- réglages
# Tout ce qui définit l'apparence du témoin est ici, et rien qu'ici.
#
# Un disque plutôt qu'une barre ou un texte : à trois mètres d'une télé, une
# forme sans détail est lue d'un coup d'œil et ne demande pas de la regarder.
COIN = "bas-droite"      # bas-droite | bas-gauche | haut-droite | haut-gauche
RAYON = 15               # px — 30 px de diamètre ≈ 1,4 cm sur une télé de 1 m,
                         # soit ~0,3° à trois mètres : vu sans être lu.
HALO = 7                 # px de pénombre autour du disque. C'est elle qui rend
                         # le témoin visible aussi bien sur un ciel blanc que
                         # sur une roche noire — sans elle il disparaît une fois
                         # sur deux selon la photo affichée dessous.
HALO_OPACITE = 0.6       # 1 = noir franc ; au-delà de ~0,7 ça fait un autocollant
MARGE = 46               # px entre le bord de la pénombre et le bord de l'écran
COULEUR = (255, 96, 40)  # ambre-rouge : la couleur d'un voyant d'enregistrement,
                         # et elle ne se confond avec presque aucune photo
RESPIRATION_S = 3.2      # période du souffle. Un point fixe se lit comme un
                         # défaut d'écran ou un logo de chaîne ; qui respire se
                         # lit comme vivant. 3,2 s ≈ un rythme de repos.
CREUX = 0.45             # luminosité au creux du souffle (1 = pleine)
NIVEAUX = 24             # images distinctes dans un souffle, donc 7,5 par
                         # seconde ici. Elles sont calculées une fois à
                         # l'allumage et rejouées en boucle : composer une image
                         # coûte 2,39 ms sur ce Pi, l'écrire 0,22 ms (mesuré le
                         # 04/09). Recalculer à chaque fois revenait à 21 ms de
                         # CPU par seconde ; le film ramène à ~3, sur une
                         # machine déjà bridée à 1,03 GHz par sa température.


class Temoin:
    """Le point allumé, en gestionnaire de contexte : `with Temoin(ecran): …`.

    **Pourquoi un thread.** `enregistrer()` est un `subprocess.run` d'arecord de
    45 s : il bloque, et il n'a aucune raison d'apprendre à dessiner. Un thread
    permet de laisser la capture exactement telle qu'elle est et d'entourer
    n'importe quel appel bloquant du même `with`. L'autre voie — passer arecord
    en Popen et animer entre deux `poll()` — mélangerait la capture et
    l'affichage dans la même fonction pour économiser un thread dont le risque
    est nul ici : entre `allumer()` et `eteindre()`, le thread principal ne
    touche jamais au framebuffer, il attend arecord. Il n'y a donc jamais deux
    écrivains.

    **L'image dessous n'est pas redessinée.** On relit le rectangle avant de
    dessiner, on le remet à l'extinction : 4,2 kio pour 46x46 px en RGB565, au
    lieu des 369 ms d'un réaffichage complet — qui supposerait en plus d'avoir
    gardé la photo. Le fond n'est relu qu'une fois : rien ne peut le modifier
    pendant l'enregistrement, puisque la boucle n'affiche une image qu'après."""

    def __init__(self, fbuf: fbmod.Framebuffer):
        import numpy as np

        self.fb = fbuf
        r = RAYON + HALO
        self.w = self.h = 2 * r + 1          # impair : le disque a un centre exact
        x_max = fbuf.info.xres - self.w - MARGE
        y_max = fbuf.info.yres - self.h - MARGE
        # `max(0, …)` pour qu'un petit écran ne fasse pas planter la boucle
        # d'écoute pour une histoire de décoration.
        self.x = max(0, MARGE if "gauche" in COIN else x_max)
        self.y = max(0, MARGE if "haut" in COIN else y_max)

        # Couvertures précalculées une fois pour toutes : ce sont elles qui
        # rendent les bords lisses (sans elles, un disque de 30 px montre ses
        # escaliers) et qui font que chaque image ne coûte plus qu'un mélange.
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        d = np.hypot(xx - r, yy - r)
        self.a_halo = (np.clip((r - d) / HALO, 0, 1) * HALO_OPACITE)[..., None]
        self.a_disque = np.clip(RAYON + 0.5 - d, 0, 1)[..., None]

        self._fond = None
        self._stop = threading.Event()
        self._fil: threading.Thread | None = None
        self.images = 0                      # pour mesurer le coût
        self.cpu = 0.0

    # -- rendu ------------------------------------------------------------
    def _composer(self, eclat: float) -> bytes:
        """Le fond sauvegardé + la pénombre + le disque, en octets natifs."""
        import numpy as np

        out = self.fb.unpack_rgb(self._fond, (self.w, self.h)).astype(np.float32)
        out *= 1.0 - self.a_halo                      # pénombre = vers le noir
        coul = np.asarray(COULEUR, dtype=np.float32) * eclat
        out += (coul - out) * self.a_disque
        return self.fb.pack_rgb(out.clip(0, 255).astype(np.uint8))

    def _film(self) -> list[bytes]:
        """Un souffle entier, prêt à écrire, calculé une fois à l'allumage.

        Le fond ne bouge pas de toute la prise — la boucle n'affiche une image
        qu'après la transcription, donc jamais pendant que le témoin est
        allumé. L'animation se réduit alors à N images fixes rejouées en boucle,
        et la seconde d'écoute ne coûte plus que N écritures de 4,1 kio."""
        # Un cosinus, pas une rampe : il s'attarde sur le creux et sur la crête
        # et traverse vite entre les deux, ce qui se lit comme une respiration
        # et non comme un gradateur qui monte et descend.
        return [self._composer(
            CREUX + (1 - CREUX) * (0.5 + 0.5 * math.cos(2 * math.pi * i / NIVEAUX)))
            for i in range(NIVEAUX)]

    def _souffler(self, film: list[bytes]) -> None:
        pas = RESPIRATION_S / NIVEAUX
        t0 = time.monotonic()
        i = 0
        while True:
            t = time.process_time()
            try:
                self.fb.write_rect(self.x, self.y, self.w, self.h, film[i % NIVEAUX])
            except Exception:
                # Un témoin qui casse ne doit jamais emporter la soirée
                # d'écoute : on s'arrête d'animer, `eteindre()` remettra le fond.
                return
            self.cpu += time.process_time() - t
            self.images += 1
            i += 1
            # On vise l'horloge plutôt que d'enchaîner des attentes fixes : sinon
            # le souffle dérive de la durée du dessin à chaque tour.
            if self._stop.wait(max(0.0, t0 + i * pas - time.monotonic())):
                return

    # -- cycle de vie -----------------------------------------------------
    def allumer(self) -> None:
        if self._fil is not None:
            return
        t = time.process_time()
        self._fond = self.fb.read_rect(self.x, self.y, self.w, self.h)
        film = self._film()
        self.cpu += time.process_time() - t
        self._stop.clear()
        self._fil = threading.Thread(target=self._souffler, args=(film,),
                                     name="temoin", daemon=True)
        self._fil.start()

    def eteindre(self) -> None:
        if self._fil is None:
            return
        self._stop.set()
        self._fil.join(timeout=2.0)
        self._fil = None
        if self._fond is not None:
            self.fb.write_rect(self.x, self.y, self.w, self.h, self._fond)
            self._fond = None

    def __enter__(self) -> "Temoin":
        self.allumer()
        return self

    def __exit__(self, *exc) -> None:
        self.eteindre()


# --------------------------------------------------------------- essai CLI
def main() -> int:
    import hashlib

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duree", type=float, default=6.0, help="secondes allumé")
    ap.add_argument("--verifier", action="store_true",
                    help="empreinte des pixels du témoin avant / pendant / après : "
                         "prouve qu'il s'efface sans abîmer l'image qu'il couvre")
    a = ap.parse_args()

    print(fbmod.unblank())
    with fbmod.Framebuffer() as f:
        t = Temoin(f)
        print(f"témoin  {t.w}x{t.h} px en ({t.x},{t.y}) — coin {COIN}")

        # L'empreinte porte sur LE RECTANGLE du témoin, pas sur l'écran entier :
        # le curseur de la console clignote tout seul en haut à gauche (8x2 px)
        # dès que `console.sh` n'a pas tourné depuis le dernier démarrage, et il
        # ferait échouer une comparaison plein écran sans rien dire du témoin.
        zone = lambda: hashlib.sha256(
            f.read_rect(t.x, t.y, t.w, t.h)).hexdigest()[:16]

        avant = zone()
        t.allumer()
        time.sleep(min(2.0, a.duree))
        pendant = zone()
        time.sleep(max(0.0, a.duree - 2.0))
        t.eteindre()
        apres = zone()
        # Le coût par seconde d'enregistrement est le seul chiffre qui compte
        # ici : cette machine est déjà bridée à 1,03 GHz par sa température.
        print(f"coût    {t.images} images, {t.cpu * 1e3:.0f} ms CPU au total, "
              f"soit {t.cpu / max(a.duree, 1e-9) * 1e3:.1f} ms par seconde")
        if not a.verifier:
            return 0
        print(f"zone    avant {avant} · pendant {pendant} · après {apres}")
        if pendant == avant:
            print("VERDICT ÉCHEC — le témoin ne s'est pas affiché")
            return 1
        if apres != avant:
            print("VERDICT ÉCHEC — l'image sous le témoin n'a pas été rendue")
            return 1
        print("VERDICT le témoin s'affiche, s'efface, et rend les pixels d'origine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
