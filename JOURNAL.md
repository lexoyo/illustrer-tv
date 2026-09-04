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
