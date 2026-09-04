# illustrer-tv — afficher une image sur la télé du Pi

Première brique de sortie du prototype « écouter les discussions et les
illustrer sur la télé ». Objectif de cette brique, et rien de plus :
**un chemin fiable et mesuré entre un fichier image et les pixels de la télé
HDMI**, sur un Raspberry Pi sans serveur graphique.

Cible : `raspi2` — Pi 3B, Raspberry Pi OS Lite trixie arm64, **pas de X, pas de
Wayland**. On écrit donc directement dans le framebuffer du noyau, `/dev/fb0`.

## Ce que ça fait

```bash
./show.py photo.jpg                    # plein écran, ratio conservé, fond noir
./show.py https://exemple.org/img.jpg  # une URL marche aussi
./show.py --backend ffmpeg photo.jpg   # sans dépendance Python
./show.py --clear                      # écran noir
./testcard.py                          # mire de validation (voir plus bas)
./grab.py capture.png                  # relit la télé et en fait un PNG
```

## La voie retenue, et pourquoi

**Pillow + numpy dans un venv dédié, écriture directe dans `/dev/fb0`.**
`ffmpeg` reste disponible en second backend (`--backend ffmpeg`).

Les deux ont été implémentés et mesurés côte à côte sur le Pi. Trois raisons de
garder Pillow par défaut :

1. **2,3× plus rapide en régime réel** (369 ms contre 846 ms par image, process
   déjà chaud). ffmpeg paie à chaque image le lancement d'un binaire statique de
   51 Mo et l'initialisation complète de libav.
2. **C'est la suite du projet.** Illustrer une conversation voudra composer du
   texte par-dessus l'image (légende, mot-clé, horodatage). Avec Pillow c'est
   `ImageDraw.text()` dans le même process. Avec ffmpeg, ce serait impossible
   ici : **le filtre `drawtext` est absent** du binaire disponible sur la
   machine, malgré son `--enable-libfreetype`. Vérifié :
   `ffmpeg -filters | grep -i text` ne renvoie que `showinfo` et `subtitles`.
3. Le venv coûte **17 s à créer et zéro compilation** (Pillow 12.3.0 arrive en
   wheel aarch64 depuis piwheels), et il ne touche pas au python système.

ffmpeg garde un usage : c'est le repli si le venv saute, il n'a **aucune**
dépendance Python, et il lira des formats que PIL ne connaît pas (HEIC, AVIF,
première image d'une vidéo). Sur un lancement à froid il est même un peu plus
rapide bout en bout (1,49 s contre 1,62 s), parce qu'il évite les 444 ms
d'import de PIL+numpy — mais ce régime-là n'est pas celui du projet.

## Comment ça marche

`fb.py` est la brique réutilisable. Elle **n'invente aucun paramètre** : tout
vient du driver, par `ioctl(FBIOGET_VSCREENINFO / FBIOGET_FSCREENINFO)` —
résolution, bits par pixel, *stride*, et la position de chaque canal de couleur.
Sur `raspi2` ça donne :

```
vc4drmfb 1920x1080 16bpp stride=3840 (utile=3840) R@11/5 G@5/6 B@0/5
```

soit du **RGB565 little-endian**, 2 octets par pixel. `show.py` en déduit tout
seul le `pix_fmt` à demander à ffmpeg (`rgb565le`) et les décalages de bits pour
la conversion numpy — un autre Pi en 32 bpp ou en BGR marcherait sans changer
une ligne.

Le framebuffer est **mmappé** plutôt qu'écrit avec `write()` : une trame de
4,15 Mio part à l'écran en ~5 ms.

## Le piège du stride

`stride` (alias `line_length`) est le nombre d'octets d'une ligne **en mémoire**.
Il peut dépasser `largeur × octets_par_pixel` si le driver aligne les lignes.
Écrire la trame d'un seul bloc dans ce cas décale chaque ligne un peu plus que
la précédente : l'image part en escalier vers la gauche.

Ici `stride = 3840 = 1920 × 2` exactement, donc **pas de padding** et le cas ne
se présente pas. `Framebuffer.write_frame()` gère quand même le cas padded
(recopie ligne par ligne au bon offset), pour que le code survive à un autre
écran ou à un autre mode.

## Vérification — sans voir l'écran

Trois niveaux, du plus faible au plus fort :

1. **Relecture de pixels témoins.** Après écriture, `show.py` relit le
   framebuffer et compare 64 pixels répartis dans l'image (256 pour la mire).
   Une écriture peut « réussir » sans que le driver l'ait acceptée.
2. **`grab.py`** relit *tout* le framebuffer, reconvertit le RGB565 en RGB888 et
   en fait un PNG. On peut donc **regarder ce qu'il y a sur la télé** depuis une
   session SSH. C'est ce qui a servi à valider cette brique : les captures
   montrent la mire et les photos exactement telles qu'attendues (couleurs dans
   le bon ordre, diagonales droites, letterbox centré).
3. **La mire, pour l'œil humain.** `testcard.py` produit une image dont un seul
   coup d'œil suffit à disqualifier un affichage cassé :
   - équerres colorées **collées aux 4 coins** + cadre 1 px → cadrage et stride ;
   - **diagonales d'angle à angle** → tout cisaillement casse le X central ;
   - pastilles **étiquetées** ROUGE / VERT / BLEU → ordre des canaux (un
     framebuffer BGR ferait lire « ROUGE » sous du bleu) ;
   - dégradé de gris → les paliers visibles sont ceux du RGB565 (32 niveaux),
     c'est normal et pas un défaut d'affichage ;
   - `microturn` + date/heure → prouve qu'on regarde bien la dernière écriture
     et pas une image restée à l'écran depuis un essai précédent.

## Mesures (Pi 3B, `raspi2`, 2026-09-04)

Image : JPEG 1280×960 = **1,23 Mpx**, 247 kio (Wikimedia Commons,
*Bachalpsee reflection*). Écran 1920×1080. 3 passes par régime.

| régime | pillow | ffmpeg |
|---|---|---|
| **A. un process par image** (wall-clock, imports compris) | **1 624 ms** | 1 492 ms |
| **B. process déjà chaud**, par image | **369 ms** | 846 ms |
| — dont décodage + mise à l'échelle | 364 ms | 842 ms |
| — dont écriture dans `/dev/fb0` | **5 ms** | 4 ms |
| coût unique du process (démarrage + imports) | 109 + 444 ms | 108 + 0 ms |

Découpage fin du chemin Pillow, à chaud (profilé séparément) :
`ouverture+draft 2 ms · décodage JPEG 40 ms · redimensionnement 124 ms ·
composition 23 ms · conversion RGB565 129 ms · écriture fb 4 ms`.

Deux enseignements pour la suite :
- **la conversion RGB565 en numpy (≈130 ms) coûte autant que le
  redimensionnement.** Si 370 ms devient trop, c'est là qu'il faut creuser
  (table de correspondance précalculée, ou rester en RGB565 de bout en bout).
- `--quality good` (LANCZOS au lieu de BILINEAR) fait passer le
  redimensionnement de 124 à 274 ms. À réserver aux images fixes soignées.

**Température** (mur thermique à 80 °C) : 54,8 °C au repos, 58,0 °C avant le
banc, **61,8 °C après** un banc complet (12 affichages + téléchargements).
Aucun risque de throttling pour cet usage — afficher une image est un travail
court et peu intense.

## Pièges rencontrés

1. **`/sys/class/graphics/fb0/blank` valait 4** (= écran éteint) sur une machine
   fraîche. Les écritures dans `/dev/fb0` réussissaient et l'écran restait noir.
   C'est le piège n°1 et il ne donne aucun message d'erreur. `fb.py` lit
   maintenant cette valeur et essaie de la remettre à 0 à chaque affichage ; si
   `/sys` n'est pas inscriptible il affiche la commande sudo à lancer.
2. **`drawtext` absent du ffmpeg disponible** malgré `--enable-libfreetype`.
   Toute idée de composer du texte avec ffmpeg tombe. (Seul `subtitles`/libass
   est là.)
3. **Wikimedia refuse désormais les largeurs de vignette arbitraires**
   (`HTTP 400: Use thumbnail sizes listed on…`). Il faut une taille de la liste
   autorisée : 320, 640, 800, 1024, 1280, 1920, 2560.
4. `bc` n'est pas installé sur le Pi — les moyennes de `bench.sh` sont en `awk`.
5. `/usr/sbin` n'est pas dans le `PATH` en SSH non interactif : `vcgencmd` et
   `setterm` sont appelés en chemin absolu.
6. Le premier appel à ffmpeg après un démarrage prend **4,1 s** au lieu de
   0,85 s : c'est le binaire statique de 51 Mo qui monte depuis la carte SD.
   Toute mesure sur ffmpeg doit jeter la première passe.
7. **`raspi2` est en `Europe/London`**, pas en heure de Paris. L'horloge affichée
   par la mire est donc en retard d'une heure sur celle du poste de travail.
   Rien n'a été changé (ça toucherait la conf système), mais c'est à savoir avant
   de conclure qu'une image est vieille d'une heure.

## Installation sur le Pi

```bash
scp fb.py show.py testcard.py grab.py bench.sh install.sh console.sh pi:~/illustrer-tv/
ssh pi 'cd ~/illustrer-tv && ./install.sh'      # venv + Pillow, ~20 s, pas de sudo
ssh pi 'cd ~/illustrer-tv && sudo ./console.sh' # rallumer l'écran, cacher le curseur
ssh pi 'cd ~/illustrer-tv && ./.venv/bin/python testcard.py'
```

`install.sh` ne touche **pas** au python système : Debian 13 le refuserait de
toute façon (PEP 668). Le venv est en `--system-site-packages` pour réutiliser
le numpy 2.2.4 déjà installé plutôt que d'en recompiler un.

### sudo — ce qui est utilisé, et comment le défaire

`console.sh` est le **seul** script qui demande root, pour trois réglages de la
console texte. Aucun n'est persistant : **un reboot les annule tous les trois**,
et `sudo ./console.sh --undo` les remet à leurs valeurs par défaut.

| commande | pourquoi | défaire |
|---|---|---|
| `echo 0 > /sys/class/graphics/fb0/blank` | l'écran était en veille (valeur 4) | `echo 4 > …/blank` |
| `printf '\033[?25l' > /dev/tty1` | le curseur clignotant repeint par-dessus | `printf '\033[?25h' > /dev/tty1` |
| `setterm --blank 0 --powerdown 0 > /dev/tty1` | éviter que la console rééteigne l'écran | `setterm --blank 10 --powerdown 10` |

Rien d'autre n'a été fait en root. **Aucun paquet système n'a été installé**
(les 82 mises à jour en attente sur la machine n'ont pas été touchées).

## Fichiers

| fichier | rôle |
|---|---|
| `fb.py` | **la brique réutilisable** : géométrie du framebuffer par ioctl, mmap, gestion du stride, conversion RGB↔format natif, letterbox, relecture de contrôle |
| `show.py` | CLI d'affichage (chemin ou URL), deux backends, mesures en `--json` |
| `testcard.py` | mire de validation à l'œil |
| `grab.py` | relit la télé → PNG ou SHA-256 (voir l'écran depuis SSH) |
| `bench.sh` | le banc de mesure ci-dessus, reproductible |
| `install.sh` | venv + Pillow sur le Pi |
| `console.sh` | les trois réglages console qui demandent sudo (+ `--undo`) |

## Pour la suite

`fb.py` expose ce qu'il faut pour la brique suivante : `Framebuffer.show_image()`
prend n'importe quelle image PIL, donc composer une légende par-dessus une
illustration ne demande qu'un `ImageDraw` avant l'appel. Le point à surveiller
est le **coût fixe du process** (550 ms d'imports) : l'afficheur devra être un
process long qui reçoit les images, pas un `show.py` relancé à chaque fois.
