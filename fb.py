"""Accès bas niveau au framebuffer Linux (/dev/fb0), sans X ni Wayland.

Brique de sortie réutilisable : ouvre le framebuffer, lit sa vraie géométrie
via ioctl (résolution, bits par pixel, *stride*, position des canaux R/G/B),
et sait y écrire une image PIL en plein écran letterboxé.

Testé sur Raspberry Pi 3B / Raspberry Pi OS Lite trixie arm64, pilote
`vc4drmfb` : 1920x1080, 16 bpp, RGB565 little-endian, stride 3840.
Le code ne suppose rien de tout ça : tout vient de l'ioctl.
"""

from __future__ import annotations

import fcntl
import mmap
import os
import struct
from dataclasses import dataclass

# <linux/fb.h>
FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602

SYS_FB = "/sys/class/graphics/fb0"


@dataclass(frozen=True)
class Bitfield:
    offset: int
    length: int
    msb_right: int


@dataclass(frozen=True)
class FbInfo:
    xres: int
    yres: int
    bits_per_pixel: int
    line_length: int  # stride en octets — PAS forcément xres * bpp/8
    smem_len: int
    red: Bitfield
    green: Bitfield
    blue: Bitfield
    fix_id: str

    @property
    def bytes_per_pixel(self) -> int:
        return self.bits_per_pixel // 8

    @property
    def row_bytes(self) -> int:
        """Octets réellement utiles par ligne (sans le padding de stride)."""
        return self.xres * self.bytes_per_pixel

    @property
    def padded(self) -> bool:
        return self.line_length != self.row_bytes

    def __str__(self) -> str:
        return (
            f"{self.fix_id} {self.xres}x{self.yres} {self.bits_per_pixel}bpp "
            f"stride={self.line_length} (utile={self.row_bytes}"
            f"{', PADDÉ' if self.padded else ''}) "
            f"R@{self.red.offset}/{self.red.length} "
            f"G@{self.green.offset}/{self.green.length} "
            f"B@{self.blue.offset}/{self.blue.length}"
        )


def read_fb_info(fd: int) -> FbInfo:
    """Interroge le driver plutôt que de deviner. C'est ça qui évite l'escalier."""
    var = fcntl.ioctl(fd, FBIOGET_VSCREENINFO, b"\0" * 160)
    u = struct.unpack("<40I", var[:160])
    xres, yres = u[0], u[1]
    bpp = u[6]
    fields = [Bitfield(u[8 + i * 3], u[9 + i * 3], u[10 + i * 3]) for i in range(3)]

    fix = fcntl.ioctl(fd, FBIOGET_FSCREENINFO, b"\0" * 80)
    fix_id = fix[:16].split(b"\0")[0].decode("ascii", "replace")
    smem_len = struct.unpack("<I", fix[24:28])[0]
    line_length = struct.unpack("<I", fix[48:52])[0]
    if line_length == 0:  # driver avare : on retombe sur le calcul naïf
        line_length = xres * (bpp // 8)

    return FbInfo(
        xres=xres,
        yres=yres,
        bits_per_pixel=bpp,
        line_length=line_length,
        smem_len=smem_len or line_length * yres,
        red=fields[0],
        green=fields[1],
        blue=fields[2],
        fix_id=fix_id,
    )


def unblank(sys_fb: str = SYS_FB) -> str:
    """Rallume le framebuffer s'il est en veille. Renvoie ce qui a été fait.

    `blank` vaut 0 (allumé), 1 (normal standby), 2 (suspend), 3 (off),
    4 (powerdown). Sur un Pi Lite sans session graphique il est très souvent
    à 4 : l'écriture dans /dev/fb0 « réussit » mais rien ne s'affiche.
    Le fichier appartient à root, d'où le besoin de sudo pour le corriger.
    """
    path = os.path.join(sys_fb, "blank")
    try:
        with open(path) as f:
            cur = f.read().strip()
    except OSError as e:
        return f"blank illisible ({e})"
    if cur == "0":
        return "blank=0 (déjà allumé)"
    try:
        with open(path, "w") as f:
            f.write("0\n")
        return f"blank {cur} -> 0"
    except OSError:
        return (
            f"blank={cur} (écran en veille) et /sys non inscriptible — lance :\n"
            f"    echo 0 | sudo tee {path}"
        )


class Framebuffer:
    """Le framebuffer, mmappé. À utiliser en context manager."""

    def __init__(self, path: str = "/dev/fb0"):
        self.path = path
        self._fd = os.open(path, os.O_RDWR)
        try:
            self.info = read_fb_info(self._fd)
            self._map = mmap.mmap(
                self._fd, self.info.smem_len, mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE,
            )
        except Exception:
            os.close(self._fd)
            raise

    # -- cycle de vie -----------------------------------------------------
    def close(self) -> None:
        try:
            self._map.flush()
            self._map.close()
        finally:
            os.close(self._fd)

    def __enter__(self) -> "Framebuffer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def size(self) -> tuple[int, int]:
        return self.info.xres, self.info.yres

    # -- écriture ---------------------------------------------------------
    def write_frame(self, frame: bytes | bytearray | memoryview) -> None:
        """Écrit une trame *compacte* (xres*yres*bpp/8, sans padding).

        C'est ici que le stride est géré : si line_length > row_bytes, on
        recopie ligne par ligne au bon offset. Écrire la trame d'un bloc dans
        ce cas produit l'image en diagonale (l'« escalier »).
        """
        i = self.info
        expected = i.row_bytes * i.yres
        if len(frame) != expected:
            raise ValueError(
                f"trame de {len(frame)} octets, attendu {expected} "
                f"({i.xres}x{i.yres}x{i.bytes_per_pixel})"
            )
        if not i.padded:
            self._map[0:expected] = frame
        else:
            view = memoryview(frame)
            for y in range(i.yres):
                off = y * i.line_length
                self._map[off:off + i.row_bytes] = view[y * i.row_bytes:(y + 1) * i.row_bytes]
        self._map.flush()

    def read_frame(self) -> bytes:
        """Relit la zone utile (padding de stride retiré) — pour vérifier."""
        i = self.info
        if not i.padded:
            return bytes(self._map[0:i.row_bytes * i.yres])
        out = bytearray(i.row_bytes * i.yres)
        for y in range(i.yres):
            off = y * i.line_length
            out[y * i.row_bytes:(y + 1) * i.row_bytes] = self._map[off:off + i.row_bytes]
        return bytes(out)

    def clear(self, rgb: tuple[int, int, int] = (0, 0, 0)) -> None:
        px = self.pack_pixel(rgb)
        self.write_frame(px * (self.info.xres * self.info.yres))

    # -- conversion de pixels --------------------------------------------
    def pack_pixel(self, rgb: tuple[int, int, int]) -> bytes:
        """Un pixel RGB888 -> octets natifs du framebuffer (little-endian)."""
        i = self.info
        r, g, b = rgb
        v = (
            ((r >> (8 - i.red.length)) << i.red.offset)
            | ((g >> (8 - i.green.length)) << i.green.offset)
            | ((b >> (8 - i.blue.length)) << i.blue.offset)
        )
        return int(v).to_bytes(i.bytes_per_pixel, "little")

    def pack_array(self, rgb_array) -> bytes:
        """numpy (H, W, 3) uint8 -> trame compacte au format du framebuffer."""
        import numpy as np

        i = self.info
        a = np.asarray(rgb_array)
        if a.shape[:2] != (i.yres, i.xres):
            raise ValueError(f"array {a.shape[:2]}, attendu {(i.yres, i.xres)}")
        if i.bytes_per_pixel == 2:
            acc = np.zeros((i.yres, i.xres), dtype=np.uint16)
            for ch, bf in enumerate((i.red, i.green, i.blue)):
                acc |= (a[:, :, ch] >> (8 - bf.length)).astype(np.uint16) << bf.offset
            return acc.astype("<u2").tobytes()
        if i.bytes_per_pixel == 4:
            acc = np.zeros((i.yres, i.xres), dtype=np.uint32)
            for ch, bf in enumerate((i.red, i.green, i.blue)):
                acc |= (a[:, :, ch] >> (8 - bf.length)).astype(np.uint32) << bf.offset
            return acc.astype("<u4").tobytes()
        raise NotImplementedError(f"{i.bits_per_pixel} bpp non géré")

    # -- image ------------------------------------------------------------
    def show_image(self, img, resample=None) -> None:
        """Affiche une image PIL en plein écran, ratio conservé, fond noir."""
        import numpy as np
        from PIL import Image

        if resample is None:
            resample = Image.BILINEAR
        canvas = letterbox(img, self.size, resample=resample)
        self.write_frame(self.pack_array(np.asarray(canvas)))

    def probe(self, frame: bytes, n: int = 64) -> tuple[int, int]:
        """Compare n pixels témoins de `frame` avec ce que le fb contient.

        Renvoie (vérifiés, identiques). Une écriture peut « réussir » sans que
        le driver l'ait acceptée : on relit pour en être sûr.
        """
        i = self.info
        bpp = i.bytes_per_pixel
        got = self.read_frame()
        step = max(1, (i.xres * i.yres) // n)
        checked = same = 0
        for p in range(0, i.xres * i.yres, step):
            o = p * bpp
            checked += 1
            if got[o:o + bpp] == frame[o:o + bpp]:
                same += 1
        return checked, same


def letterbox(img, size: tuple[int, int], resample=None, bg=(0, 0, 0)):
    """Redimensionne en conservant le ratio et centre sur un fond uni."""
    from PIL import Image, ImageOps

    if resample is None:
        resample = Image.BILINEAR
    W, H = size
    img = ImageOps.exif_transpose(img)  # les photos de téléphone sont tournées
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    scale = min(W / w, H / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((nw, nh), resample)
    canvas = Image.new("RGB", (W, H), bg)
    canvas.paste(resized, ((W - nw) // 2, (H - nh) // 2))
    return canvas
