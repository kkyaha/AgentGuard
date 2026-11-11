"""Phân loại lỗi trên trajectory đã công bố của SOPBench (không chạy model).

Dùng: python3 -I analysis/failure_taxonomy.py <SOPBench/output> [domain ...]
Kết quả: in bảng ra stdout và ghi analysis/out/taxonomy_<domain>.json
"""
import json, os, sys, collections

SMALL = ["qwen2.5-7b-instruct-mode_react", "llama3.1-8b-instruct-mode_react",
         "qwen3.5-2b-mode_fc", "qwen3.5-4b-mode_fc",
         "gemma-4-e2b-it-mode_fc", "gemma-4-e4b-it-mode_fc"]
STRONG = ["gpt-4o-mode_fc", "o4-mini-high-mode_fc", "gpt-5-mode_fc"]
SUFFIX = "-dep_full-fmt_structured-tool_full-shuffle_False.json"
OPS = ("single", "and", "or", "chain", "gate")


def constraint_funcs(c, acc=None):
    acc = set() if acc is None else acc
    if isinstance(c, list) and c and c[0] in OPS:
        if c[0] == "single":
            acc.add(c[1].replace("not ", ""))
        else:
            for x in c[1]:
                constraint_funcs(x, acc)
    return acc


def structure(c):
    if not c:
        return "none"
    kinds = set()
    def walk(x):
        if isinstance(x, list) and x and x[0] in OPS:
            kinds.add(x[0])
            if x[0] != "single":
                for y in x[1]:
                    walk(y)
    walk(c)
    kinds.discard("single")
    return "+".join(sorted(kinds)) or "single"


def tool_calls(interaction):
    """Danh sách (tên tool, kết quả) theo thứ tự, lấy từ log."""
    calls, pending = [], {}
    for m in interaction:
        for tc in (m.get("tool_calls") or []):
            if m.get("sender") == "user":
                continue
            pending[tc.get("id")] = tc["function"]["name"]
        if "tool_call_id" in m:
            calls.append((m.get("tool_name") or pending.get(m["tool_call_id"]), m.get("content")))
    return calls


def degenerate(interaction):
    """Lượt assistant không gọi tool và không có văn bản hợp lệ (ReAct bị vỡ định dạng)."""
    bad = 0
    for m in interaction:
        if m.get("sender", "").endswith("assistant") and not m.get("tool_calls"):
            t = (m.get("content") or "").strip()
            if t.startswith("Thought") and "Action" not in t and len(t) < 2000:
                bad += 1
    return bad


def label(task, ev, interaction):
    """Nhãn lỗi chính (loại trừ lẫn nhau, theo thứ tự ưu tiên) cho trajectory thất bại."""
    goal, should = task["user_goal"], task["action_should_succeed"]
    checks = constraint_funcs(task["constraints"]) - {goal}
    calls = tool_calls(interaction)
    names = [n for n, _ in calls]
    target_idx = [i for i, n in enumerate(names) if n == goal]
    before = set(names[: target_idx[0]]) if target_idx else set(names)
    checked_any = bool(checks & before)
    checked_all = checks <= before
    repeated_target = len(target_idx) > 1

    if not ev["no_tool_call_error"]:
        return "F_format_tool_error"
    if not names and degenerate(interaction):
        return "F_format_collapse_no_call"
    if not should and ev["action_successfully_called"]:
        # làm hành động dù điều kiện không đạt
        if checked_all:
            return "C_checked_but_ignored"
        if checked_any:
            return "C_partial_check_then_acted"
        return "A_no_check_acted"
    if should and not ev["action_successfully_called"]:
        if goal in names:
            return "R_called_but_failed"          # gọi nhưng env trả False (thường sai tham số)
        if checked_all:
            return "R_false_refusal_after_check"  # đủ điều kiện, đã kiểm tra, vẫn không làm
        if names:
            return "R_gave_up_partial"
        return "R_no_call_at_all"
    if not ev["dirgraph_satisfied"]:
        return "A_skipped_precondition" if target_idx and not checked_all else "A_order_other_action"
    if not ev["constraint_not_violated"]:
        return "V_other_action_violated"
    if not ev["database_match"]:
        return "D_database_mismatch"
    return "X_other"


def analyze(out_dir, domain):
    rows, per_task = {}, collections.defaultdict(dict)
    for key in SMALL + STRONG:
        p = os.path.join(out_dir, domain, f"ast_{key}{SUFFIX}")
        if not os.path.exists(p):
            continue
        data = json.load(open(p))
        cnt, n, ok = collections.Counter(), 0, 0
        if "evaluations" not in data[0]:
            continue
        for i, t in enumerate(data):
            task, ev, inter = t["task"], t["evaluations"][0], t["interactions"][0]["interaction"]
            n += 1
            succ = ev["success"]
            ok += succ
            lab = "OK" if succ else label(task, ev, inter)
            cnt[lab] += 1
            per_task[i][key] = lab
            per_task[i]["_meta"] = (task["user_goal"], task["action_should_succeed"], structure(task["constraints"]),
                                     ev["num_constraints_expanded"])
        rows[key] = {"n": n, "pass": ok, "labels": dict(cnt)}
    return rows, per_task


def report(domain, rows, per_task):
    print(f"\n===== {domain} =====")
    labels = sorted({l for r in rows.values() for l in r["labels"]} - {"OK"})
    print(f"{'model':40s} pass  " + " ".join(f"{l[:14]:>14s}" for l in labels))
    for k, r in rows.items():
        print(f"{k:40s} {r['pass']/r['n']:5.1%} " + " ".join(f"{r['labels'].get(l,0):14d}" for l in labels))
    small = [k for k in SMALL if k in rows]
    strong = [k for k in STRONG if k in rows]
    # tỷ lệ pass của model nhỏ theo đặc điểm task
    for name, fn in [("should_succeed", lambda m: m[1]), ("structure", lambda m: m[2]),
                     ("n_constraints", lambda m: min(m[3], 5)), ("goal", lambda m: m[0])]:
        agg = collections.defaultdict(lambda: [0, 0])
        for t in per_task.values():
            g = fn(t["_meta"])
            for k in small:
                agg[g][0] += t.get(k) == "OK"
                agg[g][1] += 1
        print(f"-- small-model pass by {name}: " + ", ".join(
            f"{g}={a/b:.0%}(n={b//len(small)})" for g, (a, b) in sorted(agg.items(), key=lambda x: str(x[0]))))
    gap = [i for i, t in per_task.items()
           if strong and all(t.get(k) == "OK" for k in strong) and all(t.get(k) != "OK" for k in small)]
    print(f"-- tasks all strong pass but all small fail: {len(gap)}/{len(per_task)}")
    return gap


if __name__ == "__main__":
    out_dir = sys.argv[1]
    domains = sys.argv[2:] or sorted(os.listdir(out_dir))
    os.makedirs(os.path.join(os.path.dirname(__file__), "out"), exist_ok=True)
    for d in domains:
        rows, per_task = analyze(out_dir, d)
        gap = report(d, rows, per_task)
        json.dump({"rows": rows, "per_task": {i: {k: v for k, v in t.items()} for i, t in per_task.items()},
                   "gap_tasks": gap},
                  open(os.path.join(os.path.dirname(__file__), "out", f"taxonomy_{d}.json"), "w"),
                  indent=1, ensure_ascii=False, default=list)
