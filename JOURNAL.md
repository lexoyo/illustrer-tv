# Journal — illustrer-tv

## 2026-09-04 — première session : la sortie est prouvée, l'entrée change de modèle

Session idea-lab avec Alex. Point de départ : « est-ce qu'on peut déployer
microturn sur R2 sans le TTS ? ». Point d'arrivée : **microturn n'est pas
réutilisé**, le projet est neuf, et deux de ses trois étages sont mesurés.

### Ce qui est prouvé

**L'affichage sur la télé.** `/dev/fb0` en 1920×1080, 16 bpp (RGB565). Pillow +
mmap, **369 ms par image** à chaud, dont 5 ms d'écriture. Vérifié trois fois,
dont une relecture du framebuffer reconvertie en PNG, **et vu par Alex sur sa
télé** : quatre coins nets, pas de cisaillement, pas d'étirement. 61,8 °C au
pire, pour un mur à 80 °C.
🔴 **Le piège qui a coûté le plus** : `/sys/class/graphics/fb0/blank` valait 4
(écran éteint). Les écritures « réussissaient » et l'écran restait noir, sans un
message d'erreur.

**La transcription, sur du son réel du micro de R2.** Quatre enregistrements
faits ce soir dans le salon, à la distance habituelle d'Alex.

| Modèle | Ce qu'il rend sur « les éléphants d'Asie ont des oreilles plus petites que ceux d'Afrique » |
|---|---|
| `tiny` q5 | « les **élèves fonds** d'Asie ont des oreilles… » |
| **`base` q5** | « Les **éléphants** d'Asie ont des oreilles plus petites que les **éléphants d'Afrique**. » |
| `small` | exact aussi, mais **tronque** : trois répétitions rendues sur cinq dites |

🔴 **`tiny` est disqualifié, et c'était le modèle hérité de microturn.** Les noms
concrets ne survivent pas — le système illustrerait « des élèves » au lieu d'un
éléphant. **`base` q5 est le modèle du projet**, et il n'est **pas installé sur
le Pi** à ce jour.

**Le gain est obligatoire.** La voix arrive à **-12 dBFS de crête** (plancher de
bruit à -41 dBFS, voix entre -28 et -36). Sans normalisation, `tiny` rendait
`(música)` et rien d'autre. Un gain calculé sur la crête (×3 à ×4 selon la
prise) suffit ; ×8 sature sans rien gagner.

**Le seuil de silence de ce micro est à ~-37 dBFS**, pas -40 comme dans
microturn — à -40, tout serait pris pour de la voix. L'écart voix/silence n'est
que de 10 dB : le RMS seul sera un signal fragile.

**Un prompt qui fonctionne, obtenu en une itération.** La v1 (« sois avare »)
refusait d'illustrer « des modèles d'architecture moderne du futur » — un faux
refus. La v2, généreuse (« trouve quelque chose à montrer ; un thème, une
matière, une ambiance suffisent ») rend, sur le **même texte** :
`{"requete": "modèle d'architecture futuriste", "titre": "Architecture
Futuriste", "ton": "neutre", "scene": "une pièce lumineuse où différents modèles
d'architecture sont exposés"}`
Un seul changement, effet net. C'est la v2 qui est la base.

### Le problème ouvert n° 1 — `base` est trop lourd pour le Pi

`base` q5 en beam search : **RTF 1,00 sur shiao** (40 s de calcul pour 40 s
d'audio, 4 threads). Sur un Pi 3B, il faut compter 4 à 6 fois plus, soit **3 à
4 minutes pour 40 s d'audio**. Ça ne tient pas, même avec le déclencheur
espacé.

Le greedy (`-bo 1 -bs 1`) ramène le RTF à **0,61** — mais **détruit les noms
propres** : « architecture » devient « séptéculture ». Inutilisable ici, où tout
repose sur les noms concrets. **Le facteur 2 que microturn documente n'est donc
pas disponible pour cet usage.**

Pistes non explorées, dans l'ordre de promesse :
1. **sherpa-onnx** (zipformer fr en flux), déjà installé sur le Pi *et* sur
   shiao, mesuré à RTF 0,81 sur le Pi par microturn. **Sa qualité sur les noms
   concrets n'est pas mesurée** — c'est le test à faire en premier, il est
   gratuit et il peut tout débloquer.
2. Déporter whisper sur `shiao` : le Pi ne garde que le micro et l'écran. Reste
   dans la maison, mais **contredit la consigne « tout sur le Pi »** d'Alex — à
   lui de trancher, avec ce chiffre sous les yeux.
3. Réduire la fenêtre transcrite (20 s au lieu de 40).

### Ce qui n'a jamais tourné

- **`ecouter.py` (la boucle) : pas une seule fois.** Écrit, syntaxe validée, rien
  de plus.
- **Le déclencheur silence/minuteur : pas codé.** C'est pourtant la décision
  d'architecture la plus importante de la journée (cf. `PLAN.md` § 5).
- **Le décideur local sur le Pi** : confié à un sous-agent, non rendu à l'heure
  où ces lignes sont écrites.
- Le seul essai de bout en bout (`essai.py`) s'est arrêté à l'étape 4 sur un
  faux refus du décideur, donc **aucune image n'a jamais été affichée à partir
  d'une conversation**. Les images vues sur la télé venaient de tests manuels.

### Deux conclusions que j'ai dû corriger dans la même session

À consigner, parce que les deux fois j'ai conclu trop vite sur une seule lecture :

1. J'ai annoncé que `small` **hallucinait** sur le premier enregistrement (« de
   la maîtrise » ×3). Faux : Alex a confirmé que le texte correspondait à ce
   qu'il disait. Seule la triple répétition était un artefact.
2. J'ai annoncé que `base` **inventait** cinq répétitions de la phrase de
   référence. Faux aussi : Alex l'avait dite plus de deux fois. C'est `small`
   qui tronquait — le défaut était sur l'autre modèle.

Règle qui en découle : **ne pas qualifier une sortie d'ASR d'hallucination sans
savoir ce qui a été dit.** La référence, c'est le locuteur, pas le plus gros
modèle.

### Décidé avec Alex, et qui tient

- Pas de temps réel : blocs de 30-60 s, on assume de rater une partie du son.
- **Rien de la conversation ne sort de la machine.** Résidu connu et non résolu :
  la requête d'image de 2 à 5 mots part chez Wikimedia.
- Le déclencheur est **mécanique** (long silence OU toutes les X minutes), pas
  confié au modèle : ça lui retire la décision la plus dure.
- **Le style est séparé du sujet** : `requete` pour la recherche, `scene` + `ton`
  pour l'atmosphère. Le `ton` traite l'image aujourd'hui, `scene` alimentera un
  générateur demain.
- Le corpus (`corpus/`) est **exclu du dépôt** : ce sont des conversations
  privées captées dans le salon.

## 2026-09-04, matin — les deux murs tombent, mesurés sur la machine

Reprise après la publication du dépôt. Trois mesures faites directement sur
`raspi2`, avec le modèle et le son réels.

**whisper `base` q5 sur le Pi : 78,4 s pour 40 s d'audio, RTF 1,96**, 2 threads,
chargement en 0,5 s. Le texte rendu est exact, noms concrets compris. La veille,
j'avais extrapolé « 3 à 4 minutes » depuis un RTF mesuré sur `shiao` : **faux
d'un facteur 2,5**. Extrapoler d'une machine à l'autre n'a pas marché, et c'est
la deuxième fois dans ce projet (microturn avait relevé la même erreur sur le
RTF de sherpa, annoncé à 0,37 et mesuré à 1,151).

**La coexistence en mémoire n'est pas un problème.** Décideur et STT chargés
ensemble : 240 Mo utilisés sur 905, 664 disponibles, swap inchangé à 17 Mio, et
la transcription tourne au même temps qu'isolée. Le RSS de 510 Mio relevé pour
`llama-server` comptait ses pages mmappées.

**Le budget d'un cycle est donc de ~90 s pour 40 s écoutées** — on entend un peu
moins de la moitié de la conversation, ce qui est le compromis retenu dès le
départ.

**Déploiement** : le Pi n'est plus mis à jour par copie mais par `git pull`
depuis ce dépôt. `~/illustrer-tv` y est un clone ; `.venv/`, `corpus/` et les
modèles restent hors dépôt.

Installé sur le Pi ce matin : `models/ggml-base-q5_1.bin` et `pywhispercpp` dans
le venv du projet.

**Ce qui reste, et c'est maintenant le seul obstacle** : la boucle `ecouter.py`
n'a toujours jamais tourné, et le déclencheur silence/minuteur n'est pas écrit.
Tous les étages sont mesurés séparément ; aucun ne les a encore enchaînés.

## 2026-09-04, 10h — le premier bout-en-bout tourne, et le décideur déraille

**La chaîne complète a tourné pour la première fois** (en rejeu, sur
`corpus/ref-loin2.wav`) :

```
[1] 78.5s stt · 75.8°C · "Les éléphants d'Asie ont des oreilles plus petites…"
    OUI (29.3s) « tarte Tatin maison avec1000000000000 » — monument (local)
    aucune image trouvée
```

La transcription est exacte. **Le décideur, lui, répond « tarte Tatin » sur un
texte qui parle d'éléphants**, et classe ça en « monument ». C'est la
contamination par les exemples du prompt relevée dans `MESURES-DECIDEUR.md` —
« tarte Tatin » est un exemple — dont le correctif (n'autoriser dans la requête
que des mots du bloc) avait été **écarté** parce qu'il faisait tomber
`llama-server` et dégradait la décision.

**Conséquence directe : les 5 requêtes justes sur 5 de `cas.json` ne survivent
pas au texte réel.** Le banc mesurait sur du texte propre et court ; ici le texte
fait cinq fois la même phrase (whisper répète, fidèlement, ce qui a été dit cinq
fois) et le prompt devient long — d'où aussi les 29,3 s de décision contre 10,5 s
mesurées.

Deux pistes, dans cet ordre :
1. **Dédupliquer les phrases répétées** avant d'appeler le décideur. Non pas
   parce que whisper invente — il ne le fait pas — mais parce qu'un texte répété
   est un mauvais prompt.
2. **Reprendre l'ancrage aux mots du bloc**, en isolant d'abord le crash de
   `llama-server` sous grammaire reconstruite.

**Le service tourne.** `illustrer-tv.service`, `active` et `enabled` : l'app
écoute la pièce en continu et repart au démarrage du Pi. Le micro est sur
`card 1` — il était sur `card 2` il y a deux heures, et la détection par nom a
tenu.

Deux détails relevés au passage : `setterm` se plaint de `$TERM is not defined`
sous systemd (sans conséquence, `blank=0` suffit), et l'API d'Openverse a
dépassé son délai de 15 s — le repli de recherche est donc lent quand Commons ne
trouve rien.

## 2026-09-04, 17h — un témoin d'écoute, parce que les fenêtres sourdes étaient invisibles

**Le problème n'était pas la boucle, c'était de ne pas la voir.** La chaîne est
strictement séquentielle : `enregistrer` 45 s, *puis* whisper, *puis* le
décideur. Rien n'enregistre pendant la transcription. En régime nominal ça fait
45 s écoutées sur ~122, soit 37 % du temps — et sur les cycles réels de cette
fin d'après-midi, whisper est monté à 175,8 s puis 220,3 s, ce qui fait tomber
la part écoutée à 20 %.

C'est le compromis assumé du projet depuis le premier jour. Ce qui ne l'était
pas : **il ne se voit pas.** Alex a parlé trois fois d'éléphants devant la télé
sans la moindre réaction, parce que ses phrases sont tombées dans les fenêtres
sourdes. Dix minutes passées à parler dans le vide, sans aucun moyen de le
savoir.

**Le témoin** (`temoin.py`) : un disque ambre de 30 px, halo compris 45x45,
posé en bas à droite pendant la prise et effacé dès qu'elle s'arrête. Il ne dit
qu'une chose — *c'est maintenant qu'on peut parler*. Pas de niveau, pas de
compteur, pas de texte : c'est un objet de salon, pas un instrument.

**L'image dessous n'est jamais redessinée.** `fb.py` gagne `read_rect` /
`write_rect` (conscients du stride) : on sauve les 4,1 kio du rectangle, on
dessine, on les remet. Réafficher la photo aurait coûté 369 ms et supposé de
l'avoir gardée en mémoire.

**Ce que la première version coûtait, et pourquoi elle a été refaite** :
composer une image du témoin coûte **2,39 ms** sur ce Pi, l'écrire **0,22 ms** —
le calcul numpy sur 2 025 pixels est écrasé par son propre coût d'appel. À
7,5 images/s recalculées, ça faisait **21,4 ms de CPU par seconde** d'écoute, sur
une machine déjà bridée à 1,03 GHz par sa température. Le fond ne bouge
pourtant pas de toute la prise : la boucle n'affiche une image qu'*après* la
transcription. Le souffle est donc calculé **une fois à l'allumage** (24 images,
~57 ms) puis rejoué en boucle. Mesuré sur un bloc de 45 s, cadre réel :
**3,9 ms de CPU par seconde**, soit 0,4 % d'un cœur.

**Un thread, pas une restructuration.** `enregistrer()` est un `subprocess.run`
d'arecord de 45 s : il bloque, et il n'a aucune raison d'apprendre à dessiner.
Le témoin s'écrit `with etat["temoin"]:` autour de la prise. Le risque de deux
écrivains est nul : entre l'allumage et l'extinction, le thread principal attend
arecord et ne touche pas au framebuffer.

🔴 **Le piège qu'il a fallu boucher** : systemd arrête le service par SIGTERM,
que Python honore en tuant le process **sans dérouler les `finally`**. Le point
serait resté peint sur la télé — et au redémarrage, le premier allumage l'aurait
relu comme s'il faisait partie de l'image, puis remis à chaque extinction : il
serait devenu **permanent**. `ecouter.py` transforme donc SIGTERM en
KeyboardInterrupt, que la boucle savait déjà traiter.

**Vérifié sur le Pi**, `./temoin.py --verifier` (empreinte des pixels du témoin
avant / pendant / après) :

```
zone    avant 9d0c4f6652855079 · pendant 224a606b43dca59c · après 9d0c4f6652855079
VERDICT le témoin s'affiche, s'efface, et rend les pixels d'origine
```

Passé sur la mire, sur un écran noir (cas du démarrage, où aucune image n'a
encore été affichée) et sur un fond clair. Les captures `grab.py` montrent le
disque net sur les trois fonds : c'est le halo, une pénombre de 7 px à 60 %, qui
le sauve sur un fond clair — sans lui il disparaît une fois sur deux selon la
photo affichée dessous.

Un détail relevé au passage : une comparaison **plein écran** échoue toujours,
et pas à cause du témoin — le curseur de la console clignote tout seul en haut à
gauche (8x2 px) dès que `console.sh` n'a pas tourné depuis le dernier
démarrage. L'empreinte porte donc sur le rectangle du témoin, qui est la seule
chose dont il répond.
