#!/usr/bin/env python3
"""Affiche une image plein écran sur le framebuffer HDMI (pas de X ni Wayland).

    ./show.py photo.jpg
    ./show.py https://upload.wikimedia.org/.../truc.jpg
    ./show.py --backend ffmpeg photo.jpg
    ./show.py --clear

Ratio conservé, letterbox sur fond noir, vérification par relecture du
framebuffer. Deux backends de décodage :

  pillow (défaut) — décode + redimensionne + composite dans le process. C'est
      celui qu'on garde pour la suite du projet : on pourra dessiner du texte
      par-dessus l'image (PIL.ImageDraw) sans repasser par un tube.
  ffmpeg          — repli sans aucune dépendance Python : un seul appel
      `scale,pad,format=rgb565le -f rawvideo` dont la sortie va au framebuffer.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

T_IMPORT = time.perf_counter()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fb as fbmod  # noqa: E402

UA = "illustrer-tv/0.1 (microturn prototype; alex@lexoyo.me)"

# Emplacements où chercher un ffmpeg utilisable (le PATH d'abord).
FFMPEG_CANDIDATES = [
    os.path.expanduser(
        "~/microturn/.venv/lib/python3.13/site-packages/imageio_ffmpeg/"
        "binaries/ffmpeg-linux-aarch64-v7.0.2"
    ),
]


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for c in FFMPEG_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def fetch(src: str) -> tuple[str, bool]:
    """Renvoie (chemin local, à_supprimer). Accepte un chemin ou une URL."""
    if "://" not in src:
        if not os.path.isfile(src):
            sys.exit(f"introuvable : {src}")
        return src, False
    req = urllib.request.Request(src, headers={"User-Agent": UA})
    ext = os.path.splitext(src.split("?")[0])[1][:6] or ".img"
    fd, path = tempfile.mkstemp(prefix="illustrer-tv-", suffix=ext)
    with os.fdopen(fd, "wb") as out, urllib.request.urlopen(req, timeout=30) as r:
        shutil.copyfileobj(r, out)
    return path, True


def pix_fmt_for(info: fbmod.FbInfo) -> str:
    """Nom du pix_fmt ffmpeg correspondant à l'ordre des canaux du driver."""
    r, g, b = info.red, info.green, info.blue
    if info.bits_per_pixel == 16 and (r.length, g.length, b.length) == (5, 6, 5):
        if (r.offset, g.offset, b.offset) == (11, 5, 0):
            return "rgb565le"
        if (r.offset, g.offset, b.offset) == (0, 5, 11):
            return "bgr565le"
    if info.bits_per_pixel == 32:
        if (r.offset, g.offset, b.offset) == (16, 8, 0):
            return "bgra"
        if (r.offset, g.offset, b.offset) == (0, 8, 16):
            return "rgba"
    raise SystemExit(
        f"pas de pix_fmt ffmpeg connu pour ce framebuffer ({info}) — "
        f"utilise --backend pillow"
    )


def decode_ffmpeg(path: str, info: fbmod.FbInfo, ffmpeg: str,
                  cadrage: str = "cover") -> bytes:
    W, H = info.xres, info.yres
    pf = pix_fmt_for(info)
    # Le repli ffmpeg doit cadrer comme pillow, sinon l'option ne veut rien dire
    # selon le backend — et le backend, lui, est choisi automatiquement.
    if cadrage == "cover":
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},format={pf}")
    else:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,format={pf}")
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", path,
           "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", pf, "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        sys.exit(f"ffmpeg a échoué :\n{p.stderr.decode(errors='replace')}")
    want = W * H * info.bytes_per_pixel
    if len(p.stdout) != want:
        sys.exit(f"ffmpeg a rendu {len(p.stdout)} octets, attendu {want}")
    return p.stdout


def preload(backend: str) -> None:
    """Charge PIL/numpy AVANT de chronométrer.

    Sur un Pi 3B ces imports coûtent ~0,5 s. Les compter dans le temps de
    décodage donnerait un chiffre faux (et pessimiste) pour le cas réel du
    projet, où le process tourne en continu et n'importe qu'une fois.
    """
    if backend == "pillow":
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401


def decode_pillow(path: str, fbuf: fbmod.Framebuffer, quality: str,
                  cadrage: str = "cover") -> bytes:
    import numpy as np
    from PIL import Image

    resample = {"fast": Image.BILINEAR, "good": Image.LANCZOS}[quality]
    with Image.open(path) as img:
        img.draft("RGB", fbuf.size)  # décodage JPEG en DCT scaling : gros gain
        cadre = fbmod.cover if cadrage == "cover" else fbmod.letterbox
        canvas = cadre(img, fbuf.size, resample=resample)
    return fbuf.pack_array(np.asarray(canvas))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", help="chemin local ou URL http(s)")
    ap.add_argument("--backend", choices=["auto", "pillow", "ffmpeg"], default="auto")
    ap.add_argument("--cadrage", choices=["cover", "contain"], default="cover",
                    help="cover : remplit l'écran en rognant (défaut, c'est ce "
                         "qu'on veut sur une télé) ; contain : image entière "
                         "avec des bandes noires")
    ap.add_argument("--quality", choices=["fast", "good"], default="fast",
                    help="filtre de redimensionnement du backend pillow")
    ap.add_argument("--device", default="/dev/fb0")
    ap.add_argument("--clear", action="store_true", help="écran noir puis sortie")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="réafficher N fois (mesure le cas process long, "
                         "sans le coût des imports)")
    ap.add_argument("--json", action="store_true",
                    help="mesures en JSON sur stdout (pour scripter / mesurer)")
    args = ap.parse_args()

    if not args.image and not args.clear:
        ap.error("donne une image, ou --clear")

    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    with fbmod.Framebuffer(args.device) as fbuf:
        log(f"fb      : {fbuf.info}")
        log(f"blank   : {fbmod.unblank()}")

        if args.clear:
            fbuf.clear()
            log("écran effacé")
            return 0

        backend = args.backend
        if backend == "auto":
            try:
                import PIL  # noqa: F401
                backend = "pillow"
            except ImportError:
                backend = "ffmpeg"
        ffmpeg = find_ffmpeg() if backend == "ffmpeg" else None
        if backend == "ffmpeg" and not ffmpeg:
            sys.exit("ffmpeg introuvable (ni dans le PATH ni aux emplacements connus)")

        t_pre = time.perf_counter()
        preload(backend)
        t_preloaded = time.perf_counter()

        path, tmp = fetch(args.image)
        t_fetch = time.perf_counter()
        try:
            runs = []
            for _ in range(max(1, args.repeat)):
                t_a = time.perf_counter()
                if backend == "pillow":
                    frame = decode_pillow(path, fbuf, args.quality, a.cadrage)
                else:
                    frame = decode_ffmpeg(path, fbuf.info, ffmpeg, a.cadrage)
                t_decode = time.perf_counter()
                fbuf.write_frame(frame)
                t_write = time.perf_counter()
                runs.append((t_a, t_decode, t_write))

            ok = ""
            t_v0 = time.perf_counter()
            if not args.no_verify:
                checked, same = fbuf.probe(frame)
                ok = f"  relecture {same}/{checked} pixels identiques"
                if same != checked:
                    print(f"ATTENTION : {checked - same}/{checked} pixels témoins "
                          f"diffèrent après relecture", file=sys.stderr)
            t_end = time.perf_counter()

            ms = lambda a, b: round(1e3 * (b - a), 1)
            n = len(runs)
            dec = sum(ms(a, d) for a, d, _ in runs) / n
            wr = sum(ms(d, w) for _, d, w in runs) / n
            timing = {
                "backend": backend,
                "quality": args.quality if backend == "pillow" else None,
                "source": args.image,
                "repeat": n,
                # coût une fois par process (imports Python, ouverture du fb)
                "startup_ms": ms(T_IMPORT, t_pre),
                "preload_ms": ms(t_pre, t_preloaded),
                "fetch_ms": ms(t_preloaded, t_fetch),
                # coût par image, process déjà chaud : c'est LE chiffre du projet
                "decode_scale_ms": round(dec, 1),
                "write_fb_ms": round(wr, 1),
                "disk_to_screen_ms": round(dec + wr, 1),
                "verify_ms": ms(t_v0, t_end),
                "total_ms": ms(T_IMPORT, t_end),
            }
            log(f"backend : {backend}"
                + (f" ({args.quality})" if backend == "pillow" else "")
                + (f" x{n}" if n > 1 else ""))
            log(f"une fois: démarrage {timing['startup_ms']:.0f} ms | "
                f"imports {timing['preload_ms']:.0f} ms | "
                f"source {timing['fetch_ms']:.0f} ms")
            log(f"par img : décode+scale {timing['decode_scale_ms']:.0f} ms | "
                f"écriture fb {timing['write_fb_ms']:.0f} ms | "
                f"=> disque->écran {timing['disk_to_screen_ms']:.0f} ms")
            log(f"état    : affiché.{ok}")
            if args.json:
                print(json.dumps(timing))
        finally:
            if tmp:
                os.unlink(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
