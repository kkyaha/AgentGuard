"""Gộp kết quả conformance của 7 domain thành nhóm vi phạm (vi phạm ĐẦU TIÊN trong trace thất bại)."""
import collections, glob, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from failure_taxonomy import SMALL, STRONG

def group(v):
    if not v: return "G0 không vi phạm DECLARE (db/tham số)"
    x = min(v, key=lambda e: e["step"])
    t, k = x["template"], x["kind"]
    if t.endswith("Precedence"):
        if not x["is_goal"]: return "G2 Precedence trên action phụ"
        return "G1 Precedence (goal): chưa gọi bước bắt buộc" if k == "missing" else "G1b Precedence (goal): gọi thiếu/sai tham số/Chain"
    if t == "DataCondition":
        return "G3 Điều kiện dữ liệu: đã kiểm tra vẫn làm" if k == "checked_ignored" else "G4 Điều kiện dữ liệu: không kiểm tra"
    if t == "Absence": return "G5 Làm khi không được phép (khác)"
    if t == "Existence": return "G6 Không hoàn thành: chưa thử" if k == "never_attempted" else "G7 Không hoàn thành: gọi nhưng thất bại"
    return t

tot = collections.defaultdict(collections.Counter); n = collections.Counter(); ok = collections.Counter()
for f in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "out", "conformance_*.json"))):
    for t in json.load(open(f))["traces"]:
        n[t["model"]] += 1; ok[t["model"]] += t["oracle_success"]
        if not t["oracle_success"]: tot[t["model"]][group(t["violations"])] += 1
groups = sorted({g for c in tot.values() for g in c})
print("Tỷ lệ (% trên số trace THẤT BẠI), 7 domain, đã loại task không giải được\n")
print(f"{'model':32s} {'pass':>6s} {'#fail':>6s} " + " ".join(f"{g[:3]:>5s}" for g in groups))
for m in SMALL + STRONG:
    fail = n[m] - ok[m]
    print(f"{m:32s} {ok[m]/n[m]:6.1%} {fail:6d} " + " ".join(f"{tot[m][g]/fail:5.0%}" for g in groups))
print(); [print(" ", g) for g in groups]
