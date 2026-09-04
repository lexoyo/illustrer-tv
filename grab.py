#!/usr/bin/env python3
"""Relit le framebuffer et l'enregistre en PNG — le seul moyen de *voir* la télé
depuis une session SSH.

    ./grab.py capture.png            # pleine résolution
    ./grab.py --scale 3 capture.png  # divisé par 3 (fichier léger)
    ./grab.py --hash                 # juste l'empreinte SHA-256 de la trame

Sert à deux choses : vérifier une écriture autrement qu'en la relisant octet
par octet, et diagnostiquer à distance (une image en escalier se voit ici
aussi bien que sur l'écran).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb as fbmod  # noqa: E402


def frame_to_image(frame: bytes, info: fbmod.FbInfo):
    """Trame compacte au format du driver -> image PIL RGB."""
    import numpy as np
    from PIL import Image

    if info.bytes_per_pixel == 2:
        a = np.frombuffer(frame, dtype="<u2").reshape(info.yres, info.xres)
    elif info.bytes_per_pixel == 4:
        a = np.frombuffer(frame, dtype="<u4").reshape(info.yres, info.xres)
    else:
        raise NotImplementedError(f"{info.bits_per_pixel} bpp")

    out = np.zeros((info.yres, info.xres, 3), dtype=np.uint8)
    for ch, bf in enumerate((info.red, info.green, info.blue)):
        v = ((a >> bf.offset) & ((1 << bf.length) - 1)).astype(np.uint16)
        # remise à l'échelle 0..255 exacte (5 bits -> 0,8,16,...,255)
        out[:, :, ch] = (v * 255 // ((1 << bf.length) - 1)).astype(np.uint8)
    return Image.fromarray(out, "RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", help="fichier PNG de sortie")
    ap.add_argument("--scale", type=int, default=1, help="diviseur de taille")
    ap.add_argument("--hash", action="store_true", help="afficher le SHA-256")
    ap.add_argument("--device", default="/dev/fb0")
    args = ap.parse_args()

    with fbmod.Framebuffer(args.device) as fbuf:
        frame = fbuf.read_frame()
        print(f"fb   : {fbuf.info}", file=sys.stderr)
        if args.hash or not args.out:
            print(f"sha256 = {hashlib.sha256(frame).hexdigest()}  "
                  f"({len(frame)} octets)")
        if args.out:
            img = frame_to_image(frame, fbuf.info)
            if args.scale > 1:
                img = img.resize((img.width // args.scale, img.height // args.scale))
            img.save(args.out)
            print(f"écrit : {args.out} {img.size}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
