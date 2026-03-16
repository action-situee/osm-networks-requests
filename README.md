# OSM Networks Requests

Ce dépôt contient deux scripts Python pour extraire des données OpenStreetMap utiles à des analyses SIG :

- un export de réseaux de marche et de vélo ;
- un export de stationnements automobiles.

Ce développement s'inscrit dans le projet Marchabilité et Cyclabilité, porté par Bureau Action Située et financé par l'État de Genève.

Chaque dossier est autonome et contient :

- un script principal ;
- un notebook minimal ;
- un fichier `requirements_osm.txt` ;
- un dossier `input/` avec le périmètre fourni ;
- un dossier `output/` créé à l'exécution.

## Structure

- `request_active_mode_network/` : extraction des réseaux marche et vélo.
- `request_parking_space/` : extraction des stationnements surfaciques, ponctuels et du stationnement sur rue estimé à partir des tags OSM.

## Prérequis

- Python `3.11` recommandé ;
- `pip` ;
- une connexion internet pour interroger OSM / Overpass.

## Installation

Depuis la racine du dépôt :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r request_active_mode_network/requirements_osm.txt
```

Les deux fichiers `requirements_osm.txt` sont actuellement équivalents, donc une seule installation suffit.

## Utilisation

### Réseaux marche et vélo

```bash
cd request_active_mode_network
python load_osm_networks_bike_walk.py
```

Sorties principales :

- `output/walk_network.parquet`
- `output/walk_network.geojson`
- `output/bike_network.parquet`
- `output/bike_network.geojson`

### Stationnement

```bash
cd request_parking_space
python load_osm_parking_spots.py
```

Sorties principales :

- `output/parking_spaces.parquet`
- `output/parking_spaces.geojson`

## Paramétrage

Les paramètres se modifient directement dans chaque script Python, notamment :

- la zone d'étude (`geocode` ou `shapefile`) ;
- les lieux à interroger ;
- les formats d'export ;
- certaines options de nettoyage ou de reconstruction.

Un shapefile de périmètre est fourni dans chaque dossier `input/`.

## Notes

- Les exports finaux sont en `EPSG:4326`.
- Les temps de traitement dépendent de la taille de la zone et de la qualité des serveurs Overpass.
- Les résultats dépendent directement de la qualité du renseignement OSM sur la zone étudiée.
- Le module stationnement reste plus exploratoire que le module réseaux.
- Les données OpenStreetMap mobilisées par ces scripts sont distinctes du code du dépôt et restent soumises à leur propre licence.

## Documentation

Pour plus de détails sur les paramètres, hypothèses et limites, voir :

- [request_active_mode_network/README.md](request_active_mode_network/README.md)
- [request_parking_space/README.md](request_parking_space/README.md)

## How to cite

Pour citer ce logiciel, utiliser de préférence les métadonnées du fichier [CITATION.cff](CITATION.cff).

Auteur à citer : Marc-Edouard Schultheiss.  
Structure à mentionner : Bureau Action Située.  
Contexte du projet : développement inscrit dans le projet Marchabilité et Cyclabilité, financé par l'État de Genève.

Citation textuelle simple :

```text
Bureau Action Située. 2026. OSM Networks Requests. Bureau Action Située. Software developed within the Marchabilité et Cyclabilité project, funded partially by the État de Genève. https://github.com/action-situee/osm-networks-requests/
```

## Licence

Le code de ce dépôt est distribué sous licence Apache 2.0. Voir `LICENSE` et `NOTICE`.
Les données OpenStreetMap restent distinctes du code et relèvent de leur propre licence.
