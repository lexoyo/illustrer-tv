#!/usr/bin/env python3
"""Un essai réel de bout en bout : micro du Pi → base → décideur → image → télé.

Le décideur tourne ICI, sur shiao, avec ollama : local, donc rien ne sort, mais
c'est la borne haute (3 B) et non le 0,5 B visé sur le Pi.
"""
import json, math, array, os, wave, subprocess, sys, time, urllib.parse, urllib.request

# Tout se paramètre par l'environnement : ce fichier est public, et un chemin
# de clé SSH ou un nom de machine en dur n'y a rien à faire.
PI = os.environ.get("ILLUSTRER_PI", "raspi2")
CLE = os.environ.get("ILLUSTRER_SSH_KEY", "")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"] \
      + (["-i", CLE] if CLE else []) + [PI]
WHISPER = os.environ.get("ILLUSTRER_WHISPER",
                         "/opt/whisper.cpp/build/bin/whisper-cli")
BASE = os.environ.get("ILLUSTRER_MODELE_STT", "models/ggml-base-q5_1.bin")
UA = "illustrer-tv/0.1 (prototype; alex@lexoyo.me)"
SECONDES = int(sys.argv[1]) if len(sys.argv) > 1 else 40

CONSIGNE = """Tu reçois la transcription automatique d'une conversation entendue \
dans une pièce. Personne ne s'adresse à toi, et le texte est imparfait.

Dis de quoi on parle, pour l'illustrer sur l'écran de la pièce.

Réponds par un objet JSON, rien d'autre :
{"requete": "2 à 5 mots pour chercher une image", "titre": "le sujet en 3 mots", \
"ton": "neutre|sombre|chaleureux|comique|onirique|clinique", \
"scene": "une phrase décrivant l'image idéale et son atmosphère"}

Si rien de concret ni de visuel n'est dit : {"rien": true}

La requête décrit la CHOSE, pas la conversation : « tour Eiffel de nuit », \
jamais « ils parlent de Paris »."""


def etape(n, s):
    print(f"\n[{n}] {s}", flush=True)


# 1. capture
etape(1, f"enregistrement de {SECONDES} s (2 bips = parle)")
subprocess.run(["./bip.sh", "parle"])
carte = subprocess.run(SSH + ["arecord -l | grep -m1 0x46d | sed 's/^card \\([0-9]*\\).*/\\1/'"],
                       capture_output=True, text=True).stdout.strip()
subprocess.run(SSH + [f"arecord -q -D plughw:{carte},0 -f S16_LE -r 16000 -c 1 "
                      f"-d {SECONDES} -t wav ~/illustrer-tv/corpus/essai.wav"], check=True)
subprocess.run(["./bip.sh", "stop"])
subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes"]
               + (["-i", CLE] if CLE else [])
               + [f"{PI}:~/illustrer-tv/corpus/essai.wav", "corpus/"], check=True)

# 2. gain automatique : whisper décroche sous -20 dBFS de crête
etape(2, "normalisation")
w = wave.open("corpus/essai.wav"); sr = w.getframerate()
a = array.array("h"); a.frombytes(w.readframes(w.getnframes()))
crete = max(abs(x) for x in a) or 1
g = max(1.0, 26000 / crete)
b = array.array("h", (max(-32768, min(32767, int(x * g))) for x in a))
o = wave.open("corpus/essai.norm.wav", "wb")
o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes(b.tobytes()); o.close()
print(f"    crête {crete}/32768 ({20*math.log10(crete/32768):.0f} dBFS) → gain ×{g:.1f}")

# 3. transcription
etape(3, "whisper base")
t0 = time.monotonic()
r = subprocess.run([WHISPER, "-m", BASE, "-l", "fr", "-nt", "-t", "4",
                    "-f", "corpus/essai.norm.wav"], capture_output=True, text=True)
texte = " ".join(r.stdout.split())
print(f"    {time.monotonic()-t0:.1f} s pour {SECONDES} s d'audio "
      f"(RTF {(time.monotonic()-t0)/SECONDES:.2f})")
print(f"    « {texte[:400]} »")
if len(texte) < 15:
    sys.exit("rien d'audible")

# 4. décideur local
etape(4, "décideur — qwen2.5:3b, en local")
t0 = time.monotonic()
req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({"model": "qwen2.5:3b", "prompt": texte, "system": CONSIGNE,
                     "format": "json", "stream": False,
                     "options": {"temperature": 0}}).encode(),
    headers={"Content-Type": "application/json"})
rep = json.loads(urllib.request.urlopen(req, timeout=180).read())["response"]
print(f"    {time.monotonic()-t0:.1f} s")
v = json.loads(rep)
print(f"    {json.dumps(v, ensure_ascii=False)}")
if v.get("rien") or not v.get("requete"):
    sys.exit("le décideur ne voit rien à illustrer")

# 5. recherche d'image
etape(5, f"recherche Wikimedia : « {v['requete']} »")
p = urllib.parse.urlencode({
    "action": "query", "format": "json", "generator": "search",
    "gsrsearch": f"{v['requete']} filetype:bitmap", "gsrnamespace": "6",
    "gsrlimit": "20", "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": "1920"})
d = json.loads(urllib.request.urlopen(
    urllib.request.Request(f"https://commons.wikimedia.org/w/api.php?{p}",
                           headers={"User-Agent": UA}), timeout=20).read())
url = None
for page in (d.get("query", {}).get("pages") or {}).values():
    i = (page.get("imageinfo") or [{}])[0]
    # paysage et assez grand : l'écran est une télé, et le cadrage rogne
    if (i.get("mime") in ("image/jpeg", "image/png") and i.get("thumburl")
            and (i.get("width") or 0) >= 1280
            and (i.get("width") or 0) / (i.get("height") or 1) >= 1.2):
        url, titre = i["thumburl"], page.get("title"); break
if not url:
    sys.exit("aucune image trouvée")
print(f"    {titre}")

# 6. affichage sur la télé
etape(6, "affichage sur la télé")
r = subprocess.run(SSH + [f"cd ~/illustrer-tv && .venv/bin/python show.py '{url}'"],
                   capture_output=True, text=True)
print("   ", (r.stdout or r.stderr).strip()[:300])
print(f"\n→ sujet « {v.get('titre')} », ton « {v.get('ton')} »")
print(f"→ scène pour la génération future : {v.get('scene')}")
