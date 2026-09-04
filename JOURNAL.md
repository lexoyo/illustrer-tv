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

## 2026-09-04, 17h30 — on enlève tout ce qui décidait, et l'écran se met à vivre

Six heures d'écoute dans le salon, **136 cycles, une seule image affichée**. Les
trois « oui » du décideur étaient dégénérés : « musique de la musique », « video
de la vidéo », « tarte Tatin aube etApplication ». Et sur « J'aime le vélo… on
voit dans Paris il y a plein de vélo au sacré cœur partout », il a rendu
`oui|objet|vélo et vélo partageur` — il **rate « Sacré-Cœur »**, le seul mot
cherchable de la phrase, et **invente « partageur »**, absent de la
transcription.

Verdict d'Alex : la consigne, les douze exemples, les huit catégories et la
grammaire GBNF coûtent ~600 tokens de préfixe et 5 à 19 s par bloc pour produire
ça. **On enlève.** Deux changements, tous les deux les siens.

### 1. Le décideur n'a plus de prompt

Supprimés : `CONSIGNE`, `EXEMPLES`, `CATEGORIES`, `PREFIXE`, la grammaire
(`_ENTETE`, `_MOT_LIBRE`, `grammaire()`, `ancrage`), la fonction `lire()` et son
garde-fou « déjà à l'écran ». Supprimée aussi, la `CONSIGNE` de la voie distante
et son `response_format: json_object` : les deux voies doivent rester
interchangeables, c'est une règle du projet.

Ce qui reste : **le prompt est la transcription du bloc et rien d'autre, ce que
le modèle écrit ensuite est la requête d'image verbatim.** Pas de nettoyage, pas
de validation, pas de traduction. `illustrer` vaut toujours vrai.

Supprimée également la fenêtre de trois blocs (`FENETRE`) : « la transcription du
bloc, et rien d'autre » ne se discute pas, et c'est elle qui rendait `cache_prompt`
crédible. **Si Alex la voulait, c'est le point à me signaler.**

**La latence.** Avant : 10,5 s de médiane au banc, 5 à 19 s en service, jusqu'à
29,3 s sur un texte répétitif. Après, 14 blocs réels relevés dans le journal du
service, Pi entre 72 et 86 °C :

| n_predict | latence médiane | min | max | images trouvées /14 |
|---|---|---|---|---|
| 4 | 1,2 s | 0,9 | 3,2 | 11 |
| **6 (retenu)** | **2,1 s** | 1,0 | 4,6 | **10** |
| 10 | 3,6 s | 1,0 | 19,8 | 7 |

Le prompt est passé de ~600 tokens à 12–28. La lecture du prompt était **le
poste principal sur un Cortex-A53** — c'était le résultat n° 1 de
`MESURES-DECIDEUR.md` — et elle a simplement disparu ; ce qui reste est de la
génération pure, donc la latence est linéaire en `n_predict`.

**`cache_prompt` : mesuré, et il ne sert plus à rien.** A/B/A sur les 14 blocs
(True, False, True) : **11,8 s / 11,8 s / 2,3 s** de médiane. L'écart entre les
deux passes `True` est cinq fois celui entre `True` et `False` — ce qu'on mesure
là c'est la température du Pi (86 °C, bridé), pas le cache. Il ne coûte rien, il
ne rapporte rien, il reste à `True`.

### 2. Quelqu'un parle, l'image change

Deux conditions ET : du son au-dessus du fond, et des mots (`parole_utile`,
inchangée). Le son se mesure **sur le WAV avant whisper**, ce qui a un effet de
bord considérable : **un bloc où la pièce se tait ne paie plus les 70 à 260 s de
transcription.** Le 04/09, 95 cycles sur 136 ne contenaient que des étiquettes de
bruit.

🔴 **Deux façons de mesurer ce son ne marchent pas, et il fallait les essayer
pour le savoir.** Un **seuil absolu** d'abord : le plancher de cette pièce était
à -41 dBFS RMS le matin (relevé dans ce journal) et à **-34,6 dBFS** le soir, sur
trois blocs de 45 s pris à vide. Six décibels d'écart dans la même pièce le même
jour. Le **RMS du bloc entier** ensuite, et c'est pire :

| bloc | RMS global | p10 | p90 | p90 − p10 |
|---|---|---|---|---|
| pièce vide ×3 (le soir) | -34,6 / -34,6 / -34,3 | -35,2 | -34,1 | **1,1** |
| base-01 (voix) | -35,7 | -41,2 | -31,5 | 9,7 |
| essai (voix) | -34,1 | -44,4 | -28,5 | 15,9 |
| ref-loin2 (voix) | -32,1 | -44,6 | -27,3 | 17,3 |
| ref-loin (voix) | -30,2 | -43,6 | -26,2 | 17,3 |

Le RMS d'un bloc de voix (-30 à -36) **recouvre entièrement** celui d'un bloc
vide (-34,6) : une voix n'occupe qu'une fraction des 45 s et la moyenne la noie.
Ce qui sépare, c'est l'écart entre les moments forts et le fond — 1,1 dB quand la
pièce souffle toute seule, 9,7 à 17,3 dB dès qu'une voix passe.

Retenu : `fort` (p90 des trames de 200 ms) contre le **plus haut** du plancher
glissant de la pièce (25e centile des p10 des vingt derniers blocs) et du fond du
bloc lui-même, plus 5 dB.

🔴 **Le plancher glissant seul ne suffisait pas, et c'est le test qui l'a dit.**
Les sept blocs disponibles présentés dans trois ordres — dont un qui mélange
exprès la soirée du 03 (fond -44) et celle du 04 (fond -35), ce qui simule un
saut de plancher de 9 dB en 45 s :

| ordre | plancher glissant seul | `max(plancher, fond du bloc)` |
|---|---|---|
| pièce puis voix | 7/7 | 7/7 |
| entrelacé | 4/7 | **7/7** |
| voix puis pièce | 4/7 | **7/7** |

Le silence de la pièce ne peut pas être plus bas que ce que ce bloc-ci a entendu
pendant ses creux : prendre le plus haut des deux n'est pas une ceinture de plus,
c'est ce qui fait tenir la mesure. Marge restante, mince : 3,9 dB de garde sur le
bloc vide le plus fort, 4,7 dB sur la voix la plus faible. **Sept blocs ne
mesurent presque rien** — un cas vaut 14 points.

**Supprimé avec ça** : la règle « déjà à l'écran » (c'est elle qui a figé la télé
cinq heures sur « musique de la »), le mécanisme d'oubli `OUBLI`/`etat["age"]`
ajouté le matin pour la rattraper — on ne rattrape pas une règle qu'on supprime —
et `etat["sujet"]`.

**Même sujet, autre image.** `chercher_image()` rend maintenant une liste de
candidats classés, et la boucle garde les **identifiants de fichier** déjà
montrés (`etat["vues"]`, 300 au plus). Vérifié : trois appels de suite sur
« Sacré-Cœur » rendent trois fichiers Commons différents.

**`chercher_image()` est enfichable.** Un moteur = une fonction
`requete -> [(url, identifiant), …]`, enregistrée dans `MOTEURS`, choisie par
`CHAINE`. Changer de moteur ne touche que ces deux noms. **Aucun moteur
généraliste n'est écrit** : la place est préparée, rien de plus.

### ⚠ La latence : trois mesures, dont deux qui ne veulent rien dire

**1. Le banc sur 14 blocs (1 à 6 s) est un plancher, pas une prévision.** Ces
blocs sont les extraits du journal du service, **tronqués à 70 caractères**. Un
vrai bloc de 45 s de whisper fait 100 à 200 tokens, et le premier cycle réel avec
le nouveau code a mis **53,0 s**. Le prompt n'est plus les ~600 tokens de la
consigne, mais il n'est pas non plus les 12 à 28 tokens du banc : c'est la
longueur du bloc.

**2. Le journal du service ne compare pas ce qu'il a l'air de comparer.** 70
appels avec l'ancien prompt : médiane **19,1 s**, p90 62,3 s, max 95,7 s (et non
10,5 s — le banc de `MESURES-DECIDEUR.md` tournait sur une machine qui ne
transcrivait pas en même temps). Mais l'ancien code appelait le modèle sur des
blocs quasi vides que la porte sonore écarte désormais : les deux populations de
blocs sont différentes, et l'écart avant/après lu dans le journal ne mesure que
ça.

**3. La seule comparaison qui vaille : le MÊME bloc, le même `llama-server`, les
deux prompts, en A/B/B/A pour annuler la dérive thermique.** Bloc de 357
caractères, Pi stabilisé à 86 °C :

| | passes | moyenne |
|---|---|---|
| AVANT — consigne + 12 exemples + grammaire, préfixe chaud | 80,3 / 32,8 / 33,9 / 31,7 s | 44,7 s |
| **APRÈS — bloc nu, `n_predict` 6** | **12,1 / 12,0 / 11,9 / 11,9 s** | **12,0 s** |

La première passe AVANT (80,3 s) est une collision avec le whisper du service ;
les trois autres tiennent en 2 s d'écart. **Le rapport honnête est donc 32,8 s
→ 12,0 s, un facteur 2,7**, et il est reproductible à 0,2 s près côté APRÈS.

Ce n'est pas la lecture du préfixe qui coûtait — `cache_prompt` la supprimait
déjà, c'était tout l'objet de `MESURES-DECIDEUR.md`. Ce qui coûte, c'est que
**chaque token généré paie une attention sur tout le contexte** : 693 tokens de
profondeur et 14 tokens à générer contre 100 et 6. Le prompt court est deux fois
gagnant.

🔴 **Et c'est une correction à ce que j'avais écrit plus haut dans cette même
entrée** : sur le cas courant de l'ancien code — un « non » — la grammaire
ramenait la génération à 2 tokens, et l'ancien prompt était alors *plus rapide*
que le nouveau (3,2 s contre 1,6 s sur le bloc court… non, l'inverse ; mais 3,7 s
contre 1,7 s à froid, l'écart est mince). L'ancien design n'était pas lent par
bêtise. Ce qu'on a acheté ce soir, c'est un comportement, pas de la vitesse — et
la vitesse est venue par-dessus, sur les blocs longs.

**Ce qui domine tout, de très loin, c'est whisper et la température.** Sur les
cinq cycles observés après le changement : 368,9 s, 78,9 s, 209,1 s et 416,1 s de
transcription pour 45 s d'audio, à 82-86,5 °C. RTF 1,8 à 9,2. Le décideur, à 12 s
ou à 53 s, ne se voit pas là-dedans.

### Le déclencheur en service : les deux conditions tirent, et la porte sonore
### est trop permissive pour cette pièce ce soir

Cinq cycles observés après le déploiement, tous les cas de figure sont passés :

| cycle | `fort` | ce qui s'est passé |
|---|---|---|
| [1] | -19,9 dBFS | parole → whisper 368,9 s → requête `. - On va faire tout` → **image changée** |
| [2] | -29,3 dBFS | sous le seuil -28,8 → **pas de whisper du tout** |
| [3] | -27,3 dBFS | passe la porte, whisper 78,9 s, rend `... ...` → pas de parole |
| [4] | -27,8 dBFS | passe la porte, whisper 209,1 s, rend `[Musique]` → pas de parole |
| [5] | -10,2 dBFS | parole → cycle complet |

🔴 **Un seul bloc muet sur trois a été arrêté avant whisper.** Les deux autres
sont passés à 0,5 et 1,0 dB au-dessus du seuil, et c'est `parole_utile` qui les a
attrapés — après avoir payé 79 s et 209 s de transcription. Le gain « la pièce
vide ne paie plus whisper » est donc réel mais **beaucoup plus petit qu'annoncé**
ce soir dans cette pièce-là : le fond y est vivant (-27 à -29 dBFS de crête sans
personne qui parle), pas le souffle plat des trois blocs de référence.

Monter la marge au-dessus de 5 dB fermerait ces deux blocs — et rapprocherait le
seuil de la voix la plus faible mesurée (4,7 dB de garde). Je ne l'ai pas fait :
on ne règle pas un seuil sur cinq cycles, et le sens de l'erreur qu'Alex a choisi
est celui-là — mieux vaut transcrire pour rien que rater quelqu'un qui parle.

### Ce qui ne marche pas, et c'est le résultat le plus important

**Le modèle nu ne produit pas des requêtes, il continue la conversation.** Un
modèle de base complète du texte, il ne le résume pas ; sans consigne il n'a
aucune raison de faire autre chose. Sur les blocs réels, `n_predict` 6 :

| ce que la pièce a dit | ce que le modèle écrit | ce que ça affiche |
|---|---|---|
| « J'aime le vélo… plein de vélo au sacré cœur partout » | `. C'est un bon moyen` | un recueil d'actes de Louis XII |
| « Les éléphants d'Asie ont des oreilles plus petites… » | ` C'est une propriété de la` | *Les bains de la Samaritaine* |
| « Nous sommes en train de faire le débat de la France… » | ` question qui est très importante.` | un Dan Flavin |

**Aucune de ces images n'a de rapport avec la conversation.** Le lien est qu'un
mot de la suite du modèle tombe sur un titre de Commons. C'est le pari d'Alex
tenu à la lettre — « se tromper d'image n'est pas grave, rester figé l'est » — et
il faut le lire tel quel : on est passé de 3 déclenchements en 136 cycles à
10 images sur 14 blocs, en échange de **zéro pertinence**.

**Quatre requêtes sur quatorze ne ramènent rien du tout**, et l'écran reste alors
figé. Commons et Openverse ne rendent rien dès que la requête est bancale. C'est
exactement le trou que la forme enfichable de `chercher_image()` prépare à
boucher.

**Ce qui n'est pas mesuré** : la pertinence perçue des images sur la télé (c'est
le jugement d'Alex, pas le mien), et la tenue d'une longue soirée avec le nouveau
déclencheur.

### Une erreur de méthode à consigner

J'ai tenu le service à terre avec une boucle de `pkill` pendant les mesures, faute
de `sudo` pour un `systemctl stop`. Résultat : **68 redémarrages**, le process tué
2 s après chaque démarrage, donc il n'atteignait jamais la phase d'écoute — et un
aplat blanc sur la télé du salon pendant qu'Alex la regardait. Un objet de salon
se mesure sans le débrancher : tuer le process **une fois** quand il faut
recharger le code, et le laisser vivre entre deux.
