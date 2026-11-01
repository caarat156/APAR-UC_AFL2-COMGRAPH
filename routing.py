"""Routing jalan kaki APAR berbasis jaringan koridor (tanpa menembus tembok).

Ide utama (Computational Geometry + Graph):
1. Koridor (LineString multi-titik) di-"noding" pada persimpangan -> graph jalan.
2. Tiap ruangan punya *pintu*: titik di batas ruangan yang terhubung ke koridor lewat garis
   penghubung yang TIDAK memotong ruangan lain. Titik dipilih dari sampling batas ruangan.
3. Ruangan yang tidak menyentuh koridor (garis penghubung selalu menembus ruangan lain) boleh
   dilewati lewat ruangan tetangga yang berbagi dinding (titik "pintu" antar-ruangan).
4. Titik pintu & APAR disisipkan ke tengah segmen koridor (edge split), bukan ke node terdekat,
   sehingga rute tidak memutar ke ujung koridor.
5. Jarak jalan kaki = Dijkstra (networkx); jarak Euclidean dihitung terpisah sebagai pembanding.
"""
import json
import math
import re
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, unary_union

STEP_PX = 8.0        # jarak sampling kandidat pintu di batas ruangan
TOL_CROSS_PX = 1.5   # toleransi panjang garis yang boleh "menyentuh" ruangan lain
SHARED_MIN_PX = 6.0  # panjang dinding bersama minimum agar dua ruangan dianggap bertetangga
APAR_OWNER_PX = 6.0  # APAR dianggap milik ruangan jika jaraknya <= ini


def load_floor_file(path):
    """Baca satu file GeoJSON lantai menjadi dict geometri Shapely."""
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    result = {"footprint": None, "rooms": [], "corridors": [], "through": [], "apar": [], "hydrant": []}
    for feat in gj["features"]:
        geom = shape(feat["geometry"])
        props = feat["properties"]
        kind = props["type"]
        if kind == "footprint":
            result["footprint"] = geom
        elif kind == "room":
            result["rooms"].append({
                "code": props["code"],
                "name": props["name"],
                "geom": geom,
                "area_m2": props.get("area_m2", 0.0),
            })
        elif kind == "corridor":
            result["corridors"].append(geom)
            result["through"].extend(props.get("through", []))
        elif kind == "APAR":
            result["apar"].append({
                "id": props.get("id", "APAR"),
                "geom": geom,
                "inside": props.get("inside_building", True),
            })
        elif kind == "Hydrant":
            result["hydrant"].append({"id": props.get("id", "Hydrant"), "geom": geom})
    return result


def natural_key(code):
    """Kunci urut natural: 101, 102, 107, 107A, 113, 113a, 113b, 231-232, ... lalu kode huruf."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(code))]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class FloorNav:
    def __init__(self, data):
        self.rooms = {r["code"]: r["geom"] for r in data["rooms"]}
        self.through = set(data.get("through", []))
        self.G = nx.Graph()
        self.pos = {}
        self.owner = {}
        self.door_via = {}  # code -> "koridor" | "tetangga" | None
        lines = data["corridors"]
        self.net = unary_union(lines) if lines else None
        self.centroid = {}
        for code, g in self.rooms.items():
            c = g.centroid
            if not g.contains(c):
                c = g.representative_point()
            self.centroid[code] = (c.x, c.y)
            self._node(("R", code), self.centroid[code], {code})
        if self.net is not None and not self.net.is_empty:
            self._build_network()
            for code in self.rooms:
                self._connect_room(code)
            self._link_neighbors()
        self.apar = {}
        for a in data["apar"]:
            self._add_apar(a["id"], a["geom"])

    # ---------- graph helpers ----------
    def _node(self, nid, xy, owners=()):
        if nid not in self.pos:
            self.pos[nid] = (float(xy[0]), float(xy[1]))
            self.owner[nid] = set(owners)
            self.G.add_node(nid)
        return nid

    def _edge(self, u, v, net=False):
        w = _dist(self.pos[u], self.pos[v])
        if u != v:
            self.G.add_edge(u, v, weight=w, net=net)

    def _build_network(self):
        noded = unary_union(self.net)
        for g in getattr(noded, "geoms", [noded]):
            coords = list(g.coords)
            for p1, p2 in zip(coords[:-1], coords[1:]):
                n1 = self._node(("N", round(p1[0], 2), round(p1[1], 2)), p1)
                n2 = self._node(("N", round(p2[0], 2), round(p2[1], 2)), p2)
                self._edge(n1, n2, net=True)

    def _attach(self, xy):
        """Sisipkan titik proyeksi xy ke segmen koridor terdekat (edge split)."""
        p = Point(xy)
        best = None
        for u, v, d in self.G.edges(data=True):
            if not d.get("net"):
                continue
            seg = LineString([self.pos[u], self.pos[v]])
            dist = seg.distance(p)
            if best is None or dist < best[0]:
                best = (dist, u, v, seg)
        _, u, v, seg = best
        q = seg.interpolate(seg.project(p))
        for n in (u, v):
            if _dist(self.pos[n], (q.x, q.y)) < 0.01:
                return n
        nid = ("N", round(q.x, 2), round(q.y, 2))
        if nid not in self.pos:
            self._node(nid, (q.x, q.y))
            self.G.remove_edge(u, v)
            self._edge(u, nid, net=True)
            self._edge(nid, v, net=True)
        return nid

    # ---------- door / connector ----------
    def _blockers(self, exclude):
        geoms = [g for c, g in self.rooms.items() if c not in self.through and c not in exclude]
        return unary_union(geoms) if geoms else None

    def _valid(self, a, b, blockers):
        if blockers is None:
            return True
        conn = LineString([a, b])
        if conn.length < 1e-6:
            return True
        return conn.intersection(blockers).length <= TOL_CROSS_PX

    def _connect_room(self, code):
        geom = self.rooms[code]
        cen = self.centroid[code]
        rid = ("R", code)
        # ruangan yang dilintasi koridor (lobby/aula): hubungkan dari centroid ke koridor terdekat
        if self.net.intersection(geom).length > TOL_CROSS_PX:
            q = nearest_points(self.net, Point(cen))[0]
            nid = self._attach((q.x, q.y))
            self._edge(rid, nid)
            self.door_via[code] = "koridor"
            return
        blockers = self._blockers({code})
        ext = geom.exterior
        n = max(int(ext.length // STEP_PX), 8)
        cands = []
        for i in range(n):
            pt = ext.interpolate(i * ext.length / n)
            q = nearest_points(self.net, pt)[0]
            cands.append((pt.distance(q), (pt.x, pt.y), (q.x, q.y)))
        cands.sort(key=lambda t: t[0])
        for d, a, b in cands:
            if self._valid(a, b, blockers):
                did = self._node(("D", code), a, {code})
                self._edge(rid, did)
                self._edge(did, self._attach(b))
                self.door_via[code] = "koridor"
                return
        self.door_via[code] = None

    def _link_neighbors(self):
        """Ruangan tanpa akses koridor langsung -> boleh lewat ruangan tetangga (dinding bersama)."""
        for code, geom in self.rooms.items():
            if self.door_via.get(code) is not None:
                continue
            for other, og in self.rooms.items():
                if other == code:
                    continue
                shared = geom.boundary.intersection(og.boundary)
                if shared.is_empty or shared.length < SHARED_MIN_PX:
                    continue
                parts = [p for p in getattr(shared, "geoms", [shared]) if p.length > 0]
                if not parts:
                    continue
                mid = max(parts, key=lambda p: p.length).interpolate(0.5, normalized=True)
                sid = self._node(("S",) + tuple(sorted((code, other))), (mid.x, mid.y), {code, other})
                self._edge(("R", code), sid)
                self._edge(sid, ("R", other))
                if self.door_via[code] is None:
                    self.door_via[code] = "tetangga"

    def _add_apar(self, aid, geom):
        xy = (geom.x, geom.y)
        nid = self._node(("A", aid), xy)
        self.apar[aid] = nid
        owners = {c for c, g in self.rooms.items() if g.distance(geom) <= APAR_OWNER_PX}
        self.owner[nid] = set(owners)
        for c in owners:
            self._edge(nid, ("R", c))
        if self.net is None or self.net.is_empty:
            return
        blockers = self._blockers(owners)
        # APAR di dalam ruangan (bukan di dinding) tidak boleh menembus dinding ke koridor
        near_wall = (not owners) or any(
            g.exterior.distance(geom) <= APAR_OWNER_PX for c, g in self.rooms.items() if c in owners
        )
        q = nearest_points(self.net, geom)[0]
        if near_wall and (self._valid(xy, (q.x, q.y), blockers) or not owners):
            self._edge(nid, self._attach((q.x, q.y)))

    # ---------- query ----------
    def route(self, code, apars):
        """Kembalikan list hasil per APAR (urut jarak jalan terdekat)."""
        src = ("R", code)
        dist, paths = nx.single_source_dijkstra(self.G, src, weight="weight")
        cen = Point(self.centroid[code])
        out = []
        for a in apars:
            nid = self.apar.get(a["id"])
            euc = cen.distance(a["geom"])
            if nid in dist:
                coords = [self.pos[n] for n in paths[nid]]
                out.append({"id": a["id"], "apar_pt": a["geom"], "walk_px": dist[nid],
                            "euc_px": euc, "route": coords, "nodes": paths[nid]})
        out.sort(key=lambda r: r["walk_px"])
        return out

    def violations(self, nodes):
        """Daftar ruangan terlarang yang ditembus jalur (kosong = tidak ada tembok yang ditembus)."""
        bad = []
        for u, v in zip(nodes[:-1], nodes[1:]):
            seg = LineString([self.pos[u], self.pos[v]])
            allowed = self.owner.get(u, set()) | self.owner.get(v, set()) | self.through
            for c, g in self.rooms.items():
                if c not in allowed and seg.intersection(g).length > TOL_CROSS_PX:
                    bad.append((c, u, v))
        return bad
