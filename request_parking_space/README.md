# Extract Parking Spaces From OSM

Ce dossier est autonome. Il permet d'extraire depuis OSM les objets de stationnement auto sous forme de surfaces quand elles existent, sinon sous forme de points, et d'ajouter une estimation surfacique du stationnement sur rue quand il est decrit par les tags lateraux OSM.

## Contenu

- `load_osm_parking_spots.py` : script principal
- `load_osm_parking_spots.ipynb` : notebook minimal qui lance le script
- `requirements_osm.txt` : dependances Python
- `input/AGGLO_PERIMETRE_AVEC_LAC.*` : perimetre GG par defaut
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
python load_osm_parking_spots.py
```

## Sorties

- `output/parking_spaces.parquet`
- `output/parking_spaces.geojson`

Le fichier exporte :

- les surfaces `amenity=parking` ou `parking=*` quand OSM fournit des polygones
- les `amenity=parking_space`
- un repli en points pour les objets non surfaciques
- les bandes de stationnement sur rue reconstruites a partir des tags `parking:left/right/both` et `parking:lane:*`

Colonnes principales :

- `parking_type`
- `geometry_kind`
- `surface_m2`
- `osm_id`
- `parking_side`
- `parking_orientation`
- `estimated_width_m`

## Changer la zone

Dans `load_osm_parking_spots.py` :

- pour utiliser le perimetre GG fourni, laisser `area_mode = "shapefile"`
- pour telecharger une autre zone via OSM, mettre `area_mode = "geocode"` et modifier `places`

## Notes

- Le script telecharge lui-meme les donnees OSM.
- Pour les grands perimetres, le telechargement est decoupe en tuiles, tente plusieurs serveurs Overpass et redecoupe automatiquement une tuile qui echoue en sous-tuiles plus petites.
- Les logs indiquent explicitement quelle requete OSM est en cours, avec les tags demandes.
- L'export final est en `EPSG:4326`.
- Les calculs internes de surface sont faits en `EPSG:2056`.

## Limites

- Le stationnement sur rue est une estimation surfacique a partir de l'axe de voirie et des tags OSM, pas une geometrie exacte du bord de trottoir.
- Les largeurs deduites dependent de l'orientation estimee du stationnement (`parallel`, `diagonal`, `perpendicular`).
- Si les tags OSM sont absents ou incomplets, le stationnement sur rue restera absent ou partiel.
