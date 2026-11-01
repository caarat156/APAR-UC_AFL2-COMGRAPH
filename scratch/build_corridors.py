"""Bangun jaringan koridor (LineString multi-titik) per lantai dan tulis ke data/LT_x.geojson.

Koordinat = piksel denah asli (x kanan, y bawah). Koridor digambar manual dari denah di data/sumber.
`through` = ruangan terbuka (lobby/aula/perpustakaan) yang boleh dilewati koridor.
Skrip memvalidasi bahwa koridor tidak memotong ruangan lain (tembok).
"""
import json
from pathlib import Path

from shapely.geometry import LineString, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# floor -> list of (polyline, through_rooms)
CORRIDORS = {
    "LT_1": [
        ([(62, 340), (660, 340), (845, 340), (905, 340), (975, 340)], []),
        ([(845, 340), (845, 165)], []),
        ([(905, 340), (905, 466)], []),
        ([(975, 340), (1125, 340), (1190, 340), (1255, 340)], ["106"]),
    ],
    "LT_2": [
        ([(90, 346), (1550, 346)], "AUTO"),
    ],
    "LT_2A": [
        ([(80, 350), (1530, 350)], "AUTO"),
    ],
    "LT_3": [
        ([(60, 362), (1520, 362)], []),
        ([(832, 362), (832, 1050)], []),
    ],
    "LT_4": [
        ([(70, 378), (1540, 378)], []),
        ([(858, 378), (858, 1050)], []),
    ],
    "LT_5": [
        ([(70, 350), (1540, 350)], []),
        ([(858, 350), (858, 1040)], []),
    ],
    "LT_6": [
        ([(70, 385), (1540, 385)], []),
        ([(858, 385), (858, 1050)], []),
        # sayap kiri: koridor antara deret 616a-619a (bawah) dan 616b-619b (atas)
        ([(130, 385), (130, 290), (632, 290), (632, 385)], []),
    ],
    "LT_7": [
        ([(70, 360), (668, 360), (900, 360)], ["PREF"]),
        ([(858, 360), (858, 782)], ["PREF"]),
        ([(858, 782), (858, 1050)], ["703-704"]),
        ([(900, 360), (900, 405), (1215, 405), (1300, 405)], ["PREF", "711"]),
    ],
}


def build(write=True):
    for floor, lines in CORRIDORS.items():
        path = DATA / f"{floor}.geojson"
        gj = json.loads(path.read_text(encoding="utf-8"))
        rooms = {
            f["properties"]["code"]: shape(f["geometry"])
            for f in gj["features"] if f["properties"]["type"] == "room"
        }
        new_feats = []
        for i, (pts, through) in enumerate(lines, 1):
            ls = LineString(pts)
            crossed = {c: round(ls.intersection(g).length, 1) for c, g in rooms.items() if ls.intersection(g).length > 2}
            if through == "AUTO":
                through = sorted(crossed)
            bad = {c: l for c, l in crossed.items() if c not in through}
            status = "OK" if not bad else f"MENEMBUS {bad}"
            print(f"{floor} COR-{i:02d} len={ls.length:.0f}px through={through} -> {status}")
            new_feats.append({
                "type": "Feature",
                "properties": {"floor": floor, "type": "corridor", "id": f"{floor}-COR-{i:02d}", "through": list(through)},
                "geometry": {"type": "LineString", "coordinates": [[float(x), float(y)] for x, y in pts]},
            })
        if write:
            gj["features"] = [f for f in gj["features"] if f["properties"]["type"] != "corridor"] + new_feats
            path.write_text(json.dumps(gj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    build(write="--dry" not in sys.argv)
