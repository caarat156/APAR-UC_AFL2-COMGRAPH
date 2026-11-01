"""Render denah asli + poligon ruangan + koridor + grid koordinat (alat bantu menggambar koridor)."""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import image as mpimg
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parent.parent
IMAGES = {
    "LT_1": "Denah Lantai 1jpeg.jpeg", "LT_2": "Denah Lantai 2.jpeg", "LT_2A": "Denah Lantai 2A.jpeg",
    "LT_3": "Denah Lantai 3.jpeg", "LT_4": "Denah Lantai 4.jpeg", "LT_5": "Denah Lantai 5.jpeg",
    "LT_6": "Denah Lantai 6.jpeg", "LT_7": "Denah Lantai 7.jpeg",
}


def render(floor, out, crop=None, with_image=True, grid=50, show_rooms=True, dpi=110):
    gj = json.loads((ROOT / "data" / f"{floor}.geojson").read_text(encoding="utf-8"))
    img = mpimg.imread(ROOT / "data" / "sumber" / IMAGES[floor])
    fig, ax = plt.subplots(figsize=(18, 11))
    if with_image:
        ax.imshow(img, alpha=0.55)
    for f in gj["features"]:
        g = shape(f["geometry"])
        t = f["properties"]["type"]
        if t == "room" and show_rooms:
            x, y = g.exterior.xy
            ax.plot(x, y, color="#ff9800", lw=1)
            c = g.representative_point()
            ax.text(c.x, c.y, f["properties"]["code"], fontsize=6, color="#bf360c", ha="center")
        elif t == "corridor":
            xs, ys = g.xy
            ax.plot(xs, ys, color="#00c853", lw=3)
            ax.scatter(xs, ys, color="#00c853", s=18, zorder=9)
        elif t == "door":
            ax.scatter([g.x], [g.y], color="#6a1b9a", s=16, zorder=9)
        elif t == "APAR":
            ax.scatter([g.x], [g.y], color="red", s=30, zorder=8)
        elif t == "Hydrant":
            ax.scatter([g.x], [g.y], color="blue", s=30, zorder=8)
    h, w = img.shape[:2]
    x0, x1, y0, y1 = crop or (0, w, 0, h)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_xticks(range(int(x0 // grid * grid), int(x1) + 1, grid))
    ax.set_yticks(range(int(y0 // grid * grid), int(y1) + 1, grid))
    ax.tick_params(labelsize=6)
    ax.grid(True, color="#00000030", lw=0.4)
    fig.tight_layout()
    fig.savefig(out, dpi=dpi)
    plt.close(fig)


if __name__ == "__main__":
    floor = sys.argv[1]
    out = sys.argv[2]
    crop = tuple(int(v) for v in sys.argv[3].split(",")) if len(sys.argv) > 3 else None
    render(floor, out, crop)
