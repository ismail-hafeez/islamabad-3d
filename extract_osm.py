# extract_osm.py
# pip install osmnx geopandas shapely pyproj
import json, re
import osmnx as ox
from pyproj import Transformer
from shapely.ops import transform
import time

def retry(fn, *a, tries=5, **kw):
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            wait = 15 * 2 ** i
            print(f"Failed ({type(e).__name__}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Overpass still unavailable")

# ---- EDIT THESE ----
ADDRESS = "44, F-6/1, Islamabad, Pakistan"
CENTER = None      # or set (lat, lon) to skip geocoding, e.g. (33.6844, 73.0479)
DIST = 150       # radius in meters
OUT = "street.json"
# --------------------

center = CENTER or ox.geocode(ADDRESS)
print("Center:", center)

G = retry(ox.graph_from_point, center, dist=DIST, network_type="all")
b = retry(ox.features_from_point, center, {"building": True}, dist=DIST)
poi = retry(ox.features_from_point, center, dist=DIST)

# Project lat/lon -> meters (UTM 43N), then shift so center = (0, 0)
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
cx, cy = to_utm.transform(center[1], center[0])

def proj(geom):
    return transform(lambda x, y, z=None: tuple(
        a - b for a, b in zip(to_utm.transform(x, y), (cx, cy))), geom)

def pts(coords):
    # Godot is Y-up with north = -Z, so z = -northing
    return [[round(x, 2), round(-y, 2)] for x, y in coords]

def num(v):
    m = re.search(r"[\d.]+", str(v)) if v is not None else None
    return float(m.group()) if m else None

# Buildings
b = retry(ox.features_from_point, center, {"building": True}, dist=DIST)
buildings = []
for _, r in b.iterrows():
    g = r.geometry
    if g is None or g.geom_type not in ("Polygon", "MultiPolygon"):
        continue
    g = proj(g)
    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    h = num(r.get("height"))
    if h is None:
        lv = num(r.get("building:levels"))
        h = lv * 3 if lv else 8.0
    for p in polys:
        buildings.append({
            "name": r.get("name") if isinstance(r.get("name"), str) else None,
            "height": h,
            "footprint": pts(list(p.exterior.coords)[:-1]),
        })

# Roads
G = retry(ox.graph_from_point, center, dist=DIST, network_type="all")
edges = retry(ox.graph_to_gdfs, G, nodes=False)
WIDTH = {"motorway": 14, "trunk": 14, "primary": 12, "secondary": 10,
         "tertiary": 8, "residential": 7, "service": 4,
         "footway": 2, "path": 2, "pedestrian": 3}
roads = []
for _, r in edges.iterrows():
    hw = r["highway"][0] if isinstance(r["highway"], list) else r["highway"]
    roads.append({
        "type": hw,
        "width": WIDTH.get(hw, 6),
        "name": r.get("name") if isinstance(r.get("name"), str) else None,
        "line": pts(proj(r.geometry).coords),
    })

# Landmarks / points of interest
tags = {"amenity": True, "tourism": True, "historic": True, "leisure": True}
poi = retry(ox.features_from_point, center, tags, dist=DIST)
landmarks = []
for _, r in poi.iterrows():
    g = proj(r.geometry.centroid)
    kind = next((r[k] for k in tags if isinstance(r.get(k), str)), None)
    landmarks.append({
        "name": r.get("name") if isinstance(r.get("name"), str) else None,
        "kind": kind,
        "pos": pts([(g.x, g.y)])[0],
    })

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"center": center, "buildings": buildings,
               "roads": roads, "landmarks": landmarks}, f)

print(f"{len(buildings)} buildings, {len(roads)} road segments, "
      f"{len(landmarks)} landmarks -> {OUT}")