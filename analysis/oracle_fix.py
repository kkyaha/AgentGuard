"""Sửa lỗi oracle SOPBench: harness mới (swarm/core.py) bỏ phần tử đầu của kết quả tuple (True, value) trước khi ghi log,
nên evaluator không bao giờ thấy goal 'thành công' → task should_succeed có goal trả tuple không thể pass.
Sửa: goal được gọi, kết quả không phải bool False và không phải chuỗi lỗi → coi là thành công. Các tiêu chí khác giữ nguyên."""
import json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import conformance as C
from failure_taxonomy import SMALL, STRONG, SUFFIX
from declare_rules import SOPBENCH

ERR = re.compile(r"^(Error|[A-Z][A-Za-z]*Error|[A-Z][A-Za-z]*Exception)\b")

def goal_succeeded_fixed(task, interaction):
    for c in C.extract_calls(interaction):
        if c["name"] != task["user_goal"]:
            continue
        r = c["result"]
        if isinstance(r, bool):
            ok = r
        elif isinstance(r, (tuple, list)) and r and isinstance(r[0], bool):
            ok = r[0]
        elif isinstance(r, str) and (ERR.match(r) or r.strip() == "False"):
            ok = False
        else:
            ok = True          # giá trị trả về của tuple (True, value) đã bị bỏ cờ
        if ok:
            return True
    return False

def fixed_success(t):
    ev, task = t["evaluations"][0], t["task"]
    asc = goal_succeeded_fixed(task, t["interactions"][0]["interaction"])
    return (ev["no_tool_call_error"] and ev["constraint_not_violated"] and ev["database_match"]
            and ev["dirgraph_satisfied"] and asc == task["action_should_succeed"])

if __name__ == "__main__":
    rows = collections.defaultdict(lambda: [0, 0, 0])
    for dom in sorted(os.listdir(os.path.join(SOPBENCH, "output"))):
        bad = C.unsolvable(dom)
        for key in SMALL + STRONG:
            p = os.path.join(SOPBENCH, "output", dom, f"ast_{key}{SUFFIX}")
            if not os.path.exists(p): continue
            d = json.load(open(p))
            if not all(t.get("evaluations") for t in d): continue
            for i, t in enumerate(d):
                if i in bad: continue
                rows[key][0] += 1; rows[key][1] += t["evaluations"][0]["success"]; rows[key][2] += fixed_success(t)
    print(f"{'model':34s} {'n':>5s} {'pass gốc':>9s} {'pass sửa':>9s} {'chênh':>7s}")
    for k, (n, a, b) in rows.items():
        print(f"{k:34s} {n:5d} {a/n:9.1%} {b/n:9.1%} {(b-a)/n:+7.1%}")
