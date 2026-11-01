import json
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import streamlit as st
from shapely.geometry import Point, LineString, shape
from shapely.ops import nearest_points, unary_union

DATA_DIR = Path(__file__).resolve().parent / "data"
FLOORS = ["LT_1", "LT_2", "LT_2A", "LT_3", "LT_4", "LT_5", "LT_6", "LT_7"]
PX_PER_M = 15.0  # Skala: 15 piksel = 1 meter


@st.cache_data
def load_floor(floor):
    gj = json.loads((DATA_DIR / f"{floor}.geojson").read_text(encoding="utf-8"))
    result = {
        "footprint": None,
        "rooms": [],
        "corridors": [],
        "apar": [],
        "hydrant": []
    }
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
                "area_m2": props.get("area_m2", 0.0)
            })
        elif kind == "corridor":
            result["corridors"].append(geom)
        elif kind == "APAR":
            result["apar"].append({
                "id": props.get("id", "APAR"),
                "geom": geom,
                "inside": props.get("inside_building", True)
            })
        elif kind == "Hydrant":
            result["hydrant"].append({
                "id": props.get("id", "Hydrant"),
                "geom": geom
            })
    return result


def build_corridor_graph(corridor_lines):
    G = nx.Graph()
    if not corridor_lines:
        return G

    for line in corridor_lines:
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            p1, p2 = coords[i], coords[i + 1]
            dist = Point(p1).distance(Point(p2))
            G.add_edge(p1, p2, weight=dist)

    # Hubungkan persimpangan jika ada garis koridor yang berpotongan
    for i in range(len(corridor_lines)):
        for j in range(i + 1, len(corridor_lines)):
            l1, l2 = corridor_lines[i], corridor_lines[j]
            inter = l1.intersection(l2)
            if not inter.is_empty and inter.geom_type == "Point":
                ip = (inter.x, inter.y)
                for l in (l1, l2):
                    c = list(l.coords)
                    p1, p2 = c[0], c[-1]
                    d1 = Point(ip).distance(Point(p1))
                    d2 = Point(ip).distance(Point(p2))
                    G.add_edge(ip, p1, weight=d1)
                    G.add_edge(ip, p2, weight=d2)
    return G


def compute_corridor_route(graph, corridor_union, pt_start, pt_end):
    """
    Menghitung rute koridor (real walking distance) dari pt_start ke pt_end.
    Trik Computational Geometry:
    1. Proyeksikan pt_start dan pt_end ke titik terdekat di sumbu koridor.
    2. Hubungkan ke Graph, cari Shortest Path dengan Dijkstra (networkx).
    3. Kembalikan rute lengkap: Start -> Entry -> Jalur Koridor -> Exit -> End.
    """
    if corridor_union.is_empty or graph.number_of_nodes() == 0:
        # Fallback garis lurus jika tidak ada koridor
        line = LineString([pt_start, pt_end])
        return [pt_start, pt_end], line.length

    # 1. Proyeksi titik ke koridor
    proj_start = nearest_points(corridor_union, pt_start)[0]
    proj_end = nearest_points(corridor_union, pt_end)[0]

    node_start = (proj_start.x, proj_start.y)
    node_end = (proj_end.x, proj_end.y)

    H = graph.copy()

    # Hubungkan node_start ke node terdekat di graph
    nodes = list(graph.nodes)
    closest_start = min(nodes, key=lambda n: Point(n).distance(proj_start))
    H.add_edge(node_start, closest_start, weight=Point(node_start).distance(Point(closest_start)))

    # Hubungkan node_end ke node terdekat di graph
    closest_end = min(nodes, key=lambda n: Point(n).distance(proj_end))
    H.add_edge(node_end, closest_end, weight=Point(node_end).distance(Point(closest_end)))

    try:
        path_nodes = nx.shortest_path(H, source=node_start, target=node_end, weight="weight")
        corridor_len = nx.shortest_path_length(H, source=node_start, target=node_end, weight="weight")
        
        # Jarak total = (start -> pintu/koridor) + (jalan koridor) + (koridor -> APAR)
        d_in = pt_start.distance(proj_start)
        d_out = proj_end.distance(pt_end)
        total_px = d_in + corridor_len + d_out
        full_coords = [(pt_start.x, pt_start.y)] + path_nodes + [(pt_end.x, pt_end.y)]
        return full_coords, total_px
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        line = LineString([pt_start, pt_end])
        return [pt_start, pt_end], line.length


def plot_polygon(ax, geom, **kwargs):
    for poly in getattr(geom, "geoms", [geom]):
        x, y = poly.exterior.xy
        ax.fill(x, y, **kwargs)


def render_map(data, selected_room=None, route_coords=None, buffer_union=None, covered_rooms=None):
    fig, ax = plt.subplots(figsize=(14, 9))

    # 1. Gambar Batas Gedung (Footprint)
    if data["footprint"]:
        plot_polygon(ax, data["footprint"], facecolor="#f5f5f7", edgecolor="#222222", linewidth=2.5)

    # 2. Gambar Koridor
    for line in data["corridors"]:
        lx, ly = line.xy
        ax.plot(lx, ly, color="#d0d0d5", linewidth=3.5, linestyle="--", zorder=1)

    # 3. Buffer Lingkaran 15 Meter (Analisis Jangkauan)
    if buffer_union is not None and not buffer_union.is_empty:
        plot_polygon(ax, buffer_union, facecolor="#00bcd4", alpha=0.22, edgecolor="#0097a7", linewidth=1.5, zorder=2)

    # 4. Gambar Ruangan
    for r in data["rooms"]:
        code = r["code"]
        geom = r["geom"]
        
        # Pewarnaan sesuai mode
        if covered_rooms is not None:
            # Mode Jangkauan APAR: Hijau (terjangkau) vs Merah (belum terjangkau)
            if code in covered_rooms:
                fc, ec = "#c8e6c9", "#2e7d32"  # Hijau
            else:
                fc, ec = "#ffcdd2", "#c62828"  # Merah
        elif selected_room and code == selected_room["code"]:
            fc, ec = "#ffb74d", "#e65100"  # Oranye (Ruangan Dipilih)
        else:
            fc, ec = "#fff3e0", "#ffb300"  # Kuning Muda default

        plot_polygon(ax, geom, facecolor=fc, edgecolor=ec, linewidth=1.2, zorder=3)
        c = geom.representative_point()
        ax.text(c.x, c.y, code, ha="center", va="center", fontsize=6, fontweight="bold", color="#333333", zorder=4)

    # 5. Gambar Rute Jalan Koridor (Walking Path)
    if route_coords and len(route_coords) >= 2:
        rx = [p[0] for p in route_coords]
        ry = [p[1] for p in route_coords]
        # Garis rute utama
        ax.plot(rx, ry, color="#d50000", linewidth=3.0, linestyle="-", zorder=6, label="Jalur Koridor ke APAR")
        # Titik start (Centroid Ruangan)
        ax.scatter([rx[0]], [ry[0]], c="#e65100", s=90, edgecolors="white", linewidth=1.5, zorder=7, label="Centroid Ruangan")

    # 6. Titik APAR dan Hydrant
    apar_x = [a["geom"].x for a in data["apar"]]
    apar_y = [a["geom"].y for a in data["apar"]]
    if apar_x:
        ax.scatter(apar_x, apar_y, c="#e53935", s=70, edgecolors="white", linewidth=1.2, zorder=8, label="APAR")

    hydrant_x = [h["geom"].x for h in data["hydrant"]]
    hydrant_y = [h["geom"].y for h in data["hydrant"]]
    if hydrant_x:
        ax.scatter(hydrant_x, hydrant_y, c="#1e88e5", s=70, edgecolors="white", linewidth=1.2, zorder=8, label="Hydrant")

    ax.set_aspect("equal")
    ax.invert_yaxis()  # Sumbu Y piksel mengarah ke bawah
    ax.axis("off")
    ax.legend(loc="lower right", framealpha=0.9, fontsize=8)
    fig.tight_layout()
    return fig

# ==========================================
# STREAMLIT UI
# ==========================================
st.set_page_config(page_title="APAR-UC GIS Finder", layout="wide", page_icon="🧯")

st.title("🧯 APAR-UC: GIS Pencarian APAR & Analisis Jangkauan")
st.caption("Main Building Universitas Ciputra (Lantai 1 - 7) • Berbasis Geometri Shapely & NetworkX")

col_fl, col_md = st.columns([1, 2])
with col_fl:
    floor = st.selectbox("🏢 Pilih Lantai", FLOORS, index=0)

data = load_floor(floor)
corridor_union = unary_union(data["corridors"]) if data["corridors"] else LineString()
corridor_graph = build_corridor_graph(data["corridors"])

with col_md:
    mode = st.radio(
        "🛠️ Pilih Mode Operasi GIS",
        ["Pencarian APAR Terdekat (Real Walking Distance)", "Analisis Jangkauan Proteksi APAR (Buffer 15m)"],
        horizontal=True
    )

st.divider()

if mode == "Pencarian APAR Terdekat (Real Walking Distance)":
    room_options = {f"{r['code']} - {r['name']}": r for r in data["rooms"]}
    
    col_input, col_info = st.columns([1, 2])
    with col_input:
        selected_key = st.selectbox("🚪 Pilih Ruangan Sumber Kebakaran", list(room_options.keys()))
        selected_room = room_options[selected_key]
        room_centroid = selected_room["geom"].centroid
        
        # Hitung jarak ke seluruh APAR
        results = []
        for apar in data["apar"]:
            apar_pt = apar["geom"]
            # 1. Euclidean distance (garis lurus)
            euc_px = room_centroid.distance(apar_pt)
            euc_m = euc_px / PX_PER_M
            
            # 2. Real walking distance (jalur koridor)
            route, walk_px = compute_corridor_route(corridor_graph, corridor_union, room_centroid, apar_pt)
            walk_m = walk_px / PX_PER_M
            
            results.append({
                "id": apar["id"],
                "apar_pt": apar_pt,
                "euc_m": round(euc_m, 2),
                "walk_m": round(walk_m, 2),
                "route": route
            })
            
        # Urutkan berdasarkan jarak koridor nyata terdekat
        results.sort(key=lambda x: x["walk_m"])
        nearest = results[0] if results else None

    with col_info:
        if nearest:
            m1, m2, m3 = st.columns(3)
            m1.metric("📍 APAR Terdekat", nearest["id"])
            m2.metric("🚶 Real Walking Distance", f"{nearest['walk_m']} m")
            m3.metric("📏 Euclidean Distance", f"{nearest['euc_m']} m")

    # Render peta
    route_coords = nearest["route"] if nearest else None
    fig = render_map(data, selected_room=selected_room, route_coords=route_coords)
    st.pyplot(fig)

    # Tabel Top 3 APAR Terdekat sesuai dokumen laporan
    if results:
        st.subheader("📋 Daftar APAR Terdekat dari " + selected_room["code"])
        df_apar = pd.DataFrame([{
            "Peringkat": f"#{idx+1}",
            "ID APAR": r["id"],
            "Walking Distance (Koridor)": f"{r['walk_m']} meter",
            "Euclidean Distance (Lurus)": f"{r['euc_m']} meter",
            "Selisih Jarak Nyata vs Lurus": f"{round(r['walk_m'] - r['euc_m'], 2)} meter"
        } for idx, r in enumerate(results[:3])])
        st.table(df_apar)

else:
    # Mode Analisis Jangkauan Proteksi APAR (Buffer 15m)
    radius_m = 15.0
    radius_px = radius_m * PX_PER_M  # 225 px
    
    # Buat buffer lingkaran 15 meter untuk tiap APAR
    buffers = [a["geom"].buffer(radius_px) for a in data["apar"]]
    buffer_union = unary_union(buffers) if buffers else None
    
    # Periksa ruangan mana saja yang tercover (intersects)
    covered_rooms = set()
    uncovered_rooms = []
    
    for r in data["rooms"]:
        if buffer_union and r["geom"].intersects(buffer_union):
            covered_rooms.add(r["code"])
        else:
            uncovered_rooms.append(r)
            
    total_rooms = len(data["rooms"])
    n_covered = len(covered_rooms)
    n_uncovered = len(uncovered_rooms)
    pct = round((n_covered / total_rooms * 100), 1) if total_rooms > 0 else 0
    
    # Ringkasan KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Ruangan", total_rooms)
    c2.metric("✅ Terjangkau APAR (15m)", f"{n_covered} ({pct}%)")
    c3.metric("❌ Belum Terjangkau (Blind Spot)", n_uncovered)
    c4.metric("Jumlah Unit APAR", len(data["apar"]))

    # Render peta jangkauan
    fig = render_map(data, buffer_union=buffer_union, covered_rooms=covered_rooms)
    st.pyplot(fig)

    if uncovered_rooms:
        st.warning(f"⚠️ Ditemukan **{n_uncovered} ruangan** yang berada di luar radius proteksi 15m APAR (Permenakertrans No. 04/1980):")
        df_uncovered = pd.DataFrame([{
            "Kode Ruangan": r["code"],
            "Nama Ruangan": r["name"],
            "Luas (m²)": r["area_m2"],
            "Status": "Belum Terjangkau (Perlu Rekomendasi Unit APAR)"
        } for r in uncovered_rooms])
        st.dataframe(df_uncovered, use_container_width=True)
    else:
        st.success("🎉 Seluruh ruangan di lantai ini telah terlindungi secara penuh dalam radius 15 meter!")
