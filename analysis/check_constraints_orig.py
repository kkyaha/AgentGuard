"""Kiểm tra: luật Gate dùng (task["constraints"]) có cùng ngữ nghĩa với luật đưa vào prompt (task["constraints_original"]).

SOPBench dựng prompt từ constraints_original (env/task.py: task_initializer, dependency_verb_dep_orig=True),
còn oracle / directed_action_graph / Gate dùng constraints. Giả thuyết: constraints = constraints_original sau khi chèn
constraint_dependencies (env.helpers.dfsins_constr_deps), tức chỉ làm tường minh phụ thuộc đã có ở mức domain.

Chạy: .venv/bin/python analysis/check_constraints_orig.py
"""
import json, os, sys

SOPBENCH = os.environ.get("SOPBENCH", os.path.join(os.path.dirname(__file__), "..", "external", "SOPBench"))
sys.path.insert(0, os.path.abspath(SOPBENCH))
os.chdir(SOPBENCH)
from env.variables import domain_assistant_keys  # noqa: E402
from env.helpers import dfsins_constr_deps, dfsprune_dep_pro, hashable_dep  # noqa: E402

DOMAINS = ["bank", "dmv", "healthcare", "hotel", "library", "online_market", "university"]


def norm(d):
    return hashable_dep(tuple(d) if isinstance(d, list) else d) if d else None


def tup(d):
    if isinstance(d, list):
        return tuple(tup(x) for x in d)
    if isinstance(d, dict):
        return {k: tup(v) for k, v in d.items()}
    return d


tot = {"n": 0, "same": 0, "expanded": 0, "other": 0}
for dom in DOMAINS:
    da = domain_assistant_keys[dom]
    cd = getattr(da, "constraint_dependencies", {}) or {}
    tasks = json.load(open(f"data/{dom}_tasks.json"))
    c = {"n": 0, "same": 0, "expanded": 0, "other": 0}
    bad = []
    for g, arr in tasks.items():
        for j, t in enumerate(arr):
            c["n"] += 1
            a, o = tup(t["constraints"]), tup(t["constraints_original"])
            if a == o:
                c["same"] += 1
                continue
            try:
                e = dfsins_constr_deps(o, {}, cd)
            except Exception as ex:
                e = None
            # so sau khi rút gọn cả hai phía bằng chính hàm của SOPBench (A ∧ chain(A, B) ≡ chain(A, B))
            if e is not None and norm(e) in (norm(a), norm(dfsprune_dep_pro(a))):
                c["expanded"] += 1
            else:
                c["other"] += 1
                bad.append((g, j))
    for k in tot:
        tot[k] += c[k]
    print(f"{dom:14s} n={c['n']:4d} giống={c['same']:4d} chỉ_chèn_constraint_dependencies={c['expanded']:4d} khác={c['other']:4d}"
          + (f"  vd: {bad[:5]}" if bad else ""))
print(f"{'TỔNG':14s} n={tot['n']:4d} giống={tot['same']:4d} chỉ_chèn_constraint_dependencies={tot['expanded']:4d} khác={tot['other']:4d}")
