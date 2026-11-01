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
WALK_SPEED_MPS = 1.2  # Kecepatan jalan rata-rata evakuasi darurat (1.2 m/s)


# ==========================================
# STREAMLIT CONFIG & CUSTOM STYLING
# ==========================================
st.set_page_config(
    page_title="APAR-UC | GIS Finder & Coverage Analysis",
    layout="wide",
    page_icon="🧯",
    initial_sidebar_state="expanded"
)

# Custom CSS for Modern, Clean & Professional UI
st.markdown("""
<style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Main Container Padding */
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2rem;
        max-width: 95% !important;
    }

    /* Top Hero Banner */
    .hero-banner {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f766e 100%);
        color: white;
        padding: 24px 28px;
        border-radius: 16px;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.25);
        margin-bottom: 24px;
        border-left: 6px solid #f97316;
    }
    .hero-title {
        font-size: 26px;
        font-weight: 800;
        margin: 0;
        letter-spacing: -0.5px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .hero-subtitle {
        font-size: 13.5px;
        color: #cbd5e1;
        margin-top: 6px;
        margin-bottom: 0;
        font-weight: 400;
    }
    .hero-badges {
        display: flex;
        gap: 8px;
        margin-top: 10px;
    }
    .hero-badge {
        background: rgba(255, 255, 255, 0.12);
        backdrop-filter: blur(8px);
        font-size: 11px;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 20px;
        color: #f1f5f9;
        border: 1px solid rgba(255, 255, 255, 0.15);
    }

    /* KPI Metric Cards */
    .kpi-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 14px;
        margin-bottom: 20px;
    }
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 16px 18px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        position: relative;
        overflow: hidden;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08);
    }
    .kpi-card::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 4px;
        height: 100%;
    }
    .kpi-card.red::before { background: #ef4444; }
    .kpi-card.orange::before { background: #f97316; }
    .kpi-card.blue::before { background: #3b82f6; }
    .kpi-card.green::before { background: #10b981; }

    .kpi-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        color: #64748b;
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .kpi-value {
        font-size: 26px;
        font-weight: 800;
        color: #0f172a;
        margin: 6px 0 2px 0;
        letter-spacing: -0.5px;
    }
    .kpi-sub {
        font-size: 11.5px;
        color: #94a3b8;
        font-weight: 500;
    }

    /* Styled Notice Box */
    .notice-box {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-left: 4px solid #3b82f6;
        padding: 10px 14px;
        border-radius: 8px;
        font-size: 12.5px;
        color: #334155;
        margin-bottom: 16px;
    }

    /* Map Card Frame */
    .map-frame {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 12px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        margin-bottom: 20px;
    }

    /* Hide standard Streamlit header & footer decorations */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
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
    all_rooms.sort(key=lambda x: (FLOORS.index(x["floor"]), natural_key(x["code"])))
    return all_rooms


# ==========================================
# MAP VISUALIZATION (HIGH QUALITY STYLING)
# ==========================================
def plot_polygon(ax, geom, **kwargs):
    for poly in getattr(geom, "geoms", [geom]):
        x, y = poly.exterior.xy
        ax.fill(x, y, **kwargs)


def render_map(data, selected_room=None, route_coords=None, buffer_union=None, covered_rooms=None):
    fig, ax = plt.subplots(figsize=(15, 8.5), dpi=130)
    fig.patch.set_facecolor('#ffffff')
    ax.set_facecolor('#f8fafc')

    # 1. Batas Gedung (Footprint)
    if data["footprint"]:
        plot_polygon(ax, data["footprint"], facecolor="#f1f5f9", edgecolor="#334155", linewidth=2.4)

    # 2. Koridor Gedung
    for line in data["corridors"]:
        lx, ly = line.xy
        ax.plot(lx, ly, color="#059669", linewidth=3.2, linestyle="--", alpha=0.9, zorder=2)

    # 3. Buffer Lingkaran 15 Meter (Analisis Jangkauan)
    if buffer_union is not None and not buffer_union.is_empty:
        plot_polygon(ax, buffer_union, facecolor="#38bdf8", alpha=0.25, edgecolor="#0284c7", linewidth=1.6, zorder=3)

    # 4. Gambar Ruangan
    for r in data["rooms"]:
        code = r["code"]
        geom = r["geom"]
        
        if covered_rooms is not None:
            # Mode Jangkauan APAR: Hijau (terjangkau) vs Merah (blind spot)
            if code in covered_rooms:
                fc, ec = "#dcfce7", "#16a34a"  # Hijau lembut
            else:
                fc, ec = "#fee2e2", "#dc2626"  # Merah lembut
        elif selected_room and code == selected_room["code"]:
            fc, ec = "#fed7aa", "#ea580c"      # Oranye highlight
        else:
            fc, ec = "#fef9c3", "#ca8a04"      # Kuning lembut default

        plot_polygon(ax, geom, facecolor=fc, edgecolor=ec, linewidth=1.1, zorder=4)
        c = geom.representative_point()
        ax.text(c.x, c.y, code, ha="center", va="center", fontsize=6.2, fontweight="bold", color="#1e293b", zorder=5)

    # 5. Jalur Evakuasi / Rute Koridor ke APAR
    if route_coords and len(route_coords) >= 2:
        rx = [p.x if hasattr(p, "x") else p[0] for p in route_coords]
        ry = [p.y if hasattr(p, "y") else p[1] for p in route_coords]
        
        # Garis rute utama (vibrant red glow)
        ax.plot(rx, ry, color="#dc2626", linewidth=3.6, linestyle="-", solid_capstyle='round', zorder=7, label="Jalur Koridor ke APAR")
        
        # Titik start (Centroid Ruangan Sumber Kebakaran)
        ax.scatter([rx[0]], [ry[0]], c="#f97316", s=100, edgecolors="white", linewidth=2.0, zorder=8, label="Centroid Ruangan")
        
        # Titik target APAR terpilih (Lingkaran target)
        ax.scatter([rx[-1]], [ry[-1]], c="#dc2626", s=130, marker='*', edgecolors="white", linewidth=1.2, zorder=9, label="Target APAR Terdekat")

    # 6. Titik APAR dan Hydrant
    apar_x = [a["geom"].x for a in data["apar"]]
    apar_y = [a["geom"].y for a in data["apar"]]
    if apar_x:
        ax.scatter(apar_x, apar_y, c="#ef4444", s=65, edgecolors="white", linewidth=1.2, zorder=8, label="Titik APAR")

    hydrant_x = [h["geom"].x for h in data["hydrant"]]
    hydrant_y = [h["geom"].y for h in data["hydrant"]]
    if hydrant_x:
        ax.scatter(hydrant_x, hydrant_y, c="#2563eb", s=65, edgecolors="white", linewidth=1.2, zorder=8, label="Titik Hydrant")

    ax.set_aspect("equal")
    if data["footprint"]:
        minx, miny, maxx, maxy = data["footprint"].bounds
        pad_x = (maxx - minx) * 0.02
        pad_y = (maxy - miny) * 0.04
        ax.set_xlim(minx - pad_x, maxx + pad_x)
        ax.set_ylim(maxy + pad_y, miny - pad_y)  # Inverted Y
    else:
        ax.invert_yaxis()
    ax.axis("off")
    
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, loc="lower right", framealpha=0.92, facecolor="#ffffff", edgecolor="#cbd5e1", fontsize=8.5)
    
    fig.tight_layout()
    return fig


# ==========================================
# STATE MANAGEMENT
# ==========================================
if "floor_selector" not in st.session_state:
    st.session_state["floor_selector"] = "LT_1"
if "current_room_code" not in st.session_state:
    st.session_state["current_room_code"] = None

all_rooms_index = get_all_rooms_index()
search_labels = ["-- Ketik / Pilih Ruangan dari Seluruh Lantai --"] + [item["label"] for item in all_rooms_index]


# ==========================================
# SIDEBAR CONTROLS & NAVIGATION
# ==========================================
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/4/4b/Logo_Universitas_Ciputra.png", width=180)
    st.markdown("### ⚙️ Kontrol & Navigasi")
    
    # 1. Global Search Box
    def on_search_select():
        val = st.session_state.get("global_search_box")
        if val and val != search_labels[0]:
            matched = next((item for item in all_rooms_index if item["label"] == val), None)
            if matched:
                st.session_state["floor_selector"] = matched["floor"]
                st.session_state["current_room_code"] = matched["code"]

    st.markdown("**🔍 Pencarian Ruangan Global**")
    st.selectbox(
        "Cari ruangan di seluruh lantai:",
        search_labels,
        key="global_search_box",
        on_change=on_search_select,
        label_visibility="collapsed",
        help="Ketik atau pilih nomor ruangan untuk langsung menuju denah lantai dan memilih ruangan tersebut."
    )
    
    st.divider()

    # 2. Pemilihan Lantai
    def on_floor_change():
        st.session_state["current_room_code"] = None

    st.markdown("**🏢 Pemilihan Lantai**")
    floor = st.selectbox(
        "Pilih Lantai:",
        FLOORS,
        key="floor_selector",
        on_change=on_floor_change,
        label_visibility="collapsed"
    )

    data = load_floor(floor)

    st.divider()

    # 3. Pemilihan Mode Operasi
    st.markdown("**🛠️ Mode Operasi GIS**")
    mode = st.radio(
        "Pilih Fitur Analisis:",
        ["🧭 Pencarian APAR Terdekat (Real Walking)", "🛡️ Analisis Jangkauan Proteksi (Buffer 15m)"],
        label_visibility="collapsed"
    )

    st.divider()

    # Summary Info Lantai Terpilih
    st.markdown("##### 📊 Ringkasan Data Lantai")
    c_info1, c_info2 = st.columns(2)
    c_info1.metric("Ruangan", len(data["rooms"]))
    c_info2.metric("APAR", len(data["apar"]))
    
    st.caption("Skala Peta: **15 px = 1 meter** • Standar Proteksi: **Permenakertrans No. 04/1980**")


# ==========================================
# MAIN CONTENT AREA
# ==========================================
# Top Hero Banner
st.markdown(f"""
<div class="hero-banner">
    <div class="hero-title">
        <span>🧯 APAR-UC: GIS Finder & Emergency Routing</span>
    </div>
    <div class="hero-subtitle">
        Sistem Informasi Geografis Penentuan Rute Terdekat ke Titik APAR dan Analisis Jangkauan Proteksi Gedung Utama Universitas Ciputra
    </div>
    <div class="hero-badges">
        <span class="hero-badge">🏢 {floor}</span>
        <span class="hero-badge">📍 {len(data['apar'])} Unit APAR</span>
        <span class="hero-badge">🚪 {len(data['rooms'])} Ruangan Terdaftar</span>
        <span class="hero-badge">⚡ Dijkstra Shortest Path</span>
    </div>
</div>
""", unsafe_allow_html=True)


if mode == "🧭 Pencarian APAR Terdekat (Real Walking)":
    sorted_rooms = sorted(data["rooms"], key=lambda r: natural_key(r["code"]))
    room_options = {f"{r['code']} - {r['name']}": r for r in sorted_rooms}

    if not room_options:
        st.warning("⚠️ Tidak ditemukan data ruangan pada lantai ini.")
    elif not data["apar"]:
        st.warning("⚠️ Tidak ditemukan titik APAR terdaftar pada lantai ini.")
    else:
        # Tentukan default index
        default_idx = 0
        if st.session_state["current_room_code"]:
            for idx, r in enumerate(sorted_rooms):
                if r["code"] == st.session_state["current_room_code"]:
                    default_idx = idx
                    break

        # Bar Kontrol Ruangan
        col_sel_room, col_space = st.columns([2, 1])
        with col_sel_room:
            st.markdown("##### 🚪 Pilih Ruangan Sumber Kebakaran:")
            selected_key = st.selectbox(
                "Ruangan Sumber Kebakaran",
                list(room_options.keys()),
                index=default_idx,
                label_visibility="collapsed"
            )
            selected_room = room_options[selected_key]
            st.session_state["current_room_code"] = selected_room["code"]

        # Hitung Rute Dijkstra menggunakan FloorNav
        nav = get_floor_nav(floor)
        raw_results = nav.route(selected_room["code"], data["apar"])

        results = []
        for r in raw_results:
            walk_m = round(r["walk_px"] / PX_PER_M, 2)
            euc_m = round(r["euc_px"] / PX_PER_M, 2)
            est_sec = round(walk_m / WALK_SPEED_MPS)
            results.append({
                "id": r["id"],
                "apar_pt": r["apar_pt"],
                "euc_m": euc_m,
                "walk_m": walk_m,
                "diff_m": round(walk_m - euc_m, 2),
                "est_time": f"{est_sec} detik",
                "route": r["route"]
            })

        nearest = results[0] if results else None

        # Kartu KPI Metrics yang Bersih & Rapi
        if nearest:
            st.markdown(f"""
            <div class="kpi-container">
                <div class="kpi-card red">
                    <div class="kpi-header">📍 APAR Terdekat <span style="font-size:16px">🧯</span></div>
                    <div class="kpi-value">{nearest['id']}</div>
                    <div class="kpi-sub">Unit Proteksi Prioritas #1</div>
                </div>
                <div class="kpi-card orange">
                    <div class="kpi-header">🚶 Real Walking Distance <span style="font-size:16px">⏱️</span></div>
                    <div class="kpi-value">{nearest['walk_m']} m</div>
                    <div class="kpi-sub">Estimasi Tempuh: {nearest['est_time']}</div>
                </div>
                <div class="kpi-card blue">
                    <div class="kpi-header">📏 Euclidean Distance <span style="font-size:16px">📐</span></div>
                    <div class="kpi-value">{nearest['euc_m']} m</div>
                    <div class="kpi-sub">Garis Lurus (Ideal)</div>
                </div>
                <div class="kpi-card green">
                    <div class="kpi-header">🔄 Selisih Jarak Nyata <span style="font-size:16px">🛤️</span></div>
                    <div class="kpi-value">+{nearest['diff_m']} m</div>
                    <div class="kpi-sub">Efek Dinding & Koridor Fisik</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            via = nav.door_via.get(selected_room["code"])
            if via == "tetangga":
                st.markdown("""
                <div class="notice-box">
                    ℹ️ <b>Info Akses Ruangan Baris Dalam:</b> Ruangan ini tidak berbatasan langsung dengan koridor utama. Rute evakuasi diarahkan melalui pintu ruangan tetangga yang berbagi dinding.
                </div>
                """, unsafe_allow_html=True)

        # Render Peta
        route_coords = nearest["route"] if nearest else None
        st.markdown('<div class="map-frame">', unsafe_allow_html=True)
        fig = render_map(data, selected_room=selected_room, route_coords=route_coords)
        st.pyplot(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Tabel Top 3 APAR Terdekat
        if results:
            st.markdown("##### 📋 Rekomendasi 3 Unit APAR Terdekat:")
            df_display = pd.DataFrame([{
                "Prioritas": f"Peringkat #{idx+1}",
                "ID APAR": r["id"],
                "Jarak Jalan Nyata (Koridor)": f"{r['walk_m']} meter",
                "Jarak Lurus (Euclidean)": f"{r['euc_m']} meter",
                "Selisih Belokan": f"+{r['diff_m']} meter",
                "Estimasi Tempuh Jalan": r["est_time"]
            } for idx, r in enumerate(results[:3])])
            st.dataframe(df_display, use_container_width=True, hide_index=True)

else:
    # Mode Analisis Jangkauan Proteksi APAR (Buffer 15m)
    radius_m = 15.0
    radius_px = radius_m * PX_PER_M  # 225 px

    buffers = [a["geom"].buffer(radius_px) for a in data["apar"]]
    buffer_union = unary_union(buffers) if buffers else None

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

    # Kartu KPI Jangkauan Proteksi
    st.markdown(f"""
    <div class="kpi-container">
        <div class="kpi-card blue">
            <div class="kpi-header">🏢 Total Ruangan <span style="font-size:16px">🚪</span></div>
            <div class="kpi-value">{total_rooms}</div>
            <div class="kpi-sub">Lantai {floor}</div>
        </div>
        <div class="kpi-card green">
            <div class="kpi-header">✅ Terproteksi Penuh <span style="font-size:16px">🛡️</span></div>
            <div class="kpi-value">{pct}%</div>
            <div class="kpi-sub">{n_covered} dari {total_rooms} Ruangan (Radius 15m)</div>
        </div>
        <div class="kpi-card red">
            <div class="kpi-header">❌ Blind Spot (Belum Tercover) <span style="font-size:16px">⚠️</span></div>
            <div class="kpi-value">{n_uncovered}</div>
            <div class="kpi-sub">Ruangan Perlu Tambahan APAR</div>
        </div>
        <div class="kpi-card orange">
            <div class="kpi-header">🧯 Total Unit APAR <span style="font-size:16px">📍</span></div>
            <div class="kpi-value">{len(data['apar'])}</div>
            <div class="kpi-sub">Unit Terpasang di {floor}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Render Peta Jangkauan
    st.markdown('<div class="map-frame">', unsafe_allow_html=True)
    fig = render_map(data, buffer_union=buffer_union, covered_rooms=covered_rooms)
    st.pyplot(fig, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if uncovered_rooms:
        st.markdown(f"##### ⚠️ Daftar Ruangan Blind Spot di {floor} (Di luar radius 15m Permenakertrans No. 04/1980):")
        df_uncovered = pd.DataFrame([{
            "Kode Ruangan": r["code"],
            "Nama Ruangan": r["name"],
            "Estimasi Luas": f"{r['area_m2']} m²",
            "Kebutuhan Mitigasi": "Rekomendasi Penambahan Unit APAR Baru"
        } for r in uncovered_rooms])
        st.dataframe(df_uncovered, use_container_width=True, hide_index=True)
    else:
        st.success(f"🎉 **Proteksi Maksimal:** Seluruh ruangan di {floor} telah terlindungi secara menyeluruh dalam radius 15 meter!")
