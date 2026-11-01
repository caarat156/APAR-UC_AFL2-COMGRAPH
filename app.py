import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from shapely.geometry import Point, LineString
from shapely.ops import unary_union

from routing import FloorNav, natural_key, load_floor_file

DATA_DIR = Path(__file__).resolve().parent / "data"
FLOORS = ["LT_1", "LT_2", "LT_2A", "LT_3", "LT_4", "LT_5", "LT_6", "LT_7"]
PX_PER_M = 15.0  # Skala: 15 piksel = 1 meter


@st.cache_data
def load_floor(floor):
    return load_floor_file(DATA_DIR / f"{floor}.geojson")


@st.cache_resource
def get_floor_nav(floor):
    data = load_floor(floor)
    return FloorNav(data)


@st.cache_data
def get_all_rooms_index():
    """Mengindeks seluruh ruangan di semua lantai untuk fitur search global."""
    all_rooms = []
    for f in FLOORS:
        fdata = load_floor(f)
        for r in fdata["rooms"]:
            all_rooms.append({
                "code": r["code"],
                "name": r["name"],
                "floor": f,
                "label": f"[{f}] {r['code']} - {r['name']}"
            })
    # Urutkan berdasarkan lantai lalu natural sort kode ruangan
    all_rooms.sort(key=lambda x: (FLOORS.index(x["floor"]), natural_key(x["code"])))
    return all_rooms


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
        ax.plot(lx, ly, color="#2e7d32", linewidth=3.5, linestyle="--", alpha=0.85, zorder=2)

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
        rx = [p.x if hasattr(p, "x") else p[0] for p in route_coords]
        ry = [p.y if hasattr(p, "y") else p[1] for p in route_coords]
        # Garis rute utama
        ax.plot(rx, ry, color="#d50000", linewidth=3.2, linestyle="-", zorder=6, label="Jalur Koridor ke APAR")
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
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, loc="lower right", framealpha=0.9, fontsize=8)
    fig.tight_layout()
    return fig

# ==========================================
# STREAMLIT UI
# ==========================================
st.set_page_config(page_title="APAR-UC GIS Finder", layout="wide", page_icon="🧯")

st.title("🧯 APAR-UC: GIS Pencarian APAR & Analisis Jangkauan")
st.caption("Main Building Universitas Ciputra (Lantai 1 - 7) • Berbasis Geometri Shapely & NetworkX")

# Session state initialization
if "floor_selector" not in st.session_state:
    st.session_state["floor_selector"] = "LT_1"
if "current_room_code" not in st.session_state:
    st.session_state["current_room_code"] = None

# Fitur Search Ruangan Global (Semua Lantai)
all_rooms_index = get_all_rooms_index()
search_labels = ["-- Cari nomor/nama ruangan dari semua lantai --"] + [item["label"] for item in all_rooms_index]

def on_search_select():
    val = st.session_state.get("global_search_box")
    if val and val != search_labels[0]:
        matched = next((item for item in all_rooms_index if item["label"] == val), None)
        if matched:
            st.session_state["floor_selector"] = matched["floor"]
            st.session_state["current_room_code"] = matched["code"]

st.selectbox(
    "🔍 Cari Nomor Ruangan (Langsung Menuju Lantai & Ruangan Tersebut):",
    search_labels,
    key="global_search_box",
    on_change=on_search_select,
    help="Pilih atau ketik nomor ruangan untuk langsung membuka peta lantainya dan memilih ruangan tersebut."
)

def on_floor_change():
    st.session_state["current_room_code"] = None

col_fl, col_md = st.columns([1, 2])
with col_fl:
    floor = st.selectbox(
        "🏢 Pilih Lantai",
        FLOORS,
        key="floor_selector",
        on_change=on_floor_change
    )

data = load_floor(floor)

with col_md:
    mode = st.radio(
        "🛠️ Pilih Mode Operasi GIS",
        ["Pencarian APAR Terdekat (Real Walking Distance)", "Analisis Jangkauan Proteksi APAR (Buffer 15m)"],
        horizontal=True
    )

st.divider()

if mode == "Pencarian APAR Terdekat (Real Walking Distance)":
    # Nomor ruangan di dropdown diurutkan secara natural (101, 102, 107, 107A, 113, 113a, ...)
    sorted_rooms = sorted(data["rooms"], key=lambda r: natural_key(r["code"]))
    room_options = {f"{r['code']} - {r['name']}": r for r in sorted_rooms}
    
    if not room_options:
        st.warning("⚠️ Tidak ditemukan data ruangan untuk lantai ini.")
    elif not data["apar"]:
        st.warning("⚠️ Tidak ditemukan data titik APAR untuk lantai ini.")
    else:
        # Tentukan default index berdasarkan current_room_code jika ada
        default_idx = 0
        if st.session_state["current_room_code"]:
            for idx, r in enumerate(sorted_rooms):
                if r["code"] == st.session_state["current_room_code"]:
                    default_idx = idx
                    break

        col_input, col_info = st.columns([1, 2])
        with col_input:
            selected_key = st.selectbox(
                "🚪 Pilih Ruangan Sumber Kebakaran",
                list(room_options.keys()),
                index=default_idx
            )
            selected_room = room_options[selected_key]
            st.session_state["current_room_code"] = selected_room["code"]
            
            # Hitung jarak dan rute koridor bebas tembok menggunakan FloorNav
            nav = get_floor_nav(floor)
            raw_results = nav.route(selected_room["code"], data["apar"])
            
            results = []
            for r in raw_results:
                walk_m = round(r["walk_px"] / PX_PER_M, 2)
                euc_m = round(r["euc_px"] / PX_PER_M, 2)
                results.append({
                    "id": r["id"],
                    "apar_pt": r["apar_pt"],
                    "euc_m": euc_m,
                    "walk_m": walk_m,
                    "diff_m": round(walk_m - euc_m, 2),
                    "route": r["route"]
                })
                
            nearest = results[0] if results else None

        with col_info:
            if nearest:
                m1, m2, m3 = st.columns(3)
                m1.metric("📍 APAR Terdekat", nearest["id"])
                m2.metric("🚶 Real Walking Distance", f"{nearest['walk_m']} m")
                m3.metric("📏 Euclidean Distance", f"{nearest['euc_m']} m")
                
                # Info jalur jika melalui ruangan penghubung
                via = nav.door_via.get(selected_room["code"])
                if via == "tetangga":
                    st.caption("ℹ️ *Ruangan ini berada di baris dalam; rute berjalan melalui ruangan tetangga yang berbagi dinding menuju koridor.*")

        # Render peta
        route_coords = nearest["route"] if nearest else None
        fig = render_map(data, selected_room=selected_room, route_coords=route_coords)
        st.pyplot(fig)

        # Tabel Top 3 APAR Terdekat
        if results:
            st.subheader("📋 Daftar APAR Terdekat dari " + selected_room["code"])
            df_apar = pd.DataFrame([{
                "Peringkat": f"#{idx+1}",
                "ID APAR": r["id"],
                "Walking Distance (Koridor)": f"{r['walk_m']} meter",
                "Euclidean Distance (Lurus)": f"{r['euc_m']} meter",
                "Selisih Jarak Nyata vs Lurus": f"{r['diff_m']} meter"
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
