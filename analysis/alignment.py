"""Alignment tối ưu cho nhóm Precedence của DECLARE và phản hồi sinh từ alignment (dùng chung mọi domain).

Quyết định thiết kế (CLAUDE.md): Gate chỉ ép Precedence / Branched / Choice / Chain; không tự phán điều kiện dữ liệu.

Với mô hình chỉ gồm các template này, alignment tối ưu tại một lần kích hoạt X là:
  Act Y chưa thỏa  -> sửa(Y.sub) + [chèn Y]                 (model move, đệ quy theo Chain)
  and              -> nối các sửa của từng phần (bỏ trùng)
  or               -> nhánh có chi phí nhỏ nhất (1/bước; hòa: tránh internal_get_database, ít tham số phải hỏi)
Thứ tự các bước chèn là một thứ tự tô-pô hợp lệ (tiền điều kiện trước).

Chạy offline: .venv/bin/python analysis/alignment.py [domain ...]
  (1) Thống kê alignment tại lần chặn ĐẦU TIÊN trên trace thật của model nhỏ.
  (2) Độ khớp lựa chọn nhánh với trace thành công của model mạnh.
  (3) "Agent lý tưởng": chỉ làm theo phản hồi alignment (+ đọc kết quả kiểm tra) có pass oracle không → kiểm tra tính đủ.
"""
from __future__ import annotations
import collections, copy, json, os, sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
from declare_rules import (SOPBENCH, Act, Op, load_rules, new_strict_system, domain_keys,  # noqa: E402
                           domain_assistant_keys)
import conformance as C  # noqa: E402
from failure_taxonomy import SMALL, STRONG, SUFFIX  # noqa: E402

DB_DUMP = "internal_get_database"


# ---------------------------------------------------------------- alignment
@dataclass
class Move:
    tool: str
    args: dict            # tham số suy được từ tương quan với X
    ask_user: list        # tham số không suy được -> phải hỏi người dùng

    def key(self):
        return (self.tool, tuple(sorted((k, C.norm(v)) for k, v in self.args.items())))


def _cost(moves):
    # Đọc toàn bộ DB tính 2 bước: ngữ cảnh rất dài, model nhỏ dễ lạc; ưu tiên tool kiểm tra cụ thể.
    n_dump = sum(m.tool == DB_DUMP for m in moves)
    return (len(moves) + n_dump, n_dump, sum(len(m.ask_user) for m in moves))


def state_tools(domain):
    """Tool tạo trạng thái (login, xác thực): chỉ tính là đã thỏa khi KẾT QUẢ THẬT trả về thành công."""
    cl = domain_assistant_keys[domain].constraint_links
    return {(v[0] if isinstance(v, tuple) else v) for v in cl.values()}


def record(rs, hist, name, args, res):
    """Cập nhật lịch sử theo ngữ nghĩa của Gate (chỉ dùng kết quả tool thật)."""
    hist.any[name].append(args)
    if name in state_tools(rs.domain) and not C.succeeded(res):
        return
    hist.conformant[name].append(args)
    C.add_implied(rs, name, args, hist)


def repair(f, binding, hist):
    """Chuỗi model move tối thiểu để công thức tiền điều kiện f được thỏa."""
    if f is None:
        return []
    if isinstance(f, Act):
        if hist.match(f, binding, hist.conformant):
            return []
        args = {k: binding[v] for k, v in f.params.items() if binding.get(v) is not None}
        ask = [k for k, v in f.params.items() if binding.get(v) is None]
        return _dedupe(repair(f.sub, binding, hist) + [Move(f.name, args, ask)])
    if f.kind == "and":
        return _dedupe([m for p in f.parts for m in repair(p, binding, hist)])
    return min((repair(p, binding, hist) for p in f.parts), key=_cost)


def _dedupe(moves):
    seen, out = set(), []
    for m in moves:
        if m.key() not in seen:
            seen.add(m.key())
            out.append(m)
    return out


def align_activation(rs, name, args, hist):
    """Alignment cho lời gọi X=name(args) trên lịch sử hiện tại. Rỗng = không chặn."""
    f = rs.precondition(name)
    if not isinstance(f, Act):
        return []
    binding = {v: args.get(k) for k, v in f.params.items()}
    return repair(f.sub, binding, hist)


# ---------------------------------------------------------------- phản hồi
def describe(domain, tool):
    d = domain_assistant_keys[domain].action_descriptions.get(tool, "")
    return d.split(".")[0] if d else ""


def render_alignment(domain, blocked, moves, observed=None):
    """Phản hồi kiểu `alignment`: chuỗi bước tối thiểu, kèm tham số đã biết và tham số cần hỏi người dùng."""
    lines = [f"BLOCKED: `{blocked}` cannot run yet. Minimal steps to make it allowed, in order:"]
    for i, m in enumerate(moves, 1):
        a = ", ".join(f"{k}={json.dumps(v)}" for k, v in m.args.items())
        ask = f"; ask the user for: {', '.join(m.ask_user)}" if m.ask_user else ""
        lines.append(f"  {i}. call `{m.tool}`({a}){ask}")
    lines.append(f"Then call `{blocked}` again only if every check above succeeds; if a check fails, tell the user the request cannot be completed.")
    if observed:
        lines.append("Results you already have: " + "; ".join(f"{t} -> {r}" for t, r in observed))
    return "\n".join(lines)


def render_template(domain, blocked, moves):
    """Phản hồi kiểu `template` (một câu cho ràng buộc đầu tiên chưa thỏa) — để so sánh độ dài/nội dung."""
    m = moves[0]
    return f"BLOCKED: Precedence violated — you must call `{m.tool}` before `{blocked}`."


# ---------------------------------------------------------------- (1) thống kê trên trace thật
def first_block(rs, interaction):
    hist = C.History()
    for c in C.extract_calls(interaction):
        if c["name"] not in rs.action_params:
            continue
        moves = align_activation(rs, c["name"], c["args"], hist)
        if moves:
            return c, moves
        record(rs, hist, c["name"], c["args"], c["result"])
    return None, None


# ---------------------------------------------------------------- (3) agent lý tưởng
def goal_args(rs):
    node = rs.goal_graph["nodes"][0][1]
    uk = rs.task["user_known"]
    return {k: uk[v] for k, v in node.items() if v in uk}


def ideal_follower(rs, max_rounds=10):
    """Agent chỉ làm theo alignment; tham số cần hỏi lấy từ user_known (người dùng trả lời đúng).
    Sau khi đủ tiền điều kiện, quyết định gọi goal theo kết quả kiểm tra thật (mô phỏng model đọc kết quả đúng)."""
    from env.evaluator import evaluator_function_directed_graph
    env = domain_keys[rs.domain](copy.deepcopy(rs.task["initial_database"]),
                                 domain_assistant_keys[rs.domain].action_innate_dependencies,
                                 rs.task["constraint_parameters"])
    strict = new_strict_system(rs)
    uk = rs.task["user_known"]
    hist, calls, n_blocks = C.History(), [], 0
    gargs = goal_args(rs)

    def do(tool, args):
        try:
            res = copy.deepcopy(getattr(env, tool)(**args))
        except Exception as e:
            res = f"Error: {e}"
        try:
            getattr(strict, tool)(**args)
        except Exception:
            pass
        calls.append({"tool_name": tool, "arguments": args, "content": res})
        record(rs, hist, tool, args, res)
        return res

    refused = False
    for _ in range(max_rounds):
        moves = align_activation(rs, rs.goal, gargs, hist)
        if not moves:
            break
        n_blocks += 1
        for m in moves:
            a = dict(m.args)
            for k in m.ask_user:
                # tham số hỏi người dùng: khớp theo tên tham số trong user_known
                if k in uk:
                    a[k] = uk[k]
            res = do(m.tool, a)
            if m.tool in state_tools(rs.domain) and not C.succeeded(res):
                refused = True             # bước kiểm tra thất bại -> phản hồi bảo từ chối
                break
        if refused:
            break
    else:
        return {"ok": False, "reason": "no_convergence", "blocks": n_blocks}
    try:
        allowed = (not refused) and strict.evaluation_get_dependency_evaluator().process(method_str=rs.goal, **gargs)
    except Exception:
        allowed = False
    if allowed:
        do(rs.goal, gargs)
    ev = evaluator_function_directed_graph(rs.domain, rs.task, [], calls,
                                           {"final_database": env.evaluation_get_database()}, "full")
    reason = "pass" if ev["success"] else ",".join(k for k in ("no_tool_call_error", "constraint_not_violated", "database_match",
                                                             "action_called_correctly", "dirgraph_satisfied") if not ev[k])
    return {"ok": ev["success"], "reason": reason, "blocks": n_blocks, "n_moves": len(calls) - int(allowed)}


# ---------------------------------------------------------------- chạy
def run(domain):
    bad = C.unsolvable(domain)
    data = None
    # (1) lần chặn đầu tiên ở model nhỏ
    stat = collections.defaultdict(collections.Counter)
    example = None
    for key in SMALL:
        p = os.path.join(SOPBENCH, "output", domain, f"ast_{key}{SUFFIX}")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        data = data or d
        for i, t in enumerate(d):
            if i in bad or t["evaluations"][0]["success"]:
                continue
            rs = load_rules(domain, t["task"])
            c, moves = first_block(rs, t["interactions"][0]["interaction"])
            if not moves:
                stat[key]["no_block"] += 1
                continue
            stat[key]["blocked"] += 1
            stat[key][f"len={min(len(moves), 4)}{'+' if len(moves) >= 4 else ''}"] += 1
            stat[key]["needs_user_info"] += any(m.ask_user for m in moves)
            stat[key]["uses_db_dump"] += any(m.tool == DB_DUMP for m in moves)
            if example is None and len(moves) >= 2:
                example = (c["name"], render_alignment(domain, c["name"], moves), render_template(domain, c["name"], moves))
    # (2) lựa chọn nhánh so với trace thành công của model mạnh
    match = collections.Counter()
    for key in STRONG:
        p = os.path.join(SOPBENCH, "output", domain, f"ast_{key}{SUFFIX}")
        if not os.path.exists(p):
            continue
        for i, t in enumerate(json.load(open(p))):
            if i in bad or not t["evaluations"][0]["success"] or not t["task"]["action_should_succeed"]:
                continue
            rs = load_rules(domain, t["task"])
            moves = align_activation(rs, rs.goal, goal_args(rs), C.History())
            called = {c["name"] for c in C.extract_calls(t["interactions"][0]["interaction"])}
            for m in moves:
                match["suggested_used" if m.tool in called else "suggested_not_used"] += 1
    # (3) agent lý tưởng trên mọi task sạch
    ideal = collections.Counter()
    fails = []
    for i, t in enumerate(data or []):
        if i in bad:
            continue
        rs = load_rules(domain, t["task"])
        r = ideal_follower(rs)
        ideal[r["reason"]] += 1
        ideal[f"blocks={r['blocks']}"] += 1
        if not r["ok"] and len(fails) < 5:
            fails.append((i, rs.goal, rs.should_succeed, r["reason"]))
    return stat, match, ideal, fails, example


if __name__ == "__main__":
    domains = sys.argv[1:] or sorted(os.listdir(os.path.join(SOPBENCH, "output")))
    out = {}
    for dom in domains:
        stat, match, ideal, fails, example = run(dom)
        n = sum(v for k, v in ideal.items() if not k.startswith("blocks="))
        print(f"\n===== {dom} =====")
        print(f"  (3) agent lý tưởng theo alignment: pass {ideal['pass']}/{n} = {ideal['pass'] / max(1, n):.1%}   "
              + ", ".join(f"{k}:{v}" for k, v in sorted(ideal.items()) if k != "pass"))
        for f in fails:
            print("      fail:", f)
        tot = match["suggested_used"] + match["suggested_not_used"]
        print(f"  (2) bước alignment đề xuất có trong trace thành công của model mạnh: {match['suggested_used']}/{tot} = {match['suggested_used'] / max(1, tot):.1%}")
        print("  (1) lần chặn đầu tiên trong trace thất bại của model nhỏ:")
        for k, s in stat.items():
            b = s["blocked"]
            print(f"      {k:32s} bị chặn {b:3d} | độ dài sửa " + " ".join(f"{L}:{s[L]}" for L in ("len=1", "len=2", "len=3", "len=4+"))
                  + f" | cần hỏi user {s['needs_user_info'] / max(1, b):.0%} | dùng DB dump {s['uses_db_dump'] / max(1, b):.0%}")
        if example:
            print(f"  Ví dụ phản hồi khi chặn `{example[0]}`:\n    [template] {example[2]}\n    [alignment]\n      " + example[1].replace("\n", "\n      "))
        out[dom] = {"ideal": dict(ideal), "match": dict(match), "first_block": {k: dict(v) for k, v in stat.items()}}
    os.makedirs(C.OUT, exist_ok=True)
    json.dump(out, open(os.path.join(C.OUT, "alignment_summary.json"), "w"), indent=1, ensure_ascii=False)
