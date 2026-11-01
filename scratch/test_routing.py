"""Uji routing: tidak boleh ada rute yang menembus tembok & jarak jalan >= jarak lurus."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from routing import FloorNav, load_floor_file  # noqa: E402

FLOORS = ["LT_1", "LT_2", "LT_2A", "LT_3", "LT_4", "LT_5", "LT_6", "LT_7"]
PX_PER_M = 15.0
total_bad = 0
for f in FLOORS:
    t0 = time.time()
    data = load_floor_file(ROOT / "data" / f"{f}.geojson")
    nav = FloorNav(data)
    codes = [r["code"] for r in data["rooms"]]
    assert len(codes) == len(set(codes)), f"kode ganda di {f}"
    via = {}
    for c, v in nav.door_via.items():
        via.setdefault(v, []).append(c)
    unreachable, viol, shorter, maxratio = [], [], 0, 0.0
    for code in codes:
        res = nav.route(code, data["apar"])
        if not res:
            unreachable.append(code)
            continue
        for r in res:
            if r["walk_px"] + 1e-6 < r["euc_px"]:
                shorter += 1
            maxratio = max(maxratio, r["walk_px"] / max(r["euc_px"], 1))
        for v in nav.violations(res[0]["nodes"]):
            viol.append((code, v[0]))
    total_bad += len(viol) + len(unreachable) + shorter
    print(f"{f}: rooms={len(codes)} apar={len(data['apar'])} t={time.time()-t0:.1f}s "
          f"| via koridor={len(via.get('koridor', []))} tetangga={via.get('tetangga', [])} tanpa akses={via.get(None, [])}")
    print(f"   unreachable={unreachable} | tembok ditembus={viol[:8]} ({len(viol)}) | walk<euc={shorter} | max walk/euc={maxratio:.2f}")
print("TOTAL MASALAH:", total_bad)
