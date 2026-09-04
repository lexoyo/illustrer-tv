# illustrer-tv

Écouter les conversations d'une pièce, et illustrer sur la télé ce dont on parle.

Un Raspberry Pi 3B branché en HDMI sur la télé du salon. Il écoute, transcrit,
comprend de quoi on parle, cherche une image, l'affiche. Personne ne lui parle,
il n'y a pas de mot-clé, pas de bouton, et **il ne répond jamais**.

```
micro ──▶ whisper ──▶ décideur local ──▶ recherche d'image ──▶ télé
(local)   (local)      (local)            ▲ le seul flux sortant
```

**État : prototype en cours. La boucle complète n'a jamais tourné.** Deux de ses
trois étages sont mesurés, le troisième bute sur un mur documenté plus bas. Ce
dépôt est publié parce que les mesures valent d'être lues, pas parce que ça
marche.

## Les quatre décisions qui commandent tout

**Ce n'est pas du temps réel, et c'est ce qui rend le projet possible.** On
enregistre un bloc, *puis* on le transcrit. Le calcul dépasse la durée du bloc,
donc on rate une partie de ce qui se dit. Assumé : le sujet d'une conversation
survit à un trou de quarante secondes.

**Rien de la conversation ne sort de la machine.** Micro, transcription et
décision sont locaux. Ne sortent que la requête d'image — deux à cinq mots — et
le téléchargement. C'est un résidu connu, pas un oubli.

**Le déclencheur est mécanique, pas confié au modèle.** On n'appelle pas le
modèle à chaque bloc pour lui demander « faut-il illustrer ? » : on l'appelle
quand un long silence arrive, ou au plus tard toutes les X minutes. La retenue
est le risque numéro un d'un modèle de 0,5 B — un déclencheur mécanique est
infaillible là où un prompt est fragile.

**Le style est séparé du sujet.** La sortie porte `requete` (mots nus, pour la
recherche) et `scene` + `ton` (l'atmosphère). Le style ne doit jamais entrer
dans la requête de recherche : Commons est un fonds documentaire indexé par
mots-clés, l'atmosphère y détruit les résultats. `scene` prépare le jour où les
images seront générées plutôt que cherchées.

## Ce qui est mesuré

**L'affichage** — `/dev/fb0` en 1920×1080, 16 bpp, sans serveur graphique.
**369 ms par image** à chaud avec Pillow, dont 5 ms d'écriture. Détails,
mesures et pièges : [`AFFICHAGE.md`](AFFICHAGE.md).

**La transcription**, sur du son réel capté par le micro d'une webcam à deux
mètres :

| modèle | sur « les éléphants d'Asie ont des oreilles plus petites que ceux d'Afrique » |
|---|---|
| `tiny` q5 | « les **élèves fonds** d'Asie ont des oreilles… » |
| **`base` q5** | « Les **éléphants** d'Asie ont des oreilles plus petites que les **éléphants d'Afrique**. » |

`tiny` est **disqualifié** : les noms concrets ne survivent pas, et tout ce
projet repose sur eux. Un **gain numérique est obligatoire** — la voix arrive à
-12 dBFS de crête, et sans normalisation `tiny` ne rendait que `(música)`.

**Le décideur, en local sur le Pi** — `qwen2.5-0.5b-q4`, 17 cas de test :

| modèle | faux positifs /12 | faux négatifs /5 | requêtes justes /5 | latence médiane |
|---|---|---|---|---|
| smollm2-135m-q4 | 2 | 2 | 1 | 3,9 s |
| smollm2-360m-q4 | 0 | 5 | 0 | 10,9 s |
| **qwen2.5-0.5b-q4** | **2** | **0** | **5** | **10,5 s** |

Le zéro de smollm2-360m est un fil débranché : il répond « non » aux dix-sept
cas. C'est pourquoi les deux classes sont comptées séparément, toujours.

Deux leviers qui portent tout le reste : **`llama-server` au lieu d'un process
par bloc** (facteur 5 à 8 — sur un Cortex-A53, relire la consigne coûte plus que
générer la réponse), et une **grammaire GBNF** qui rend le format de sortie
impossible à rater. Méthode et chiffres complets :
[`MESURES-DECIDEUR.md`](MESURES-DECIDEUR.md).

## Le mur, et il n'est pas franchi

`base` q5 tourne à **RTF 1,00** sur un i7-7500U en beam search, donc trois à
quatre minutes de calcul pour quarante secondes d'audio sur un Pi 3B. Le greedy
le ramène à 0,61 mais **détruit les noms propres** — « architecture » devient
« séptéculture » — ce qui est précisément ce qu'on ne peut pas perdre.

Et un second mur, non mesuré : la **coexistence en mémoire**. Le décideur occupe
510 Mio, `base` en demandera 200 à 250, sur 905 disponibles.

La piste à tester en premier : **sherpa-onnx**, déjà installé, mesuré à RTF 0,81
sur cette machine. Sa qualité sur les noms concrets est inconnue.

## Lire ce dépôt

| Fichier | Ce qu'il contient |
|---|---|
| [`PLAN.md`](PLAN.md) | Ce qu'on construit, la file d'itérations, ce qui reste à trancher |
| [`TESTS.md`](TESTS.md) | Les critères de notation, et pourquoi jamais un score agrégé |
| [`JOURNAL.md`](JOURNAL.md) | Ce qui a été mesuré, séance par séance, échecs compris |
| [`AFFICHAGE.md`](AFFICHAGE.md) | La brique framebuffer, en détail |
| [`MESURES-DECIDEUR.md`](MESURES-DECIDEUR.md) | Le banc du décideur local |

Le code : `ecouter.py` (la boucle, **jamais exécutée**), `decideur_local.py`,
`fb.py` et `show.py` (l'affichage), `essai.py` (un cycle manuel de bout en bout),
`cas.json` et `bench_decideur.py` (le banc).

## Parenté

Ce projet naît d'un pivot de [microturn](https://github.com/lexoyo/microturn),
et n'en réutilise **aucun code**. Toute la machinerie de microturn — horloge à
1,2 s, agrégateur de deltas, machine à états du tour de parole — existe pour
répondre en moins d'une seconde à quelqu'un qui vous parle. Ici personne ne
parle au système et la latence n'a aucune importance : cet appareillage n'aurait
été qu'un coût.

Ce qu'il en reste : ses règles de méthode. Un seul changement par itération,
aucun écart inférieur au bruit ne compte, et rien n'entre ici sans être mesuré.

## Licence

AGPL-3.0. Voir [`LICENSE`](LICENSE).
