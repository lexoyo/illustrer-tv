# illustrer-tv

Écouter les conversations d'une pièce, et illustrer sur la télé ce dont on parle.

Un Raspberry Pi 3B branché en HDMI sur la télé du salon. Il écoute, transcrit,
comprend de quoi on parle, cherche une image, l'affiche. Personne ne lui parle,
il n'y a pas de mot-clé, pas de bouton, et **il ne répond jamais**.

```
micro ──▶ niveau ──▶ whisper ──▶ modèle local ──▶ recherche d'image ──▶ télé
(local)   (local)    (local)     (local)          ▲ le seul flux sortant
```

**État : prototype qui tourne en continu dans le salon depuis le 04/09/2026.**
Les trois étages sont mesurés et la boucle enchaîne ses cycles. Ce qu'elle
montre à l'écran, en revanche, n'a le plus souvent aucun rapport avec la
conversation — voir « Ce qui ne marche pas » plus bas, qui est la partie de ce
fichier à lire en premier.

## Les quatre décisions qui commandent tout

**Ce n'est pas du temps réel, et c'est ce qui rend le projet possible.** On
enregistre un bloc, *puis* on le transcrit. Le calcul dépasse la durée du bloc,
donc on rate une partie de ce qui se dit. Assumé : le sujet d'une conversation
survit à un trou de quarante secondes.

**Rien de la conversation ne sort de la machine.** Micro, transcription et
décision sont locaux. Ne sortent que la requête d'image — deux à cinq mots — et
le téléchargement. C'est un résidu connu, pas un oubli.

**Le déclencheur est mécanique, pas confié au modèle.** C'était vrai dès le
premier jour dans l'intention ; depuis le 04/09/2026 au soir c'est vrai dans le
code, et sans réserve. **Deux conditions, toutes les deux nécessaires : du son
au-dessus du fond de la pièce, ET des mots.** Le son se mesure sur le WAV avant
whisper (`ecouter.niveau`), les mots sont ce qui reste de la transcription une
fois retirées les étiquettes de bruit de whisper (`ecouter.parole_utile`). Le
modèle n'a plus voix au chapitre : la retenue est le risque numéro un d'un
0,5 B, et une soirée de six heures pour une seule image l'a montré en grand.

**Le modèle ne décide plus s'il faut illustrer, il dit quoi montrer — et on lui
a tout retiré pour ça.** Plus de consigne, plus d'exemples, plus de catégories,
plus de grammaire : on lui donne la transcription du bloc, et ce qu'il écrit
ensuite part verbatim dans la recherche d'image. C'est une décision d'Alex, prise
pour tester nue une machinerie qui coûtait ~600 tokens de préfixe par bloc et ne
rendait que des requêtes dégénérées (« musique de la musique », « vélo et vélo
partageur »). Le résultat est mesuré, et il est à moitié bon : l'écran vit enfin,
et il montre presque n'importe quoi.

**Se tromper d'image n'est pas grave, rester figé l'est.** C'est un objet
d'ambiance, pas un instrument de mesure. Tout le reste en découle : quand la
requête ramène des images déjà vues on en prend une autre, et quand elle ne
ramène rien on ne touche pas à l'écran.

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

**Le déclencheur sonore** — sept blocs de 45 s (trois de pièce vide, quatre de
voix d'Alex à deux mètres), classés 7/7 dans trois ordres de présentation. Le
chiffre qui compte n'est pas là : c'est que **ni un seuil absolu ni le RMS du
bloc ne marchent**. Le plancher de la pièce est passé de -41 à -34,6 dBFS en une
journée, et le RMS d'un bloc de voix (-30 à -36) recouvre entièrement celui d'un
bloc vide (-34,6) parce qu'une voix n'occupe qu'une fraction des 45 s. Ce qui
sépare, c'est l'écart entre les moments forts et le fond : **1,1 dB** quand la
pièce souffle toute seule, **9,7 à 17,3 dB** dès qu'une voix passe. Détail du
calcul et des mesures : en tête du § « niveau » de `ecouter.py`.

**Le modèle local, sans consigne** — `qwen2.5-0.5b-q4`, 14 blocs réels relevés
dans le journal du service :

| n_predict | latence médiane | images trouvées /14 |
|---|---|---|
| 4 | 1,2 s | 11 |
| **6** | **2,1 s** | **10** |
| 10 | 3,6 s | 7 |

Contre 10,5 s de médiane au banc et 5 à 19 s en service avec l'ancien prompt :
la lecture de la consigne était le poste principal sur un Cortex-A53, et elle a
disparu. **Les deux colonnes disent la même chose** : plus la suite du modèle
s'allonge, moins elle ressemble à une requête, parce qu'une phrase française
entière ne rencontre aucun mot-clé de Commons.

Le levier qui survit de tout ce banc : **`llama-server` au lieu d'un process par
bloc**. La grammaire GBNF, les huit catégories et les douze exemples ont été
supprimés le 04/09/2026 ; ce qu'ils valaient et pourquoi ils ont sauté est dans
[`MESURES-DECIDEUR.md`](MESURES-DECIDEUR.md), qui est désormais un document
historique.

## Le budget d'un cycle, mesuré sur la machine cible

Les deux murs annoncés plus haut dans l'histoire de ce projet ont été mesurés,
et **aucun des deux n'a tenu**.

| poste | sur le Pi 3B |
|---|---|
| mesure du niveau sonore (avant whisper) | quelques ms |
| whisper `base` q5, 2 threads | **78,4 s pour 40 s d'audio — RTF 1,96**, et jusqu'à 260 s quand le Pi bride |
| modèle local sans consigne, `n_predict` 6 | 2,1 s (médiane) |
| recherche + téléchargement + affichage | ~1,5 s |
| **cycle complet** | **~90 s pour 40 s écoutées** quand la pièce parle |

Autrement dit : **on entend un peu moins de la moitié de la conversation**, ce
qui est le compromis assumé depuis le début. La mesure du niveau change ce
compte dans le bon sens sans rien coûter : **un bloc où la pièce se tait ne paie
plus whisper du tout**, et le 04/09 la pièce se taisait 95 cycles sur 136. Le
micro passe alors de 37 % du temps à presque tout le temps. Une extrapolation antérieure
annonçait « trois à quatre minutes » — elle était pessimiste d'un facteur 2,5,
et c'est la mesure sur la machine qui l'a corrigée.

**La coexistence en mémoire ne pose pas de problème non plus.** Les deux modèles
chargés simultanément : 240 Mo utilisés sur 905, 664 Mo disponibles, **aucun
swap**, et la transcription prend le même temps qu'isolée (78,5 s contre 78,4).
Le « 510 Mio » relevé pour le décideur comptait ses pages mmappées, qui sont du
cache évictable.

Reste vrai : `base` en greedy tomberait à RTF 0,61 mais **détruirait les noms
propres** (« architecture » devient « séptéculture »), et c'est exactement ce
qu'on ne peut pas perdre. Le beam search n'est pas négociable ici.

Thermique : 72 à 74 °C en fin de cycle, sans bridage actif, sur une machine sans
dissipateur.

## Ce qui ne marche pas

C'est la section à lire avant de croire les tableaux du dessus.

**Le modèle nu ne produit pas des requêtes, il continue la conversation.** Un
modèle de base complète du texte, il ne le résume pas ; sans consigne il n'a
aucune raison de faire autre chose. Relevé tel quel sur trois des quatorze blocs
réels, `n_predict` 6 :

| ce que la pièce a dit (whisper) | ce que le modèle écrit |
|---|---|
| « J'aime le vélo, on voit dans Paris il y a plein de vélo au sacré cœur partout » | `. C'est un bon moyen` |
| « Les éléphants d'Asie ont des oreilles plus petites que les éléphants d'Afrique. » | ` C'est une propriété de la` |
| « Nous sommes en train de faire le débat de la France, et nous avons une » | ` question qui est très importante.` |

Aucune de ces suites ne parle du sujet du bloc. Les images qu'elles ramènent sont
donc **sans rapport avec la conversation** : un mot de la suite tombe sur un
titre de Commons, et c'est tout le lien qu'il y a. « Une propriété de la » a
ramené *Les bains de la Samaritaine*.

**Quatre requêtes sur quatorze ne ramènent rien du tout**, et l'écran reste alors
figé — le défaut même qu'on essayait de corriger. Commons et Openverse sont des
fonds documentaires indexés par mots-clés : ils ne rendent rien dès que la
requête est bancale. C'est pour ça que `chercher_image()` est enfichable
(`MOTEURS`, `CHAINE` dans `ecouter.py`) : un moteur généraliste (Pexels,
Unsplash, DuckDuckGo images) rend toujours quelque chose. **Aucun n'est écrit —
la place est préparée, rien de plus.**

**Le pouvoir de résolution est faible partout.** Sept blocs pour le déclencheur
sonore, quatorze pour le modèle : un cas vaut 14 % ou 7 %. Aucun écart d'un seul
cas ne conclut quoi que ce soit, et c'est la règle du dépôt (cf.
[`TESTS.md`](TESTS.md)).

**Ce qui n'est toujours pas mesuré** : la pertinence des images réellement
affichées, jugée par quelqu'un dans la pièce, et la tenue sur une longue soirée
avec le nouveau déclencheur.

## Lire ce dépôt

| Fichier | Ce qu'il contient |
|---|---|
| [`PLAN.md`](PLAN.md) | Ce qu'on construit, la file d'itérations, ce qui reste à trancher |
| [`TESTS.md`](TESTS.md) | Les critères de notation, et pourquoi jamais un score agrégé |
| [`JOURNAL.md`](JOURNAL.md) | Ce qui a été mesuré, séance par séance, échecs compris |
| [`AFFICHAGE.md`](AFFICHAGE.md) | La brique framebuffer, en détail |
| [`MESURES-DECIDEUR.md`](MESURES-DECIDEUR.md) | Le banc du décideur local |

Le code : `ecouter.py` (la boucle, **jamais exécutée**), `decideur_local.py`,
`fb.py` et `show.py` (l'affichage), `temoin.py` (le point qui dit quand le micro
écoute), `essai.py` (un cycle manuel de bout en bout), `cas.json` et
`bench_decideur.py` (le banc).

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
