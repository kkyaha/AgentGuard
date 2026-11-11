"""Chuyển luật SOPBench sang DECLARE / MP-DECLARE.

Nguồn luật (đã đối chiếu với env/evaluator.py):
  * Luồng điều khiển: DAG AND/OR ở mức tool. user_goal dùng task["directed_action_graph"];
    action khác dùng env.helpers.dfsgather_ifg_func(..., "full") — giống oracle.
  * Điều kiện dữ liệu: cây vị từ task["constraints"] (user_goal) và get_default_dep_full (action khác),
    đánh giá bằng phát lại trên hệ thống strict của SOPBench.

Ánh xạ:
  node tool X, con là tool Y          -> Precedence(Y, X)            (+ tương quan tham số)
  con "and"                           -> nhiều ràng buộc độc lập
  con "or", mọi nhánh là tool         -> BranchedPrecedence({Y..}, X)
  con "or", có nhánh phức hợp         -> ChoicePrecedence (DNF; ngoài DECLARE chuẩn)
  tool lồng nhau (Chain)              -> ràng buộc riêng trên chính Y
  vị từ dữ liệu của X                 -> MP-DECLARE activation condition
  action_should_succeed               -> Existence(goal) | Absence(goal thành công)
"""
from __future__ import annotations
import copy, os, sys
from dataclasses import dataclass, field

SOPBENCH = os.environ.get("SOPBENCH", os.path.join(os.path.dirname(__file__), "..", "external", "SOPBench"))
sys.path.insert(0, os.path.abspath(SOPBENCH))

from env.variables import domain_keys, domain_assistant_keys  # noqa: E402
from env.task import get_default_dep_full                     # noqa: E402
from env.helpers import dfsgather_ifg_func, get_ifg_connections_invnodes, get_action_parameters  # noqa: E402

OPS = ("single", "and", "or", "chain", "gate")


# ---------------------------------------------------------------- công thức tiền điều kiện
@dataclass
class Act:
    name: str
    params: dict          # tham số của Y -> tên biến dùng chung với X
    sub: object = None    # công thức tiền điều kiện của chính Y trong DAG (Chain)


@dataclass
class Op:
    kind: str             # "and" | "or"
    parts: list


def _compile(nodes, conns, i):
    node = nodes[i]
    if isinstance(node, str):
        return Op(node, [_compile(nodes, conns, c) for c in sorted(conns[i])])
    name, params = node
    kids = [_compile(nodes, conns, c) for c in sorted(conns[i])]
    sub = None if not kids else kids[0] if len(kids) == 1 else Op("and", kids)
    return Act(name, dict(params or {}), sub)


def graph_formula(graph):
    """DAG của SOPBench -> (Act gốc, inv_nodes). Gốc là action được kích hoạt."""
    conns, inv = get_ifg_connections_invnodes(graph)
    return _compile(graph["nodes"], conns, 0), inv


def graph_node_formula(graph, action):
    """Công thức tiền điều kiện của `action` theo node đầu tiên của nó trong DAG (cách oracle làm)."""
    conns, inv = get_ifg_connections_invnodes(graph)
    if action not in inv:
        return None
    return _compile(graph["nodes"], conns, inv[action])


# ---------------------------------------------------------------- liệt kê template DECLARE
@dataclass(frozen=True)
class Constraint:
    template: str         # Precedence | BranchedPrecedence | ChoicePrecedence | Existence | Absence | DataCondition
    target: str
    sources: tuple = ()   # tên tool (hoặc nhóm) phải xảy ra trước
    detail: str = ""

    def __str__(self):
        s = "|".join(self.sources)
        return f"{self.template}({s + ', ' if s else ''}{self.target}){' [' + self.detail + ']' if self.detail else ''}"


def _acts(f):
    if isinstance(f, Act):
        return [f]
    return [a for p in f.parts for a in _acts(p)]


def _dnf_str(f):
    if isinstance(f, Act):
        return f.name
    j = " & " if f.kind == "and" else " | "
    return "(" + j.join(_dnf_str(p) for p in f.parts) + ")"


def constraints_of(act: Act, out=None):
    """Sinh các ràng buộc DECLARE từ một node tool và các tiền điều kiện lồng nhau của nó."""
    out = [] if out is None else out
    if act.sub is None:
        return out
    stack = [act.sub]
    while stack:
        f = stack.pop()
        if isinstance(f, Act):
            out.append(Constraint("Precedence", act.name, (f.name,)))
        elif f.kind == "and":
            stack.extend(f.parts)
        elif all(isinstance(p, Act) for p in f.parts):
            out.append(Constraint("BranchedPrecedence", act.name, tuple(p.name for p in f.parts)))
        else:
            out.append(Constraint("ChoicePrecedence", act.name, (_dnf_str(f),)))
    for y in _acts(act.sub):
        constraints_of(y, out)
    return out


# ---------------------------------------------------------------- vị từ dữ liệu
def pred_leaves(dep):
    if not dep:
        return []
    if dep[0] == "single":
        return [dep]
    return [x for d in dep[1] for x in pred_leaves(d)]


def pred_name(leaf):
    return leaf[1].replace("not ", "")


def verifying_tools(domain, pred):
    """Các tool cho agent 'thấy' giá trị của vị từ (để phân biệt 'chưa kiểm tra' và 'kiểm tra rồi vẫn làm')."""
    da = domain_assistant_keys[domain]
    tools = set()
    if pred in da.constraint_links:
        cl = da.constraint_links[pred]
        tools.add(cl[0] if isinstance(cl, tuple) else cl)
    if pred in getattr(da, "constraint_processes", {}) and da.constraint_processes[pred]:
        tools |= {pred_name(l) for l in pred_leaves(da.constraint_processes[pred])}
    if pred in da.action_descriptions:
        tools.add(pred)
    return tools


def pred_kind(domain, pred):
    """state: được Precedence trên tool liên kết bao phủ; data: điều kiện dữ liệu (MP-DECLARE)."""
    return "state" if pred in domain_assistant_keys[domain].constraint_links else "data"


# ---------------------------------------------------------------- load_rules
@dataclass
class RuleSet:
    domain: str
    task: dict
    goal: str
    should_succeed: bool
    goal_graph: dict
    dep_full: dict                      # cây vị từ cho mọi action (goal đã thay bằng task["constraints"])
    action_params: dict
    _graph_cache: dict = field(default_factory=dict)

    def graph_for(self, action):
        """DAG dùng để kiểm Precedence cho `action` (task graph nếu action có trong đó, như oracle)."""
        _, inv = get_ifg_connections_invnodes(self.goal_graph)
        if action in inv:
            return self.goal_graph
        if action not in self._graph_cache:
            ds = domain_keys[self.domain + "_strict"]().evaluation_get_domain_system()
            self._graph_cache[action] = dfsgather_ifg_func(ds, domain_assistant_keys[self.domain], action, "full", False)
        return self._graph_cache[action]

    def precondition(self, action):
        g = self.graph_for(action)
        return graph_node_formula(g, action) if g else None

    def declare(self):
        """Toàn bộ mô hình DECLARE của task (để báo cáo / sinh phản hồi)."""
        root, _ = graph_formula(self.goal_graph)
        cs = constraints_of(root)
        for leaf in pred_leaves(self.task["constraints"]):
            p = pred_name(leaf)
            if pred_kind(self.domain, p) == "data":
                cs.append(Constraint("DataCondition", self.goal, (), leaf[1]))
        cs.append(Constraint("Existence" if self.should_succeed else "Absence", self.goal))
        return list(dict.fromkeys(cs))


def load_rules(domain: str, task: dict) -> RuleSet:
    dep_full = get_default_dep_full(domain, "full")
    dep_full[task["user_goal"]] = task["constraints"]
    ds = domain_keys[domain + "_strict"]().evaluation_get_domain_system()
    return RuleSet(domain, task, task["user_goal"], task["action_should_succeed"],
                   copy.deepcopy(task["directed_action_graph"]), dep_full,
                   get_action_parameters(ds, domain_assistant_keys[domain]))


def new_strict_system(rs: RuleSet):
    """Hệ thống strict của SOPBench với DB ban đầu của task (dùng để đánh giá điều kiện dữ liệu khi phát lại)."""
    return domain_keys[rs.domain + "_strict"](
        copy.deepcopy(rs.task["initial_database"]),
        domain_assistant_keys[rs.domain].action_innate_dependencies,
        copy.deepcopy(rs.dep_full), rs.task["constraint_parameters"])


if __name__ == "__main__":
    import json
    dom = sys.argv[1] if len(sys.argv) > 1 else "bank"
    data = json.load(open(os.path.join(SOPBENCH, "data", f"{dom}_tasks.json")))
    for goal, tasks in list(data.items())[:3]:
        rs = load_rules(dom, tasks[0])
        print(f"\n# {goal} (should_succeed={rs.should_succeed})")
        for c in rs.declare():
            print("  ", c)
