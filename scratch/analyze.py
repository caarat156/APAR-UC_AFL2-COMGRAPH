import json
from pathlib import Path
from shapely.geometry import shape, LineString
from shapely.ops import unary_union, nearest_points

ROOT = Path(__file__).resolve().parent.parent
for f in ['LT_1', 'LT_2', 'LT_2A', 'LT_3', 'LT_4', 'LT_5', 'LT_6', 'LT_7']:
    gj = json.loads((ROOT / 'data' / f'{f}.geojson').read_text(encoding='utf-8'))
    rooms = {x['properties']['code']: shape(x['geometry']) for x in gj['features'] if x['properties']['type'] == 'room'}
    cors = [shape(x['geometry']) for x in gj['features'] if x['properties']['type'] == 'corridor']
    ru = unary_union(list(rooms.values()))
    inside = sum(c.intersection(ru).length for c in cors)
    print(f, 'corridor px inside rooms:', round(inside, 1))
    if not cors:
        continue
    net = unary_union(cors)
    bad = []
    for code, g in rooms.items():
        a, b = nearest_points(g.boundary, net)
        conn = LineString([a, b])
        others = unary_union([r for c, r in rooms.items() if c != code])
        cross = conn.intersection(others).length
        if cross > 2:
            bad.append((code, round(conn.length), round(cross)))
    print('  rooms whose direct door-connector crosses other rooms:', len(bad), '/', len(rooms))
    print('  ', bad)
