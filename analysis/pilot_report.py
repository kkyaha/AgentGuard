"""Báo cáo pilot: đọc kết quả runner (mỗi task một file) và in các bảng cho RQ2.

Dùng: python analysis/pilot_report.py <thư mục model> [--control <thư mục model phát lại>]
  vd:  python analysis/pilot_report.py runs/bank/qwen3.5-2b --control runs/bank/replay_qwen3.5-2b-mode_fc

Bảng:
 1. Kết quả theo chế độ (lần chạy r0): hoàn thành (task nên thành công) / từ chối đúng / phục hồi / lặp chặn / token / giây
 2. Đối chứng model phát lại (Gate không có model thích nghi) nếu có --control
 3. So cặp McNemar (chính xác) giữa các chế độ: mọi task, task nên thành công, task "lẽ ra bị chặn"
 4. Hành vi ngay sau lần bị chặn đầu tiên: làm theo / lặp lại / đổi hướng / dừng
 5. Lý do trượt theo tiêu chí oracle
 6. Nhiễu giữa các lần chạy lặp (r0, r1, r2)
"""
import argparse, collections, glob, json, math, os

CRIT = ("no_tool_call_error", "constraint_not_violated", "database_match", "dirgraph_satisfied", "action_called_correctly")


def load(d):
    """{mode: {run: {task: record}}}"""
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for f in glob.glob(os.path.join(d, "*", "task_*.json")):
        try:
            x = json.load(open(f))
        except Exception:
            continue
        if "summary" not in x:
            continue
        s = x["summary"]
        out[s["mode"]][s.get("run", 0)][s["task"]] = x
    return out


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def mcnemar(pairs):
    """pairs: [(a_pass, b_pass)] -> (b, c, p hai phía, kiểm định nhị thức chính xác)"""
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if y and not x)
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return b, c, min(1.0, p)


def after_block(x):
    """Hành vi ngay sau lần bị chặn đầu tiên (theo gate_log)."""
    log = x["gate_log"]
    idx = next((i for i, e in enumerate(log) if e["decision"] == "blocked"), None)
    if idx is None:
        return None
    first = log[idx]
    if idx + 1 >= len(log):
        return "dừng/hỏi khách"
    nxt = log[idx + 1]
    if nxt["tool"] == first["tool"] and nxt.get("args") == first.get("args"):
        return "lặp lại đúng lời gọi"
    if nxt["tool"] in set(first.get("repair", [])) | set(first.get("alternative", [])):
        return "làm theo chuỗi sửa"
    return "đổi hướng khác"


def table_modes(data, title, run=0):
    print(f"\n== {title} (lần chạy r{run}) ==")
    print(f"{'chế độ':10s} {'n':>4s} {'pass':>14s} {'hoàn thành':>14s} {'từ chối đúng':>14s} {'bị chặn≥1':>10s} "
          f"{'phục hồi':>14s} {'lặp chặn':>8s} {'token/task':>10s} {'giây/task':>9s}")
    for mode in [m for m in ("none", "bare", "reason", "next_action", "template", "alignment") if m in data]:
        rows = list(data[mode].get(run, {}).values())
        if not rows:
            continue
        S = [r["summary"] for r in rows]
        ss = [s for s in S if s["should_succeed"]]
        sf = [s for s in S if not s["should_succeed"]]
        bl = [s for s in S if s["n_blocked"] > 0]
        tok = [sum((s.get("tokens") or {}).get(k, 0) for k in ("prompt", "completion")) for s in S]
        print(f"{mode:10s} {len(S):4d} {pct(sum(s['success_fixed'] for s in S), len(S)):>14s} "
              f"{pct(sum(s['success_fixed'] for s in ss), len(ss)):>14s} {pct(sum(s['success_fixed'] for s in sf), len(sf)):>14s} "
              f"{len(bl):10d} {pct(sum(s['success_fixed'] for s in bl), len(bl)):>14s} "
              f"{sum(s['n_repeat_blocked'] for s in S):8d} {sum(tok) / len(S):10.0f} {sum(s['seconds'] for s in S) / len(S):9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--control", default=None)
    a = ap.parse_args()
    data = load(a.model_dir)
    print(f"Thư mục: {a.model_dir} — chế độ: {sorted(data)}")

    table_modes(data, "1. Kết quả theo chế độ")
    if a.control:
        table_modes(load(a.control), "2. Đối chứng: model phát lại (Gate không có model thích nghi)")

    # 3. McNemar trên r0, cùng tập task
    print("\n== 3. So cặp McNemar (r0). b = A pass & B trượt, c = ngược lại ==")
    none0 = data.get("none", {}).get(0, {})
    would = {t for t, x in none0.items() if x["summary"].get("n_would_block", 0) > 0}
    for A, B in (("alignment", "bare"), ("alignment", "none"), ("bare", "none"), ("template", "bare"), ("alignment", "template"),
                 ("next_action", "bare"), ("alignment", "next_action"), ("template", "next_action")):
        if A not in data or B not in data:
            continue
        da, db = data[A].get(0, {}), data[B].get(0, {})
        common = sorted(set(da) & set(db))
        for label, keep in (("mọi task", lambda t: True),
                            ("task nên thành công", lambda t: da[t]["summary"]["should_succeed"]),
                            ("task 'lẽ ra bị chặn'", lambda t: t in would)):
            ts = [t for t in common if keep(t)]
            if not ts:
                continue
            b, c, p = mcnemar([(da[t]["summary"]["success_fixed"], db[t]["summary"]["success_fixed"]) for t in ts])
            print(f"  {A:9s} vs {B:9s} | {label:20s} n={len(ts):3d}  b={b:3d} c={c:3d}  p={p:.4f}")

    # 4. Hành vi sau khi bị chặn
    print("\n== 4. Hành vi ngay sau lần bị chặn đầu tiên (r0) ==")
    for mode in [m for m in data if m != "none"]:
        cnt = collections.Counter(after_block(x) for x in data[mode].get(0, {}).values())
        cnt.pop(None, None)
        tot = sum(cnt.values())
        print(f"  {mode:10s} " + ", ".join(f"{k}: {pct(v, tot)}" for k, v in cnt.most_common()))

    # 5. Lý do trượt
    print("\n== 5. Lý do trượt (tiêu chí oracle không đạt, đếm trên task trượt, r0) ==")
    for mode in data:
        fails = [x for x in data[mode].get(0, {}).values() if not x["summary"]["success_fixed"]]
        cnt = collections.Counter(k for x in fails for k in CRIT if not x["evaluation"].get(k, True))
        print(f"  {mode:10s} trượt {len(fails):3d}: " + ", ".join(f"{k}={v}" for k, v in cnt.most_common()))

    # 6. Nhiễu giữa các lần chạy
    print("\n== 6. Nhiễu giữa các lần chạy lặp ==")
    for mode in data:
        runs = data[mode]
        if len(runs) < 2:
            continue
        ts = set.intersection(*[set(r) for r in runs.values()])
        flip = sum(len({runs[k][t]["summary"]["success_fixed"] for k in runs}) > 1 for t in ts)
        print(f"  {mode:10s} {len(runs)} lần chạy × {len(ts)} task: {pct(flip, len(ts))} task đổi kết quả giữa các lần")


if __name__ == "__main__":
    main()
