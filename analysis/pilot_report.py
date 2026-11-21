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
    g = first.get("goal_info") or {}
    followed = set(first.get("repair", [])) | set(first.get("alternative", [])) | set(g.get("goal_steps") or [])
    if g.get("relation") in ("not_needed", "optional"):    # chế độ goal: phản hồi bảo bỏ X, làm bước của G (hoặc gọi G)
        followed = set(g.get("goal_steps") or []) | {g.get("goal")}
    if nxt["tool"] in followed:
        return "làm theo chuỗi sửa"
    return "đổi hướng khác"


MODE_ORDER = ("none", "bare", "reason", "next_action", "template", "alignment_1", "alignment_static", "alignment_dag", "alignment", "alignment_phi",
              "goal", "purpose", "goal_ex", "purpose_v2")


_RS = {}


def login_violation(x):
    """Sửa lỗi oracle (offline): login/xác thực của hệ thống strict đặt trạng thái TRƯỚC khi kiểm thông tin, nên oracle không phạt
    lời gọi phụ thuộc vào một login đã thất bại. True nếu có lời gọi ĐÃ THỰC THI mà tiền điều kiện thiếu chỉ vì tool tạo trạng
    thái đã gọi nhưng thất bại (ngữ nghĩa S2 của Gate). Dùng để báo `pass_login`: success_fixed và không có vi phạm này."""
    import conformance as C
    from alignment import record, state_tools
    from declare_rules import Act, load_rules
    dom, task = x["config"]["domain"], x["task"]
    key = (dom, task.get("user_goal"), json.dumps(task.get("constraints"), sort_keys=True, default=str), x["summary"]["task"])
    if key not in _RS:
        _RS[key] = load_rules(dom, task)
    rs = _RS[key]
    st, hist = state_tools(dom), C.History()
    for e in x.get("gate_log", []):
        if e.get("decision") != "allowed" or not isinstance(e.get("args"), dict) or e["tool"] not in rs.action_params:
            continue
        f = rs.precondition(e["tool"])
        if isinstance(f, Act):
            b = {v: e["args"].get(k) for k, v in f.params.items()}
            for _, src, _ in C.unsatisfied(f.sub, b, hist):
                if any(y in st and y in hist.any for y in src):
                    return True
        record(rs, hist, e["tool"], e["args"], C.try_eval(e.get("result")))
    return False


def pass_login(x):
    return x["summary"]["success_fixed"] and not login_violation(x)


def table_modes(data, title, run=0):
    print(f"\n== {title} (lần chạy r{run}) ==")
    print(f"{'chế độ':10s} {'n':>4s} {'pass':>14s} {'hoàn thành':>14s} {'từ chối đúng':>14s} {'bị chặn≥1':>10s} "
          f"{'phục hồi':>14s} {'lặp chặn':>8s} {'nhắc':>5s} {'token/task':>10s} {'giây/task':>9s}")
    for mode in [m for m in MODE_ORDER if m in data]:
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
              f"{sum(s['n_repeat_blocked'] for s in S):8d} {sum(s.get('n_reminders', 0) for s in S):5d} {sum(tok) / len(S):10.0f} {sum(s['seconds'] for s in S) / len(S):9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("--control", default=None)
    ap.add_argument("--budget", default=None, help="thư mục đối chứng ngân sách (max_actions/max_turns nới rộng)")
    ap.add_argument("--none_from", default=None,
                    help="thư mục model của lượt cũ có chế độ none (none không phụ thuộc code Gate; dùng cho nhóm 3b/3c, 1b). "
                         "vd runs/x1_nothink/hotel/qwen3.5-2b. KHÔNG dùng none này trong phép so McNemar.")
    a = ap.parse_args()
    data = load(a.model_dir)
    if a.none_from and "none" not in data:
        data["none"] = load(a.none_from).get("none", {})
        print(f"[none lấy từ lượt cũ: {a.none_from} — chỉ để nhóm task / mốc tham khảo, không so cặp]")
    print(f"Thư mục: {a.model_dir} — chế độ: {sorted(data)}")

    table_modes(data, "1. Kết quả theo chế độ")
    if a.control:
        table_modes(load(a.control), "2. Đối chứng: model phát lại (Gate không có model thích nghi)")
    if a.budget:
        table_modes(load(a.budget), "2b. Đối chứng ngân sách (max_actions 20, max_turns 40): bare có đuổi kịp next_action không")

    # 3. McNemar trên r0, cùng tập task
    print("\n== 3. So cặp McNemar (r0). b = A pass & B trượt, c = ngược lại ==")
    none0 = data.get("none", {}).get(0, {})
    would = {t for t, x in none0.items() if x["summary"].get("n_would_block", 0) > 0}
    for A, B in (("alignment", "bare"), ("alignment", "none"), ("bare", "none"), ("template", "bare"), ("alignment", "template"),
                 ("next_action", "bare"), ("alignment", "next_action"), ("template", "next_action"),
                 ("goal", "next_action"), ("purpose", "next_action"), ("goal", "purpose"), ("goal", "alignment"),
                 ("purpose", "alignment"), ("goal_ex", "goal"), ("goal_ex", "next_action"),
                 ("purpose_v2", "next_action"), ("purpose_v2", "purpose"), ("purpose_v2", "goal"),
                 ("alignment_1", "next_action"), ("alignment", "alignment_1"),
                 ("alignment", "alignment_dag"), ("alignment_phi", "alignment"), ("alignment", "alignment_static")):
        if A not in data or B not in data or (a.none_from and "none" in (A, B)):
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

    # 3b. H2b: pass theo độ dài chuỗi sửa ở lần chặn đầu. Nhóm lấy từ lượt none (would_block) -> không phụ thuộc chế độ.
    if none0:
        def glen(t):
            wb = [e for e in none0[t].get("gate_log", []) if e.get("decision") == "would_block"]
            return "không chặn" if not wb else ("1 bước" if len(wb[0]["repair"]) == 1 else "≥2 bước")
        print("\n== 3b. Pass theo độ dài chuỗi sửa ở lần chặn đầu (nhóm theo lượt none, r0) ==")
        for sub, keep in (("mọi task", lambda t: True), ("nên thành công", lambda t: none0[t]["summary"]["should_succeed"])):
            for g in ("1 bước", "≥2 bước", "không chặn"):
                ts = [t for t in none0 if glen(t) == g and keep(t)]
                if not ts:
                    continue
                cells = [f"{m} {sum(1 for t in ts if t in data[m].get(0, {}) and data[m][0][t]['summary']['success_fixed'])}/"
                         f"{sum(1 for t in ts if t in data[m].get(0, {}))}" for m in MODE_ORDER if m in data]
                print(f"  {sub:15s} {g:10s} | " + " | ".join(cells))

    # 3c. Theo độ dài chuỗi chi tiết (task nên thành công)
    if none0:
        def glen4(t):
            wb = [e for e in none0[t].get("gate_log", []) if e.get("decision") == "would_block"]
            return None if not wb else min(len(wb[0]["repair"]), 4)
        print("\n== 3c. Hoàn thành theo độ dài chuỗi ở lần chặn đầu (task nên thành công, nhóm theo none, r0) ==")
        for g in (1, 2, 3, 4):
            ts = [t for t in none0 if none0[t]["summary"]["should_succeed"] and glen4(t) == g]
            if ts:
                cells = [f"{m} {sum(1 for t in ts if t in data[m].get(0, {}) and data[m][0][t]['summary']['success_fixed'])}"
                         for m in MODE_ORDER if m in data and m != "none"]
                print(f"  {('4+' if g == 4 else str(g)) + ' bước':7s} n={len(ts):3d} | " + " | ".join(cells))

    # 1b. Sửa lỗi oracle login (offline) + 8. Task nên từ chối kết thúc thế nào (từ chối có căn cứ)
    print("\n== 1b. Pass khi sửa lỗi oracle login (lời gọi phụ thuộc login/xác thực đã thất bại = vi phạm), r0 ==")
    for mode in [m for m in MODE_ORDER if m in data]:
        R = list(data[mode].get(0, {}).values())
        ss = [x for x in R if x["summary"]["should_succeed"]]
        sf = [x for x in R if not x["summary"]["should_succeed"]]
        nv = sum(login_violation(x) for x in R)
        print(f"  {mode:13s} pass {sum(pass_login(x) for x in R):4d}/{len(R)} | hoàn thành {sum(pass_login(x) for x in ss):3d}/{len(ss)}"
              f" | từ chối đúng {sum(pass_login(x) for x in sf):3d}/{len(sf)} | trace có vi phạm login {nv}")
    print("\n== 8. Task nên từ chối kết thúc thế nào (r0). 'G đã chạy' = Precedence thỏa mà model vẫn làm G; 'không gọi G' gồm cả G chưa từng được phép ==")
    for mode in [m for m in MODE_ORDER if m in data and m != "none"]:
        c = collections.Counter()
        for x in data[mode].get(0, {}).values():
            sm = x["summary"]
            if sm["should_succeed"]:
                continue
            gl = [e for e in x.get("gate_log", []) if e["tool"] == sm["goal"]]
            if any(e["decision"] == "allowed" for e in gl):
                k = "G đã chạy"
            elif gl and gl[-1]["decision"] == "blocked" and gl[-1].get("violations") and gl[-1]["violations"][0][0] == "DataCondition":
                k = "G bị chặn vì φa"
            elif gl and gl[-1]["decision"] == "blocked":
                k = "dừng khi G còn bị chặn (Precedence)"
            else:
                k = "không gọi G"
            c[(k, "pass" if sm["success_fixed"] else "trượt")] += 1
        print(f"  {mode:13s} " + " | ".join(f"{k} {v1}: {c[(k, v1)]}" for k in ("G đã chạy", "G bị chặn vì φa",
              "dừng khi G còn bị chặn (Precedence)", "không gọi G") for v1 in ("pass", "trượt") if c[(k, v1)]))

    # 4. Hành vi sau khi bị chặn
    print("\n== 4. Hành vi ngay sau lần bị chặn đầu tiên (r0) ==")
    for mode in [m for m in data if m != "none"]:
        cnt = collections.Counter(after_block(x) for x in data[mode].get(0, {}).values())
        cnt.pop(None, None)
        tot = sum(cnt.values())
        print(f"  {mode:10s} " + ", ".join(f"{k}: {pct(v, tot)}" for k, v in cnt.most_common()))

    # 4b. Theo loại lần chặn đầu tiên: chặn chính goal hay chặn tool phụ (nhóm mà phản hồi theo goal nhắm tới)
    print("\n== 4b. Pass theo loại lần chặn đầu tiên (r0): goal / tool phụ ==")
    for mode in [m for m in MODE_ORDER if m in data and m != "none"]:
        grp = collections.defaultdict(list)
        for x in data[mode].get(0, {}).values():
            first = next((e for e in x.get("gate_log", []) if e.get("decision") == "blocked"), None)
            if first is None:
                continue
            k = "chặn goal" if first["tool"] == x["summary"]["goal"] else "chặn tool phụ"
            grp[k].append(x["summary"]["success_fixed"])
        print(f"  {mode:10s} " + " | ".join(f"{k}: {pct(sum(v), len(v))}" for k, v in sorted(grp.items())))

    # 5. Lý do trượt
    print("\n== 5. Lý do trượt (tiêu chí oracle không đạt, đếm trên task trượt, r0) ==")
    for mode in data:
        fails = [x for x in data[mode].get(0, {}).values() if not x["summary"]["success_fixed"]]
        cnt = collections.Counter(k for x in fails for k in CRIT if not x["evaluation"].get(k, True))
        print(f"  {mode:10s} trượt {len(fails):3d}: " + ", ".join(f"{k}={v}" for k, v in cnt.most_common()))

    # 7. Nhắc nghĩa vụ Existence(G) (goal_ex): có kéo model làm G ở task nên từ chối không (chỉ số chặn chiều xấu của H4)
    if "goal_ex" in data:
        print("\n== 7. goal_ex: task có nhắc Existence(G) (r0) ==")
        X = list(data["goal_ex"].get(0, {}).values())
        rem = [x for x in X if x["summary"].get("n_reminders", 0) > 0]
        ss = [x for x in rem if x["summary"]["should_succeed"]]
        sf = [x for x in rem if not x["summary"]["should_succeed"]]
        base = data.get("goal", {}).get(0, {})
        print(f"  có nhắc: {len(rem)}/{len(X)} task | nên thành công pass {pct(sum(x['summary']['success_fixed'] for x in ss), len(ss))}"
              f" | nên từ chối, từ chối đúng {pct(sum(x['summary']['success_fixed'] for x in sf), len(sf))}")
        if base:
            for lab, grp in (("nên thành công", ss), ("nên từ chối", sf)):
                ts = [x["summary"]["task"] for x in grp if x["summary"]["task"] in base]
                print(f"  cùng task ở goal ({lab}): pass {pct(sum(base[t]['summary']['success_fixed'] for t in ts), len(ts))}")

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
