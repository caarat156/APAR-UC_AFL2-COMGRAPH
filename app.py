from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from shapely.ops import unary_union

from routing import FloorNav, natural_key, load_floor_file

DATA_DIR = Path(__file__).resolve().parent / "data"
FLOORS = ["LT_1", "LT_2", "LT_2A", "LT_3", "LT_4", "LT_5", "LT_6", "LT_7"]
PX_PER_M = 15.0         # Skala: 15 piksel = 1 meter
WALK_SPEED_MPS = 1.2    # Kecepatan jalan rata-rata evakuasi (1.2 m/s)


# ==========================================
# CONFIG & STYLING
# ==========================================
st.set_page_config(page_title="APAR-UC | GIS Finder & Coverage Analysis", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; color: #0f172a; }
    .block-container { padding: 1.5rem 1rem 2rem 1rem; max-width: 95% !important; }
    .hero-banner {
        background-color: #1e293b; color: #ffffff; padding: 22px 26px;
        border-radius: 8px; margin-bottom: 22px; border-left: 5px solid #0284c7;
    }
    .hero-title { font-size: 23px; font-weight: 700; margin: 0; letter-spacing: -0.3px; }
    .kpi-container {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 14px; margin-bottom: 20px;
    }
    .kpi-card {
        background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 16px 18px;
    }
    .kpi-card.red { border-top: 3px solid #dc2626; }
    .kpi-card.orange { border-top: 3px solid #ea580c; }
    .kpi-card.blue { border-top: 3px solid #0284c7; }
    .kpi-card.green { border-top: 3px solid #16a34a; }
    .kpi-header { color: #64748b; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .kpi-value { font-size: 24px; font-weight: 700; color: #0f172a; margin: 6px 0 2px 0; letter-spacing: -0.5px; }
    .kpi-sub { font-size: 11.5px; color: #64748b; font-weight: 400; }
    .notice-box {
        background-color: #f8fafc; border: 1px solid #cbd5e1; border-left: 4px solid #0284c7;
        padding: 10px 14px; border-radius: 4px; font-size: 12.5px; color: #334155; margin-bottom: 16px;
    }
    #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ==========================================
# DATA LOADING & CACHING
# ==========================================
@st.cache_data
def load_floor(floor):
    return load_floor_file(DATA_DIR / f"{floor}.geojson")


@st.cache_resource
def get_floor_nav(floor):
    return FloorNav(load_floor(floor))


@st.cache_data
def get_all_rooms_index():
    """Mengindeks seluruh ruangan di semua lantai untuk fitur search global."""
    rooms = [
        {"code": r["code"], "name": r["name"], "floor": f, "label": f"[{f}] {r['code']} - {r['name']}"}
        for f in FLOORS for r in load_floor(f)["rooms"]
    ]
    return sorted(rooms, key=lambda x: (FLOORS.index(x["floor"]), natural_key(x["code"])))


# ==========================================
# MAP VISUALIZATION
# ==========================================
def plot_polygon(ax, geom, **kwargs):
    for poly in getattr(geom, "geoms", [geom]):
        ax.fill(*poly.exterior.xy, **kwargs)


def render_map(data, selected_room=None, route_coords=None, buffer_union=None, covered_rooms=None):
    fig, ax = plt.subplots(figsize=(15, 8.5), dpi=130)
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#f8fafc')

    # 1. Batas Gedung (Footprint)
    if data["footprint"]:
        plot_polygon(ax, data["footprint"], facecolor="#f1f5f9", edgecolor="#334155", linewidth=2.0)

    # 2. Koridor Gedung
    for line in data["corridors"]:
        ax.plot(*line.xy, color="#059669", linewidth=2.8, linestyle="--", alpha=0.9, zorder=2)

    # 3. Buffer Lingkaran 15m
    if buffer_union and not buffer_union.is_empty:
        plot_polygon(ax, buffer_union, facecolor="#e0f2fe", alpha=0.4, edgecolor="#0284c7", linewidth=1.4, zorder=3)

    # 4. Gambar Ruangan
    for r in data["rooms"]:
        code, geom = r["code"], r["geom"]
        if covered_rooms is not None:
            fc, ec = ("#dcfce7", "#16a34a") if code in covered_rooms else ("#fee2e2", "#dc2626")
        elif selected_room and code == selected_room["code"]:
            fc, ec = "#ffedd5", "#ea580c"
        else:
            fc, ec = "#fef9c3", "#ca8a04"

        plot_polygon(ax, geom, facecolor=fc, edgecolor=ec, linewidth=1.0, zorder=4)
        c = geom.representative_point()
        ax.text(c.x, c.y, code, ha="center", va="center", fontsize=6.2, fontweight="bold", color="#1e293b", zorder=5)

    # 5. Jalur Evakuasi ke APAR
    if route_coords and len(route_coords) >= 2:
        rx, ry = zip(*route_coords)
        ax.plot(rx, ry, color="#dc2626", linewidth=3.2, linestyle="-", solid_capstyle='round', zorder=7, label="Jalur Koridor ke APAR")
        ax.scatter([rx[0]], [ry[0]], c="#ea580c", s=90, edgecolors="white", linewidth=1.8, zorder=8, label="Centroid Ruangan")
        ax.scatter([rx[-1]], [ry[-1]], c="#dc2626", s=110, marker='s', edgecolors="white", linewidth=1.2, zorder=9, label="Target APAR Terdekat")

    # 6. Titik APAR dan Hydrant
    if data["apar"]:
        ax.scatter([a["geom"].x for a in data["apar"]], [a["geom"].y for a in data["apar"]],
                   c="#dc2626", s=60, edgecolors="white", linewidth=1.2, zorder=8, label="Titik APAR")
    if data["hydrant"]:
        ax.scatter([h["geom"].x for h in data["hydrant"]], [h["geom"].y for h in data["hydrant"]],
                   c="#2563eb", s=60, edgecolors="white", linewidth=1.2, zorder=8, label="Titik Hydrant")

    ax.set_aspect("equal")
    if data["footprint"]:
        minx, miny, maxx, maxy = data["footprint"].bounds
        pad_x, pad_y = (maxx - minx) * 0.02, (maxy - miny) * 0.04
        ax.set_xlim(minx - pad_x, maxx + pad_x)
        ax.set_ylim(maxy + pad_y, miny - pad_y)
    else:
        ax.invert_yaxis()
    ax.axis("off")

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, loc="lower right", framealpha=0.95, facecolor="#ffffff", edgecolor="#cbd5e1", fontsize=8.5)

    fig.tight_layout()
    return fig


# ==========================================
# STATE MANAGEMENT
# ==========================================
st.session_state.setdefault("floor_selector", "LT_1")
st.session_state.setdefault("current_room_code", None)

all_rooms_index = get_all_rooms_index()
search_labels = ["-- Cari Ruangan --"] + [item["label"] for item in all_rooms_index]


# ==========================================
# SIDEBAR CONTROLS & NAVIGATION
# ==========================================
with st.sidebar:
    st.markdown("### Kontrol & Navigasi")

    def on_search_select():
        val = st.session_state.get("global_search_box")
        if val and val != search_labels[0]:
            matched = next((item for item in all_rooms_index if item["label"] == val), None)
            if matched:
                st.session_state["floor_selector"] = matched["floor"]
                st.session_state["current_room_code"] = matched["code"]

    st.markdown("**Pencarian Ruangan Global**")
    st.selectbox("Cari ruangan di seluruh lantai:", search_labels, key="global_search_box",
                 on_change=on_search_select, label_visibility="collapsed",
                 help="Pilih nomor ruangan untuk mengarahkan denah lantai.")

    st.divider()

    st.markdown("**Pemilihan Lantai**")
    floor = st.selectbox("Pilih Lantai:", FLOORS, key="floor_selector",
                         on_change=lambda: st.session_state.update({"current_room_code": None}),
                         label_visibility="collapsed")
    data = load_floor(floor)

    st.divider()

    st.markdown("**Mode Operasi GIS**")
    mode = st.radio("Pilih Fitur Analisis:",
                    ["Pencarian APAR Terdekat (Real Walking)", "Analisis Jangkauan Proteksi (Buffer 15m)"],
                    label_visibility="collapsed")

    st.divider()

    st.markdown("##### Ringkasan Data Lantai")
    c1, c2 = st.columns(2)
    c1.metric("Ruangan", len(data["rooms"]))
    c2.metric("APAR", len(data["apar"]))
    st.caption("Skala Peta: **15 px = 1 meter**")


# ==========================================
# MAIN CONTENT AREA
# ==========================================
st.markdown('<div class="hero-banner"><div class="hero-title">APAR-UC: GIS Finder & Emergency Routing</div></div>', unsafe_allow_html=True)

if mode == "Pencarian APAR Terdekat (Real Walking)":
    sorted_rooms = sorted(data["rooms"], key=lambda r: natural_key(r["code"]))
    room_options = {f"{r['code']} - {r['name']}": r for r in sorted_rooms}

    if not room_options or not data["apar"]:
        st.warning("Data ruangan atau titik APAR tidak ditemukan pada lantai ini.")
    else:
        room_codes = [r["code"] for r in sorted_rooms]
        cur = st.session_state["current_room_code"]
        default_idx = room_codes.index(cur) if cur in room_codes else 0

        col_sel, _ = st.columns([2, 1])
        with col_sel:
            st.markdown("##### Pilih Ruangan Sumber Kebakaran:")
            selected_key = st.selectbox("Ruangan Sumber Kebakaran", list(room_options.keys()),
                                        index=default_idx, label_visibility="collapsed")
            selected_room = room_options[selected_key]
            st.session_state["current_room_code"] = selected_room["code"]

        nav = get_floor_nav(floor)
        results = [
            {
                "id": r["id"],
                "apar_pt": r["apar_pt"],
                "walk_m": round(r["walk_px"] / PX_PER_M, 2),
                "est_time": f"{round((r['walk_px'] / PX_PER_M) / WALK_SPEED_MPS)} detik",
                "route": r["route"]
            }
            for r in nav.route(selected_room["code"], data["apar"])
        ]
        nearest = results[0] if results else None

        if nearest:
            st.markdown(f"""
            <div class="kpi-container">
                <div class="kpi-card red"><div class="kpi-header">APAR Terdekat</div><div class="kpi-value">{nearest['id']}</div></div>
                <div class="kpi-card orange"><div class="kpi-header">Real Walking Distance</div><div class="kpi-value">{nearest['walk_m']} m</div></div>
            </div>
            """, unsafe_allow_html=True)

            if nav.door_via.get(selected_room["code"]) == "tetangga":
                st.markdown("""
                <div class="notice-box">
                    <b>Info Akses Ruangan Baris Dalam:</b> Ruangan ini tidak berbatasan langsung dengan koridor utama. Rute diarahkan melalui pintu ruangan tetangga yang berbagi dinding.
                </div>
                """, unsafe_allow_html=True)

        st.pyplot(render_map(data, selected_room=selected_room, route_coords=nearest["route"] if nearest else None), use_container_width=True)

        if results:
            st.markdown("##### Rekomendasi 3 Unit APAR Terdekat:")
            st.dataframe(pd.DataFrame([{
                "Prioritas": f"Peringkat #{idx+1}",
                "ID APAR": r["id"],
                "Jarak Jalan Nyata (Koridor)": f"{r['walk_m']} meter",
                "Estimasi Tempuh Jalan": r["est_time"]
            } for idx, r in enumerate(results[:3])]), use_container_width=True, hide_index=True)

else:
    # Mode Analisis Jangkauan Buffer 15m
    buffers = [a["geom"].buffer(15.0 * PX_PER_M) for a in data["apar"]]
    buffer_union = unary_union(buffers) if buffers else None

    covered_rooms = {r["code"] for r in data["rooms"] if buffer_union and r["geom"].intersects(buffer_union)}
    uncovered_rooms = [r for r in data["rooms"] if r["code"] not in covered_rooms]

    tot, n_cov, n_unc = len(data["rooms"]), len(covered_rooms), len(uncovered_rooms)
    pct = round((n_cov / tot * 100), 1) if tot > 0 else 0

    st.markdown(f"""
    <div class="kpi-container">
        <div class="kpi-card blue"><div class="kpi-header">Total Ruangan</div><div class="kpi-value">{tot}</div><div class="kpi-sub">Lantai {floor}</div></div>
        <div class="kpi-card green"><div class="kpi-header">Terproteksi Penuh</div><div class="kpi-value">{pct}%</div><div class="kpi-sub">{n_cov} dari {tot} Ruangan (Radius 15m)</div></div>
        <div class="kpi-card red"><div class="kpi-header">Blind Spot (Belum Tercover)</div><div class="kpi-value">{n_unc}</div><div class="kpi-sub">Ruangan Perlu Tambahan APAR</div></div>
        <div class="kpi-card orange"><div class="kpi-header">Total Unit APAR</div><div class="kpi-value">{len(data['apar'])}</div><div class="kpi-sub">Unit Terpasang di {floor}</div></div>
    </div>
    """, unsafe_allow_html=True)

    st.pyplot(render_map(data, buffer_union=buffer_union, covered_rooms=covered_rooms), use_container_width=True)

    if uncovered_rooms:
        st.markdown(f"##### Daftar Ruangan Blind Spot di {floor} (Di luar radius 15m Permenakertrans No. 04/1980):")
        st.dataframe(pd.DataFrame([{
            "Kode Ruangan": r["code"],
            "Nama Ruangan": r["name"],
            "Estimasi Luas": f"{r['area_m2']} m²",
            "Kebutuhan Mitigasi": "Rekomendasi Penambahan Unit APAR Baru"
        } for r in uncovered_rooms]), use_container_width=True, hide_index=True)
    else:
        st.success(f"Proteksi Maksimal: Seluruh ruangan di {floor} telah terlindungi secara menyeluruh dalam radius 15 meter.")