# illustrer-tv — le plan

Écouter les conversations d'une pièce, les comprendre, et les illustrer sur la
télé. Sur un Raspberry Pi 3B (`raspi2`), branché en HDMI sur la télé du salon.

Décidé avec Alex le 04/09/2026. Ce fichier dit **ce qu'on construit et dans quel
ordre** ; `TESTS.md` dit **comment on saura que ça marche**.

## Les quatre décisions qui commandent tout le reste

**1. Ce n'est pas du temps réel, et c'est ce qui rend le projet possible.**
On enregistre un bloc de 45 s, *puis* on le transcrit. Le calcul dépasse la
durée du bloc, donc on rate à peu près la moitié de ce qui se dit. Assumé : le
sujet d'une conversation survit à un trou de 40 s. C'est ce qui permet
d'utiliser whisper en batch (texte ponctué, plus juste) au lieu d'un ASR en flux,
et de ne jamais courir après une horloge.

**2. Rien de la conversation ne sort de la machine.** Exigence dure posée par
Alex : ce sont ses conversations privées. Micro, transcription et décision sont
locaux. Ne sortent que la requête d'image (2 à 5 mots) et le téléchargement de
l'image.
⚠️ **Résidu connu, non résolu** : cette requête de 3 mots est un dérivé de la
conversation, et elle part chez Wikimedia. Faible, non nul. Piste si ça gêne un
jour : une banque d'images pré-téléchargée, ou un générateur local — hors de
portée de cette machine.

**3. Le style est séparé du sujet.** La sortie du décideur porte `requete` (mots
nus, pour la recherche) *et* `scene` + `ton` (l'atmosphère). Aujourd'hui le `ton`
sert à traiter l'image trouvée ; demain `scene` sera le prompt du générateur.
Le style **ne doit jamais entrer dans la requête de recherche** : Commons est un
fonds documentaire indexé par mots-clés, l'atmosphère y détruit les résultats.

**5. Le déclencheur est mécanique, pas confié au modèle.** Décidé par Alex le
04/09, contre ma première version. On n'appelle plus le modèle à chaque bloc pour
lui demander « faut-il illustrer ? » : on l'appelle **quand un long silence
arrive, ou au plus tard toutes les X minutes**, jamais moins de N secondes après
la dernière image.

Pourquoi c'est meilleur : la **retenue** était le risque n° 1 du projet (un
modèle de 0,5 B qui dit oui à tout fait clignoter la télé d'images sans rapport).
Un déclencheur mécanique est infaillible là où un prompt est fragile. Le modèle
ne fait plus que « de quoi parle-t-on, sur quel ton » — tâche bien plus facile —
et le nombre d'appels s'effondre, donc la chaleur avec.

Deux critères et non un, parce qu'aucun ne suffit seul : **le silence est le bon
signal** (il marque la fin d'un sujet, on ne change pas l'image au milieu d'une
phrase) **mais peut ne jamais arriver** dans un salon animé, avec de la musique
ou un film en fond ; **le minuteur garantit un rythme** mais tombe volontiers au
milieu d'une phrase. Donc `silence OU minuteur`, avec un plancher anti-clignotement.

Valeurs de départ, à régler et non à défendre : silence ≥ 6 s, X = 3 min,
plancher 90 s.
⚠️ **Le seuil de silence se mesure sur ce micro**, il ne se reprend pas de
microturn : leur porte, calibrée à l'oreille, jetait 81 % de l'audio d'une
session réelle. Le RMS suffit — pas besoin de whisper ni du modèle pour savoir
que personne ne parle, donc le déclencheur est gratuit.

Le modèle garde le **droit de refuser** (« rien d'illustrable »), mais comme un
cas rare — sur de la bouillie de transcription — et non comme sa décision
principale.

**4. Ce projet ne réutilise pas microturn.** Toute la machinerie de microturn
(tick de 1,2 s, agrégateur de delta, machine à états du tour de parole) existe
pour répondre en moins d'une seconde. Ici personne ne s'adresse au système et la
latence n'a pas d'importance : cet appareillage n'aurait été qu'un coût. Ce qu'on
lui emprunte : les modèles déjà installés sur le Pi, et ses règles de méthode
(`bench/BOUCLE.md`, `PROTOCOLE.md`).

## L'architecture

```
arecord 45 s  ──▶  whisper tiny q5   ──▶  décideur LOCAL (llama.cpp)
  (local)            (local, ~40-70 s)      illustrer ? requete + scene + ton
                                                        │
   framebuffer  ◀── traitement du ton ◀── recherche d'image (Wikimedia/Openverse)
   (fb.py, 369 ms)      (Pillow)               ▲ le seul flux sortant
```

| Brique | Fichier | État |
|---|---|---|
| Affichage framebuffer | `fb.py`, `show.py` | **fait et vu sur la télé** — 369 ms/image, 61,8 °C au pire |
| Mire, capture d'écran, banc | `testcard.py`, `grab.py`, `bench.sh` | fait |
| Boucle micro → whisper → image | `ecouter.py` | écrit, **pas encore exercé de bout en bout** |
| Décideur local | `decideur_local.py` | en cours (sous-agent) |
| Traitement du ton | — | itération 1 ci-dessous |

## La file d'itérations

Règles héritées de `microturn/bench/BOUCLE.md` : **un seul changement par
itération**, hypothèse formulée avec son sens attendu *avant* de coder, commit à
chaque tour même en échec, et aucun écart inférieur au bruit ne compte.

### Bloc A — la ligne de base (prérequis, aucune modification)

Sans point de départ chiffré, aucune itération suivante ne veut rien dire.

- **A1** — le bruit de mesure du décideur local. Un llama.cpp à température 0 et
  graine fixe devrait être *déterministe*, donc bruit nul et tout écart
  significatif. **À vérifier, pas à supposer** : c'est ce qui distingue ce projet
  de microturn, dont le décideur distant avait ±0,017 de bruit.
- **A2** — un cycle complet sur le Pi, chronométré poste par poste. Le chiffre
  qui compte est la **durée totale du cycle** : c'est lui qui dit quelle part de
  la conversation on rate.

### Bloc B — le ton et le style (ce qu'Alex a demandé le 04/09)

- **B1** — ajouter `ton` en **liste fermée** de six valeurs (neutre, sombre,
  chaleureux, comique, onirique, clinique), forcé par grammaire GBNF.
  *Hypothèse* : un champ de plus dégrade la décision d'un modèle de 0,5 B ; une
  enum contrainte le dégrade **moins** qu'un texte libre. Sens attendu : faux
  positifs stables, JSON valide à 100 %.
- **B2** — appliquer le ton à l'image (Pillow : virage colorimétrique, contraste,
  désaturation, vignettage). *Hypothèse* : le rendu cesse de ressembler à une
  illustration d'encyclopédie. **Jugement d'Alex, pas une métrique.**
- **B3** — ajouter `scene` (texte libre, l'atmosphère décrite). Inutilisé
  aujourd'hui, il prépare la génération d'image. *Hypothèse* : un champ libre en
  fin de sortie ne coûte rien à la décision, puisqu'elle est déjà prise.

### Bloc C — le déclencheur (remplace l'ancien bloc « retenue »)

L'ancien bloc C cherchait à obtenir la retenue par le prompt. La décision n° 5
la rend structurelle : **ce bloc est donc largement vidé de son objet**, et c'est
un gain, pas une perte. Ce qui reste :

- **C1** — mesurer le seuil de silence sur ce micro, pièce vide puis pièce
  occupée. Sans ce chiffre, le déclencheur se déclenche au hasard.
- **C2** — implémenter `silence OU minuteur` avec le plancher. *Hypothèse* : les
  faux positifs deviennent structurellement impossibles ; ce qui peut encore
  échouer, c'est le **moment** (une image qui arrive trop tard, ou sur un sujet
  déjà clos).
- **C3** — un pré-filtre gratuit : sous N caractères utiles dans la fenêtre, ne
  pas appeler le modèle du tout. Économise du CPU et de la chaleur.

### Bloc D — après, seulement après

Le réglage fin : durée du bloc, taille de la fenêtre de contexte, nombre de
threads whisper, choix de la banque d'images, `tiny` contre `base`.

## Quand s'arrêter

- Dix itérations, ou trois d'affilée sans dépasser le bruit.
- Ou un arbitrage qui revient à Alex. Les deux connus d'avance : **la retenue se
  paie en réactivité** (C1 ajoute 45 s), et **le corpus manque** (voir ci-dessous).

## Le trou connu : il n'y a pas de corpus réel

Le jeu de cas de `TESTS.md` est **écrit à la main**. Il attrape les défauts
grossiers (un modèle qui dit oui à tout), il ne mesure pas ce système sur ces
conversations : whisper abîme le texte à sa façon, et une conversation réelle ne
ressemble pas à un exemple inventé. Optimiser un prompt contre des exemples
inventés est exactement le « chiffre plausible et vide de sens » que la QC de
`BOUCLE.md` cherche à attraper.

**Ce qui débloque** : une soirée d'écoute enregistrée avec `--trace` (audio,
texte, verdict et image de chaque cycle), puis une annotation par Alex — « là il
fallait une image, là non » — sur quelques dizaines de cycles. Tant que ce
corpus n'existe pas, les blocs B et C se mesurent sur du synthétique et il faut
l'écrire dans chaque verdict.

## Ce qui reste à trancher avec Alex

- **Licence et publication.** Alex a demandé le 04/09 une publication publique
  sur GitHub en fin de session. microturn est en AGPL ; à confirmer pour
  celui-ci. Audit obligatoire avant : aucune clé, aucun mot de passe, aucune
  adresse.
- **La génération d'image** : quand `scene` sera branché, sur quel moteur ? Rien
  ne tourne localement sur cette machine, donc ce sera une API — et **ce jour-là,
  la scène décrite sort de la maison.** À rediscuter à ce moment-là, c'est la
  décision n° 2 qui est en jeu.
