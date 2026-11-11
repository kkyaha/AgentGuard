"""Conformance checking DECLARE/MP-DECLARE trên trajectory công bố của SOPBench (giai đoạn 1).

Dùng: .venv/bin/python analysis/conformance.py [domain ...]
Ra:   analysis/out/conformance_<domain>.json  (vi phạm từng trace) + bảng tóm tắt + độ khớp với oracle.
"""
from __future__ import annotations
import ast, collections, copy, glob, json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from declare_rules import (SOPBENCH, Act, Op, load_rules, new_strict_system, pred_leaves, pred_name,  # noqa: E402
                           pred_kind, verifying_tools, domain_assistant_keys)
from failure_taxonomy import SMALL, STRONG, SUFFIX  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "out")


# ---------------------------------------------------------------- trích tool call giống run_evaluation.py
def try_eval(s):
    if not isinstance(s, str):
        return s
    try:
        return ast.literal_eval(s)
    except Exception:
        return s


def extract_calls(interaction):
    calls = []
    for i in range(len(interaction) - 1):
        tcs = [tc for tc in (interaction[i].get("tool_calls") or [])
               if tc["function"]["name"].lower() not in ("n/a", "na", "none", "null")]
        if tcs and "tool_name" in interaction[i + 1]:
            args = try_eval(tcs[0]["function"]["arguments"])
            calls.append({"name": interaction[i + 1]["tool_name"],
                          "args": args if isinstance(args, dict) else {},
                          "result": try_eval(interaction[i + 1]["content"])})
    return calls


def succeeded(res):
    if isinstance(res, bool):
        return res
    if isinstance(res, (tuple, list)) and res and isinstance(res[0], bool):
        return res[0]
    return False


def norm(v):
    return json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v


# ---------------------------------------------------------------- kiểm Precedence (ngữ nghĩa giống oracle)
class History:
    """Các lời gọi 'hợp lệ' (thỏa tiền điều kiện lúc gọi) và mọi lời gọi, theo tên tool."""
    def __init__(self):
        self.conformant = collections.defaultdict(list)   # name -> [args]
        self.any = collections.defaultdict(list)

    def match(self, act: Act, binding: dict, pool):
        exp = {k: binding.get(v) for k, v in act.params.items()}
        for args in pool.get(act.name, []):
            if all(exp[k] is None or norm(args.get(k)) == norm(exp[k]) for k in exp):
                return True
        return False


def unsatisfied(f, binding, hist):
    """Trả về danh sách vi phạm tối thiểu của công thức tiền điều kiện f (rỗng = thỏa)."""
    if f is None:
        return []
    if isinstance(f, Act):
        if hist.match(f, binding, hist.conformant):
            return []
        if hist.match(f, binding, hist.any):
            kind = "unconformant"          # Y đã gọi nhưng chính Y vi phạm tiền điều kiện (Chain)
        elif f.name in hist.any:
            kind = "param_mismatch"        # Y đã gọi nhưng với tham số khác
        else:
            kind = "missing"
        return [("Precedence", (f.name,), kind)]
    if f.kind == "and":
        return [v for p in f.parts for v in unsatisfied(p, binding, hist)]
    # or
    sub = [unsatisfied(p, binding, hist) for p in f.parts]
    if any(not s for s in sub):
        return []
    names = tuple(sorted({a.name for p in f.parts for a in _acts(p)}))
    tpl = "BranchedPrecedence" if all(isinstance(p, Act) for p in f.parts) else "ChoicePrecedence"
    kinds = {k for s in sub for (_, _, k) in s}
    return [(tpl, names, "missing" if kinds == {"missing"} else "partial")]


def _acts(f):
    return [f] if isinstance(f, Act) else [a for p in f.parts for a in _acts(p)]


def add_implied(rs, name, args, hist):
    """Gọi X hợp lệ ngụ ý các phụ thuộc bẩm sinh của X đã được kiểm (oracle cũng làm vậy)."""
    da = domain_assistant_keys[rs.domain]
    dep = da.action_innate_dependencies.get(name)
    # Oracle (dfsgather_allfunccalled_indepperm) chỉ xét nhánh đầu của and/or — giữ nguyên để đối chiếu.
    while dep and dep[0] != "single":
        dep = dep[1][0] if dep[1] else None
    if not dep:
        return
    p = pred_name(dep)
    if p in rs.action_params:
        leaves = [("single", p, dep[2])]
    elif p in getattr(da, "constraint_processes", {}):
        leaves = [(l[0], pred_name(l), {k: (dep[2] or {}).get(v, v) for k, v in (l[2] or {}).items()})
                  for l in pred_leaves(da.constraint_processes[p])]
    else:
        return
    for _, tool, pm in leaves:
        if tool in rs.action_params:
            mapped = {k: args.get(v) for k, v in (pm or {}).items()}
            hist.conformant[tool].append(mapped)
            hist.any[tool].append(mapped)


# ---------------------------------------------------------------- phát lại một trace
def check_trace(rs, interaction):
    calls = extract_calls(interaction)
    strict = new_strict_system(rs)
    dep_eval = strict.evaluation_get_dependency_evaluator()
    hist = History()
    seen = set()                                   # tool đã gọi (để biết agent đã 'thấy' vị từ chưa)
    viol = []
    tool_error = False
    strict_rejected = False
    goal_success = False
    for step, c in enumerate(calls):
        name, args, res = c["name"], c["args"], c["result"]
        if name not in rs.action_params:
            seen.add(name)
            continue
        # --- control-flow: Precedence / Branched / Choice
        f = rs.precondition(name)
        node_params = f.params if isinstance(f, Act) else {}
        binding = {v: args.get(k) for k, v in node_params.items()}
        miss = unsatisfied(f.sub if isinstance(f, Act) else None, binding, hist)
        for tpl, src, kind in miss:
            viol.append({"step": step, "template": tpl, "target": name, "sources": list(src), "kind": kind,
                         "is_goal": name == rs.goal})
        # --- data: MP-DECLARE activation condition, đánh giá trên hệ thống strict tại thời điểm gọi
        try:
            allowed = dep_eval.process(method_str=name, **args)
        except Exception:
            allowed, tool_error = None, True
        if allowed is False and res is not False and not (isinstance(res, (tuple, list)) and res and res[0] is False):
            strict_rejected = True                 # cùng định nghĩa với constraint_not_violated của oracle
        if allowed is False and succeeded(res):
            for leaf in pred_leaves(rs.dep_full.get(name)):
                try:
                    ok = dep_eval._process(leaf, **args)
                except Exception:
                    continue
                if ok:
                    continue
                p = pred_name(leaf)
                if pred_kind(rs.domain, p) == "state":
                    continue                       # đã được Precedence trên tool liên kết bao phủ
                observed = bool(verifying_tools(rs.domain, p) & seen)
                viol.append({"step": step, "template": "DataCondition", "target": name, "sources": [leaf[1]],
                             "kind": "checked_ignored" if observed else "unchecked", "is_goal": name == rs.goal})
        # --- cập nhật trạng thái
        if not miss:
            hist.conformant[name].append(args)
            add_implied(rs, name, args, hist)
        hist.any[name].append(args)
        seen.add(name)
        if hasattr(strict, name):                  # tool chỉ có ở hệ thống thường: oracle bỏ qua (status 1)
            try:
                getattr(strict, name)(**args)
            except Exception:
                tool_error = True
        if name == rs.goal and succeeded(res):
            goal_success = True
    if rs.should_succeed and not goal_success:
        attempted = any(c["name"] == rs.goal for c in calls)
        viol.append({"step": len(calls), "template": "Existence", "target": rs.goal, "sources": [],
                     "kind": "attempted_failed" if attempted else "never_attempted", "is_goal": True})
    if not rs.should_succeed and goal_success:
        if not any(v["template"] == "DataCondition" and v["is_goal"] for v in viol):
            viol.append({"step": len(calls), "template": "Absence", "target": rs.goal, "sources": [],
                         "kind": "executed", "is_goal": True})
    return {"n_calls": len(calls), "violations": viol, "tool_error": tool_error, "strict_rejected": strict_rejected}


# ---------------------------------------------------------------- chạy theo domain
# Goal có tool không được khai báo schema trong bank_assistant.py → agent không thể gọi (lỗi benchmark).
BROKEN_GOALS = {"bank": {"cancel_credit_card", "pay_bill_with_credit_card"}}


def unsolvable(domain):
    ok, n, goals = collections.Counter(), None, {}
    for p in glob.glob(os.path.join(SOPBENCH, "output", domain, "ast_*-tool_full-shuffle_False.json")):
        d = json.load(open(p))
        if not all(t.get("evaluations") for t in d) or (n is not None and len(d) != n):
            continue
        n = len(d)
        for i, t in enumerate(d):
            ok[i] += t["evaluations"][0]["success"]
            goals[i] = t["task"]["user_goal"]
    return {i for i in range(n or 0) if ok[i] == 0 or goals[i] in BROKEN_GOALS.get(domain, ())}


def first_label(v):
    if not v:
        return "conform"
    x = min(v, key=lambda e: e["step"])
    return f'{x["template"]}:{x["kind"]}' + ("" if x["is_goal"] or x["template"] in ("Existence", "Absence") else "@aux")


def run(domain):
    bad = unsolvable(domain)
    rows, per_trace = {}, []
    agree = collections.Counter()
    for key in SMALL + STRONG:
        p = os.path.join(SOPBENCH, "output", domain, f"ast_{key}{SUFFIX}")
        if not os.path.exists(p):
            continue
        data = json.load(open(p))
        if not all(t.get("evaluations") for t in data):
            continue
        cnt_first, cnt_any, n, ok = collections.Counter(), collections.Counter(), 0, 0
        for i, t in enumerate(data):
            if i in bad:
                continue
            rs = load_rules(domain, t["task"])
            ev = t["evaluations"][0]
            r = check_trace(rs, t["interactions"][0]["interaction"])
            v = r["violations"]
            n += 1
            ok += ev["success"]
            prec = any(x["template"].endswith("Precedence") for x in v)
            agree[("dirgraph", prec == (not ev["dirgraph_satisfied"]))] += 1
            agree[("constraint", r["strict_rejected"] == (not ev["constraint_not_violated"]))] += 1
            agree[("success", (not v and not r["tool_error"]) == ev["success"])] += 1
            if not ev["success"]:
                cnt_first[first_label(v)] += 1
                for tpl in {x["template"] + ":" + x["kind"] for x in v}:
                    cnt_any[tpl] += 1
            per_trace.append({"model": key, "task": i, "goal": rs.goal, "should_succeed": rs.should_succeed,
                              "oracle_success": ev["success"], **r})
        rows[key] = {"n": n, "pass": ok, "first": dict(cnt_first), "any": dict(cnt_any)}
    return rows, per_trace, agree, bad


def report(domain, rows, agree, bad):
    print(f"\n===== {domain}  (loại {len(bad)} task không giải được) =====")
    for k in ("dirgraph", "constraint", "success"):
        a, b = agree[(k, True)], agree[(k, False)]
        print(f"  khớp oracle [{k:10s}]: {a}/{a + b} = {a / max(1, a + b):.1%}")
    labels = sorted({l for r in rows.values() for l in r["first"]})
    print("  Vi phạm ĐẦU TIÊN trong trace thất bại (theo template:kiểu):")
    print(f"  {'model':34s} pass  " + " ".join(f"{l[:22]:>22s}" for l in labels))
    for k, r in rows.items():
        print(f"  {k:34s} {r['pass'] / r['n']:5.1%} " + " ".join(f"{r['first'].get(l, 0):22d}" for l in labels))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    domains = sys.argv[1:] or sorted(os.listdir(os.path.join(SOPBENCH, "output")))
    for d in domains:
        rows, per_trace, agree, bad = run(d)
        report(d, rows, agree, bad)
        json.dump({"rows": rows, "excluded_tasks": sorted(bad),
                   "agreement": {f"{k}:{v}": c for (k, v), c in agree.items()}, "traces": per_trace},
                  open(os.path.join(OUT, f"conformance_{d}.json"), "w"), indent=1, ensure_ascii=False, default=str)
