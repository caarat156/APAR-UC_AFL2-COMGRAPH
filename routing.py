"""Routing jalan kaki APAR berbasis jaringan koridor (tanpa menembus tembok).

Alur Algoritma (Computational Geometry + Graph Theory):
1. Noding koridor: Memotong garis koridor di persimpangan -> graf koridor (NetworkX).
2. Pintu ruangan: Mencari titik dinding ruangan terdekat ke koridor tanpa menembus kamar lain.
3. Ruangan baris dalam (Lantai 3): Membuka akses lewat ruangan tetangga yang berbagi dinding.
4. Rute terpendek: Dihitung dengan algoritma Dijkstra berdasarkan jarak fisik nyata (Real Walking Distance).
"""
import json
import math
import re
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points, unary_union

# ==========================================
# KONSTANTA KALIBRASI GEOMETRI (SATUAN PIKSEL)
# ==========================================
STEP_PX = 8.0        # Jarak sampling titik kandidat pintu di sekeliling dinding ruangan
TOL_CROSS_PX = 1.5   # Toleransi floating-point agar garis yang menempel dinding tidak dianggap menembus
SHARED_MIN_PX = 6.0  # Panjang minimum dinding bersama agar 2 ruangan diakui saling bertetangga
APAR_OWNER_PX = 6.0  # Jarak maksimum titik APAR ke dinding agar dianggap milik ruangan tersebut


def load_floor_file(path):
    """
    Fungsi: Membaca file GeoJSON lantai dan memilah fiturnya ke objek geometri Shapely.
    Input : path (lokasi file .geojson)
    Output: Dictionary berisi footprint gedung, list rooms, list corridors, through, dan apar.
    """
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    res = {"footprint": None, "rooms": [], "corridors": [], "through": [], "apar": []}
    for feat in gj["features"]:
        geom, props = shape(feat["geometry"]), feat["properties"]
        kind = props["type"]
        if kind == "room":
            res["rooms"].append({"code": props["code"], "name": props["name"], "geom": geom})
        elif kind == "corridor":
            res["corridors"].append(geom)
            res["through"].extend(props.get("through", []))
        elif kind == "APAR":
            res["apar"].append({"id": props.get("id", "APAR"), "geom": geom})
        elif kind == "footprint":
            res["footprint"] = geom
    return res


def natural_key(code):
    """
    Fungsi: Menghasilkan kunci pengurutan natural untuk kode ruangan (misal: '113a' -> ['', 113, 'a']).
    Tujuan: Supaya urutan di dropdown manusiawi (101, 102, ... 113, 113a, 201), bukan alfabetik mentah.
    """
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(code))]


class FloorNav:
    """
    Kelas Navigasi Spasial: Membangun Graf Jaringan Jalan Lantai dan Menghitung Rute Dijkstra.
    Format Simpul Node:
      - ("R", code)            : Simpul titik tengah ruangan (Centroid)
      - ("N", x, y)            : Simpul persimpangan/belokan koridor
      - ("D", code)            : Simpul pintu keluar ruangan ke koridor
      - ("S", codeA, codeB)    : Simpul pintu tembus antar-kamar tetangga
      - ("A", apar_id)         : Simpul posisi APAR
    """

    def __init__(self, data):
        """
        Inisialisasi Graf:
        1. Buat node centroid tiap ruangan (R).
        2. Bangun jaringan koridor (N) dari LineString.
        3. Tentukan titik pintu tiap ruangan (D).
        4. Buka akses ruangan baris dalam lewat dinding bersama (S).
        5. Pasang titik APAR (A) ke dalam jaringan graf.
        """
        self.rooms = {r["code"]: r["geom"] for r in data["rooms"]}
        self.through = set(data.get("through", []))
        self.G = nx.Graph()
        self.pos = {}
        self.owner = {}
        self.door_via = {}
        lines = data["corridors"]
        self.net = unary_union(lines) if lines else None
        self.centroid = {}

        # 1. Daftarkan titik tengah tiap ruangan (utamakan centroid, fallback representative_point)
        for code, g in self.rooms.items():
            c = g.centroid if g.contains(g.centroid) else g.representative_point()
            self.centroid[code] = (c.x, c.y)
            self._node(("R", code), self.centroid[code], {code})

        # 2. Bangun graf koridor dan sambungkan ruangan jika data koridor tersedia
        if self.net is not None and not self.net.is_empty:
            self._build_network()     # Bentuk jalan koridor
            for code in self.rooms:
                self._connect_room(code)  # Pasang pintu tiap kamar
            self._link_neighbors()    # Buka akses kamar baris dalam
        
        # 3. Tempelkan seluruh titik APAR ke graf
        self.apar = {}
        for a in data["apar"]:
            self._add_apar(a["id"], a["geom"])

    def _node(self, nid, xy, owners=()):
        """
        Fungsi: Mendaftarkan simpul (Node) baru ke dalam Graf NetworkX.
        Parameter:
          - nid   : ID unik simpul (berupa tuple, misal: ('R', '101'))
          - xy    : Koordinat fisik (x, y) dalam piksel
          - owners: Set kode ruangan pemilik simpul (jika ada)
        """
        if nid not in self.pos:
            self.pos[nid] = (float(xy[0]), float(xy[1]))
            self.owner[nid] = set(owners)
            self.G.add_node(nid)
        return nid

    def _edge(self, u, v, net=False):
        """
        Fungsi: Menghubungkan dua simpul (u dan v) dengan garis edge berbobot jarak fisik.
        Parameter:
          - net: True jika edge ini merupakan jalur umum koridor utama.
        """
        if u != v:
            self.G.add_edge(u, v, weight=math.dist(self.pos[u], self.pos[v]), net=net)

    def _build_network(self):
        """
        Fungsi: Noding Koridor -> Mengubah garis koridor bersilangan menjadi simpul graf.
        Menggunakan unary_union untuk memecah persimpangan lorong, lalu memasang node N di tiap ujungnya.
        """
        noded = unary_union(self.net)
        for g in getattr(noded, "geoms", [noded]):
            coords = list(g.coords)
            for p1, p2 in zip(coords[:-1], coords[1:]):
                n1 = self._node(("N", round(p1[0], 2), round(p1[1], 2)), p1)
                n2 = self._node(("N", round(p2[0], 2), round(p2[1], 2)), p2)
                self._edge(n1, n2, net=True)

    def _attach(self, xy):
        """
        Fungsi: Edge Split Dinamis.
        Menyisipkan titik koordinat (xy) ke tengah-tengah segmen koridor terdekat.
        Garis lama (u-v) dihapus, lalu disisipkan node baru (u - nid - v) agar rute tidak memutar ke ujung lorong.
        """
        p = Point(xy)
        best = min(
            ((LineString([self.pos[u], self.pos[v]]).distance(p), u, v, LineString([self.pos[u], self.pos[v]]))
             for u, v, d in self.G.edges(data=True) if d.get("net")),
            key=lambda t: t[0]
        )
        _, u, v, seg = best
        q = seg.interpolate(seg.project(p))
        for n in (u, v):
            if math.dist(self.pos[n], (q.x, q.y)) < 0.01:
                return n
        nid = ("N", round(q.x, 2), round(q.y, 2))
        if nid not in self.pos:
            self._node(nid, (q.x, q.y))
            self.G.remove_edge(u, v)
            self._edge(u, nid, net=True)
            self._edge(nid, v, net=True)
        return nid

    def _blockers(self, exclude):
        """
        Fungsi: Mengumpulkan semua poligon ruangan lain sebagai objek penghalang fisik (tembok).
        Ruangan sendiri di-exclude karena sinar pintu berawal dari ruangan tersebut.
        """
        geoms = [g for c, g in self.rooms.items() if c not in self.through and c not in exclude]
        return unary_union(geoms) if geoms else None

    def _valid(self, a, b, blockers):
        """
        Fungsi: Memeriksa apakah garis lurus a -> b menabrak ruangan orang lain (blockers).
        Return: True jika jalur bebas halangan / tidak menembus dinding ruangan lain.
        """
        if blockers is None or math.dist(a, b) < 1e-6:
            return True
        return LineString([a, b]).intersection(blockers).length <= TOL_CROSS_PX

    def _connect_room(self, code):
        """
        Fungsi: Menemukan pintu keluar ruangan ke koridor terdekat secara otomatis.
        1. Jika ruangan dilewati koridor langsung (lobby/aula), hubungkan centroid langsung ke koridor.
        2. Jika tidak, cacah dinding ruangan tiap 8 px, cari titik terdekat ke koridor yang lolos _valid().
        3. Sambungkan: Centroid Kamar (R) -> Pintu (D) -> Koridor (N).
        """
        geom, cen, rid = self.rooms[code], self.centroid[code], ("R", code)
        if self.net.intersection(geom).length > TOL_CROSS_PX:
            q = nearest_points(self.net, Point(cen))[0]
            self._edge(rid, self._attach((q.x, q.y)))
            self.door_via[code] = "koridor"
            return
        blockers, ext = self._blockers({code}), geom.exterior
        n = max(int(ext.length // STEP_PX), 8)
        cands = []
        for i in range(n):
            pt = ext.interpolate(i * ext.length / n)
            q = nearest_points(self.net, pt)[0]
            cands.append((pt.distance(q), (pt.x, pt.y), (q.x, q.y)))
        cands.sort(key=lambda t: t[0])
        for _, a, b in cands:
            if self._valid(a, b, blockers):
                did = self._node(("D", code), a, {code})
                self._edge(rid, did)
                self._edge(did, self._attach(b))
                self.door_via[code] = "koridor"
                return
        self.door_via[code] = None

    def _link_neighbors(self):
        """
        Fungsi: Menghubungkan ruangan baris dalam yang tidak menyentuh koridor (kasus Lantai 3).
        Mencari dinding bersama antar dua kamar tetangga, lalu membuat pintu tembus (S) di tengah dinding tersebut.
        """
        for code, geom in self.rooms.items():
            if self.door_via.get(code) is not None:
                continue
            for other, og in self.rooms.items():
                if other == code:
                    continue
                shared = geom.boundary.intersection(og.boundary)
                if not shared.is_empty and shared.length >= SHARED_MIN_PX:
                    parts = [p for p in getattr(shared, "geoms", [shared]) if p.length > 0]
                    if parts:
                        mid = max(parts, key=lambda p: p.length).interpolate(0.5, normalized=True)
                        sid = self._node(("S",) + tuple(sorted((code, other))), (mid.x, mid.y), {code, other})
                        self._edge(("R", code), sid)
                        self._edge(sid, ("R", other))
                        if self.door_via[code] is None:
                            self.door_via[code] = "tetangga"

    def _add_apar(self, aid, geom):
        """
        Fungsi: Memasang titik APAR ke dalam jaringan graf.
        - Jika APAR ada di dalam ruangan, hubungkan ke centroid ruangan tersebut.
        - Jika APAR ada di dinding lorong, hubungkan ke koridor terdekat via _attach().
        """
        xy, nid = (geom.x, geom.y), self._node(("A", aid), (geom.x, geom.y))
        self.apar[aid] = nid
        owners = {c for c, g in self.rooms.items() if g.distance(geom) <= APAR_OWNER_PX}
        self.owner[nid] = set(owners)
        for c in owners:
            self._edge(nid, ("R", c))
        if self.net is None or self.net.is_empty:
            return
        near_wall = (not owners) or any(g.exterior.distance(geom) <= APAR_OWNER_PX for c, g in self.rooms.items() if c in owners)
        q = nearest_points(self.net, geom)[0]
        if near_wall and (self._valid(xy, (q.x, q.y), self._blockers(owners)) or not owners):
            self._edge(nid, self._attach((q.x, q.y)))

    def route(self, code, apars):
        """
        Fungsi: Menjalankan Algoritma Dijkstra dari ruangan sumber kebakaran ke seluruh APAR.
        Output: List APAR terurut dari jarak jalan terpendek (walk_px) lengkap dengan koordinat belokan rute (route).
        """
        src = ("R", code)
        dist, paths = nx.single_source_dijkstra(self.G, src, weight="weight")
        out = []
        for a in apars:
            nid = self.apar.get(a["id"])
            if nid in dist:
                out.append({
                    "id": a["id"],
                    "apar_pt": a["geom"],
                    "walk_px": dist[nid],
                    "route": [self.pos[n] for n in paths[nid]]
                })
        out.sort(key=lambda r: r["walk_px"])
        return out
