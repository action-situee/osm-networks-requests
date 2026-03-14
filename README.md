# OSM Networks Requests

Ce depot regroupe deux scripts autonomes pour extraire des donnees OSM.

## Dossiers

- `request_active_mode_network/` : export de reseaux marche et velo.
- `request_parking_space/` : extraction des stationnements auto (surfaces, points, et estimation sur rue).

Chaque dossier contient son propre script, un notebook minimal et un fichier `requirements_osm.txt`.

## Installation rapide (recommande)

Depuis la racine du depot :

```bash
python -m venv venv-osm
source venv-osm/bin/activate
pip install -r request_active_mode_network/requirements_osm.txt
```

Si besoin, installer aussi les dependances du second dossier :

```bash
pip install -r request_parking_space/requirements_osm.txt
```

## Execution

- Marche + velo :

```bash
cd request_active_mode_network
python load_osm_networks_bike_walk.py
```

- Stationnement :

```bash
cd request_parking_space
python load_osm_parking_spots.py
```

Voir les README dans chaque dossier pour les details de configuration et les sorties.
