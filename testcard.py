#!/usr/bin/env python3
"""Génère et affiche une mire de validation sur la télé.

But : qu'un humain qui regarde l'écran puisse dire en une seconde si
l'affichage est correct, sans rien mesurer.

    ./testcard.py              # génère et affiche
    ./testcard.py --out m.png  # génère seulement, dans un fichier

Ce que la mire prouve :
  - repères d'angle collés aux 4 bords + cadre 1 px -> décalage de *stride*
    (l'image « en escalier ») ou zone utile mal cadrée, visible immédiatement ;
  - diagonales d'angle à angle -> tout cisaillement casse le X central ;
  - pastilles ROUGE / VERT / BLEU **étiquetées** -> ordre des canaux (un
    framebuffer BGR au lieu de RGB fait lire « ROUGE » sous du bleu) ;
  - dégradé de gris -> les paliers du RGB565 (32 niveaux) sont normaux ici ;
  - `microturn` + date/heure -> confirme qu'on regarde bien cette écriture-là
    et pas une image restée à l'écran depuis un essai précédent.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb as fbmod  # noqa: E402

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
BG = (10, 30, 90)          # bleu franc
INK = (255, 255, 255)
CORNERS = [
    ("HAUT-GAUCHE", (255, 80, 80)),
    ("HAUT-DROITE", (80, 255, 120)),
    ("BAS-GAUCHE", (255, 220, 60)),
    ("BAS-DROITE", (120, 180, 255)),
]


def font(name: str, size: int):
    for cand in (os.path.join(FONT_DIR, name), name):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def temp() -> str:
    for exe in ("/usr/bin/vcgencmd", "vcgencmd"):
        try:
            out = subprocess.run([exe, "measure_temp"], capture_output=True,
                                 text=True, timeout=5)
            if out.returncode == 0:
                return out.stdout.strip().replace("temp=", "")
        except (OSError, subprocess.SubprocessError):
            pass
    return "?"


def build(size: tuple[int, int], info_line: str = "") -> Image.Image:
    W, H = size
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Diagonales : un cisaillement de stride les casse net.
    d.line([(0, 0), (W - 1, H - 1)], fill=(60, 90, 160), width=2)
    d.line([(W - 1, 0), (0, H - 1)], fill=(60, 90, 160), width=2)

    # Cadre 1 px collé aux bords + cadre intérieur.
    d.rectangle([0, 0, W - 1, H - 1], outline=INK, width=1)
    d.rectangle([8, 8, W - 9, H - 9], outline=(120, 160, 220), width=1)

    # Repères d'angle : équerres de 220x220 px exactement dans les coins.
    L, T = 220, 26
    f_corner = font("DejaVuSans-Bold.ttf", 26)
    for idx, (label, col) in enumerate(CORNERS):
        right, bottom = idx % 2 == 1, idx >= 2
        x0 = W - L if right else 0
        y0 = H - L if bottom else 0
        # branche horizontale et branche verticale de l'équerre
        d.rectangle([x0, H - T if bottom else y0, x0 + L, (H - T if bottom else y0) + T], fill=col)
        d.rectangle([W - T if right else x0, y0, (W - T if right else x0) + T, y0 + L], fill=col)
        tx = x0 + L + 12 if not right else x0 - 12
        ty = y0 + T + 12 if not bottom else H - T - 12
        d.text((tx, ty), label, font=f_corner, fill=col,
               anchor=("l" if not right else "r") + ("a" if not bottom else "d"))

    # Bloc central.
    cx, cy = W // 2, H // 2
    f_big = font("DejaVuSans-Bold.ttf", 150)
    f_mid = font("DejaVuSansMono.ttf", 46)
    f_small = font("DejaVuSansMono.ttf", 26)
    now = datetime.now()
    d.text((cx, cy - 130), "microturn", font=f_big, fill=INK, anchor="mm")
    d.text((cx, cy - 20), now.strftime("%Y-%m-%d  %H:%M:%S"), font=f_mid,
           fill=(255, 230, 120), anchor="mm")
    d.text((cx, cy + 28), f"{socket.gethostname()}  —  {W}x{H}  —  CPU {temp()}",
           font=f_small, fill=(200, 220, 255), anchor="mm")
    if info_line:
        d.text((cx, cy + 64), info_line, font=f_small, fill=(160, 190, 240), anchor="mm")

    # Pastilles de couleur ÉTIQUETÉES : contrôle de l'ordre des canaux.
    swatches = [("ROUGE", (255, 0, 0)), ("VERT", (0, 255, 0)), ("BLEU", (0, 0, 255)),
                ("JAUNE", (255, 255, 0)), ("CYAN", (0, 255, 255)),
                ("MAGENTA", (255, 0, 255)), ("BLANC", (255, 255, 255))]
    sw, sh, gap = 150, 90, 16
    total = len(swatches) * sw + (len(swatches) - 1) * gap
    sx, sy = (W - total) // 2, cy + 120
    f_sw = font("DejaVuSans-Bold.ttf", 24)
    for label, col in swatches:
        d.rectangle([sx, sy, sx + sw, sy + sh], fill=col, outline=INK, width=1)
        d.text((sx + sw // 2, sy + sh + 8), label, font=f_sw, fill=INK, anchor="ma")
        sx += sw + gap

    # Dégradé de gris : les paliers visibles = les 32 niveaux du RGB565.
    gy0, gh = sy + sh + 60, 40
    gx0, gx1 = (W - total) // 2, (W - total) // 2 + total
    for x in range(gx0, gx1):
        v = round(255 * (x - gx0) / max(1, gx1 - gx0 - 1))
        d.line([(x, gy0), (x, gy0 + gh)], fill=(v, v, v))
    d.rectangle([gx0, gy0, gx1 - 1, gy0 + gh], outline=INK, width=1)
    d.text((gx0, gy0 + gh + 10), "degrade 0 -> 255 (les paliers sont normaux : RGB565)",
           font=f_small, fill=(200, 220, 255), anchor="la")

    # Règle de 100 px le long du bord haut : décalage horizontal repérable.
    for x in range(0, W, 100):
        h = 24 if x % 500 == 0 else 12
        d.line([(x, 9), (x, 9 + h)], fill=INK, width=2 if x % 500 == 0 else 1)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="écrire un PNG au lieu d'afficher")
    ap.add_argument("--size", default=None, help="WxH (défaut : celle du framebuffer)")
    ap.add_argument("--device", default="/dev/fb0")
    args = ap.parse_args()

    if args.out:
        W, H = (int(v) for v in (args.size or "1920x1080").split("x"))
        build((W, H), "genere hors framebuffer").save(args.out)
        print(f"écrit : {args.out} ({W}x{H})")
        return 0

    with fbmod.Framebuffer(args.device) as fbuf:
        print(f"fb    : {fbuf.info}")
        print(f"blank : {fbmod.unblank()}")
        img = build(fbuf.size, f"{fbuf.info.fix_id} stride={fbuf.info.line_length}")
        import numpy as np
        frame = fbuf.pack_array(np.asarray(img))
        fbuf.write_frame(frame)
        checked, same = fbuf.probe(frame, n=256)
        print(f"mire affichée — relecture {same}/{checked} pixels témoins identiques")
        return 0 if same == checked else 1


if __name__ == "__main__":
    sys.exit(main())
