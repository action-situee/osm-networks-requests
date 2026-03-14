# Export OSM Networks

Ce dossier est autonome. Il permet d'exporter un reseau marche et un reseau velo depuis OSM.

## Contenu

- `load_osm_networks_bike_walk.py` : script principal
- `load_osm_networks_bike_walk.ipynb` : notebook minimal qui lance le script
- `requirements_osm.txt` : dependances Python
- `input/AGGLO_PERIMETRE_AVEC_LAC.*` : si geocode == shapefile
- `output/` : dossier de sortie

## Installation

Python recommande : `3.11`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_osm.txt
```

## Execution

Depuis ce dossier :

```bash
python load_osm_networks_bike_walk.py
```

Les fichiers exportes seront ecrits dans `output/`.

## Sorties

- `output/walk_network.parquet`
- `output/walk_network.geojson`
- `output/bike_network.parquet`
- `output/bike_network.geojson`

Le `walk_network` contient une colonne `tier` :

- `priority` : elements pietons prioritaires
- `secondary` : elements pietons secondaires

## Changer la zone

Dans `load_osm_networks_bike_walk.py` :

- pour utiliser le perimetre GG fourni, laisser `area_mode = "shapefile"`
- pour telecharger une autre zone via OSM, mettre `area_mode = "geocode"` et modifier `places`
- pour sortir un reseau nettoye, laisser `apply_network_cleanup = True`
- pour sortir un reseau brut OSM, mettre `apply_network_cleanup = False`

## Notes

- Le script telecharge lui-meme les donnees OSM.
- Pour les grands perimetres, le telechargement est decoupe en tuiles et tente plusieurs serveurs Overpass.
- Les logs indiquent explicitement quelle requete OSM est en cours, avec les tags demandes.
- Le reseau exporte est en `EPSG:4326`.
- Les calculs internes sont faits en `EPSG:2056`.
- Si `apply_network_cleanup = False`, le script n'ajoute pas les traverses synthetiques ni les contours de quais, et ne fait pas de dedoublonnage, de simplification ni de decoupage aux intersections.

## Ameliorations possibles

### Marchabilite

Le reseau marchable recupere volontairement large. Cela permet de ne pas perdre de continuite, mais cree parfois des redondances.

Points ameliorables :

- axe central de route + trottoirs explicites : aujourd'hui, certaines rues peuvent apparaitre a la fois via un axe routier proxy et via des objets pietons dedies
- dedoublonnage plus fort des proxies : la logique actuelle retire deja une partie des doublons, mais elle peut etre rendue plus stricte sur les routes ou des trottoirs paralleles existent deja
- usage des tags `sidewalk`, `sidewalk:left`, `sidewalk:right`, `footway=sidewalk` : ils peuvent etre exploites plus finement pour garder l'axe central uniquement quand aucun trottoir dedie n'existe
- filtrage par parallellisme et distance : on peut comparer un axe routier et un trottoir voisin avec seuils sur distance, angle et longueur de recouvrement
- filtrage par type de route : les doublons sont plus problematiques sur `primary`, `secondary`, `tertiary` que sur `residential` ou `service`
- prise en compte du nom de rue et de la topologie : utile pour confirmer qu'un axe routier et un trottoir voisin representent bien le meme espace de circulation
- option de sortie : exposer un parametre pour choisir entre reseau `complet`, `nettoye leger`, `nettoye fort`

### Cyclabilite

Le reseau velo souffre du meme type de probleme : certaines infrastructures apparaissent a la fois comme voie dediee et comme axe routier partage.

Points ameliorables :

- axe de chaussee + piste cyclable adjacente : il peut etre utile de conserver les deux pour certaines analyses, mais cela cree des doublons pour d'autres usages
- bandes cyclables sur chaussee : il faut distinguer les cas ou la route doit rester dans le reseau de ceux ou l'infrastructure cyclable suffit comme representation
- pistes separatives mappees a cote de la route : on peut filtrer l'axe routier si une `cycleway/track` parallele existe a distance faible
- chemins mixtes `path` / `pedestrian + bicycle=yes` : ils doivent parfois etre gardes comme reseau cyclable secondaire plutot que comme infrastructure principale
- sens de circulation : sur le velo, le nettoyage doit rester compatible avec `oneway` et `oneway:bicycle`
- dedoublonnage geometrique par type d'infrastructure : ne pas fusionner aveuglement une `piste_cyclable` avec une route `sur_chaussee`
- hierarchisation des objets : definir une priorite explicite entre `piste_cyclable`, `bande_cyclable`, `chemin`, `voie_speciale`, `sur_chaussee`
- option de sortie : proposer un reseau velo `complet` et un reseau velo `dedoublonne`

En pratique, la bonne strategie depend de l'usage final :

- analyse d'accessibilite ou de continuite : garder un reseau plutot large
- cartographie ou comptage de longueur d'infrastructure : appliquer un nettoyage plus agressif des doublons
