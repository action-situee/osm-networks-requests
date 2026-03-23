# Scripts de récupération OSM simplifiés

Guide d'utilisation pour les trois scripts de collecte de données OpenStreetMap.

---

## Trois scripts, trois objectifs

| Script | Ce qu'il récupère | Fichiers produits |
|---|---|---|
| `fetch_bike_simplified.py` | Réseau cyclable : pistes dédiées + axes primaires/secondaires | `bike.geojson` |
| `fetch_walk_simplified.py` | Réseau piéton (prioritaire + secondaire) | `walk_priority.geojson`, `walk_secondary.geojson`, `walk_all.geojson` |
| `fetch_platform_simplified.py` | Arrêts de bus et plateformes de transport en commun | `platforms.geojson` |

---

## Prérequis

### Version Python

**Utiliser Python 3.12** pour créer le venv. Les versions plus récentes (3.13+) peuvent être incompatibles avec certaines dépendances (`osmnx`, `geopandas`).

```bash
python3.12 -m venv venv-osm
```

### Environnement Python

Le projet utilise un environnement virtuel `venv-osm` à la racine du dépôt.

```bash
# Activer l'environnement (macOS / Linux)
source venv-osm/bin/activate

# Installer les dépendances
pip install -r request_active_mode_network_simplified/requirements_osm.txt

# Vérifier que les packages sont là
python -c "import osmnx, geopandas; print('OK')"
```

### Connexion internet

Les scripts appellent l'API Overpass (serveur public d'OpenStreetMap). Une connexion stable est nécessaire. Les résultats sont **mis en cache** automatiquement dans `cache/` — relancer le script sans changer les paramètres ne re-télécharge pas.

---

## Lancer les scripts

```bash
cd request_active_mode_network_simplified

# Réseau vélo (pistes cyclables + axes primaires/secondaires)
python fetch_bike_simplified.py

# Réseau piéton prioritaire / secondaire
python fetch_walk_simplified.py

# Arrêts de bus et plateformes TC
python fetch_platform_simplified.py
```

Les fichiers de sortie apparaissent dans `output/`.

---

## Ce que récupère chaque script

### `fetch_bike_simplified.py` — Réseau cyclable

#### Tronçons routiers (`bike.geojson`)

Le script demande à OSM tous les segments dont l'attribut `highway` vaut :

| Valeur OSM | Signification |
|---|---|
| `cycleway` | Piste cyclable dédiée (séparée de la chaussée) |
| `primary` | Route principale (nationale / cantonale importante) |
| `primary_link` | Bretelle de raccordement vers une `primary` |
| `secondary` | Route secondaire (cantonale / départementale) |
| `secondary_link` | Bretelle de raccordement vers une `secondary` |

> Les `*_link` sont les bretelles aux giratoires et échangeurs. Peu d'attributs cyclables y sont renseignés, mais ils sont nécessaires pour la continuité topologique du réseau.

Tous les attributs OSM présents sont conservés tels quels — aucun filtrage de colonnes.

---

### `fetch_walk_simplified.py` — Réseau piéton

Le script télécharge un graphe OSM filtré et classe chaque tronçon en deux niveaux.

#### Filtre de téléchargement

Sont inclus dans le téléchargement (puis filtrés localement) :

```
footway | path | pedestrian | steps | living_street
residential | service | unclassified | tertiary | secondary | primary | platform
```

Sont **exclus d'emblée** : `motorway`, `trunk` et leurs liens, `construction`, `proposed`.

#### Classification PRIORITAIRE / SECONDAIRE

**PRIORITAIRE** (`walk_priority.geojson`) — infrastructure dédiée ou fortement favorable :

| Critère OSM | Explication |
|---|---|
| `highway=footway` | Chemin piéton dédié |
| `highway=pedestrian` | Zone piétonne |
| `highway=steps` | Escaliers |
| `highway=living_street` | Zone de rencontre (véhicules limités à l'allure du pas) |
| `highway=path` | Chemin générique (autorisé sauf interdiction explicite `foot=no`) |
| Route locale + `sidewalk=both/left/right/yes` | Route avec trottoir explicitement cartographié |

**SECONDAIRE** (`walk_secondary.geojson`) — routes locales praticables sans aménagement dédié :

| Critère OSM | Explication |
|---|---|
| `highway=residential` | Rue résidentielle |
| `highway=service` | Voie de service (parking, accès) |
| `highway=unclassified` | Route non classifiée |
| `highway=tertiary` | Route tertiaire |
| … sans trottoir explicite | Pas de `sidewalk` renseigné, mais `foot` non interdit |

> La logique implicite : sur une rue résidentielle non taguée, on suppose que la marche est permise (`ASSUME_FOOT_OK_ON_LOCAL = True`). Un tag `foot=no` ou `access=no` exclut le tronçon.

**Fichiers de sortie :**

| Fichier | Contenu |
|---|---|
| `walk_priority.geojson` | Tronçons prioritaires |
| `walk_secondary.geojson` | Tronçons secondaires |
| `walk_all.geojson` | Union des deux (`tier` = `priority` ou `secondary`) |

---

### `fetch_platform_simplified.py` — Plateformes et arrêts TC

Le script récupère tous les objets OSM liés aux arrêts et plateformes de transport en commun :

| Tag OSM | Signification |
|---|---|
| `highway=platform` | Plateforme le long d'une route |
| `highway=bus_stop` | Arrêt de bus (point) |
| `public_transport=platform` | Quai générique (point, ligne ou polygone) |
| `railway=platform` | Quai ferroviaire ou tramway |
| `amenity=bus_station` | Gare routière |

Tous les attributs OSM présents sont conservés tels quels. Toutes les géométries (points, lignes, polygones) sont incluses.

---

## Format de sortie

Tous les scripts exportent uniquement en **GeoJSON** (`.geojson`), en **WGS 84 (EPSG:4326)** (coordonnées latitude/longitude décimales).

Le format GeoJSON est directement visualisable dans QGIS, Kepler.gl, et l'extension VSCode *Geo Data Viewer*.

---

## Modifier la zone d'étude

Dans chaque script, modifier la liste `places` :

```python
places = [
    "Carouge, Switzerland",
    "Lancy, Switzerland",
    "Thônex, Switzerland",
    "Saint-Julien-en-Genevois, France",
]
```

Chaque nom est géocodé par OSMnx via Nominatim (le moteur de recherche d'OSM). Il faut que le nom soit reconnu — tester sur [nominatim.openstreetmap.org](https://nominatim.openstreetmap.org) en cas de doute.

> Le cache OSMnx est stocké dans `~/.cache/osmnx/` par défaut. Pour forcer un nouveau téléchargement, supprimer ce dossier ou passer `ox.settings.use_cache = False`.

---

## Ressources OSM utiles

- [Wiki OSM — Highway tag](https://wiki.openstreetmap.org/wiki/Key:highway) : liste complète de toutes les valeurs
- [Wiki OSM — Cycleway](https://wiki.openstreetmap.org/wiki/Key:cycleway) : aménagements cyclables sur chaussée
- [Wiki OSM — Sidewalk](https://wiki.openstreetmap.org/wiki/Key:sidewalk) : cartographie des trottoirs
- [Wiki OSM — Foot](https://wiki.openstreetmap.org/wiki/Key:foot) : autorisation piétonne
- [Overpass Turbo](https://overpass-turbo.eu) : tester des requêtes OSM directement dans le navigateur
- [OSMnx documentation](https://osmnx.readthedocs.io) : bibliothèque Python utilisée pour les requêtes
