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

BẢNG TRƯỜNG SOPBench -> THÀNH PHẦN DECLARE (đọc phần này trước):
  task["user_goal"]                 -> target (action kích hoạt) của mọi ràng buộc; RuleSet.goal
  task["directed_action_graph"]     -> cây tiền điều kiện ở mức tool -> Precedence / Branched / Choice / Chain
      graph["nodes"][i] là str "and"/"or"  -> Op (toán tử logic)
      graph["nodes"][i] là (tool, params)  -> Act (một tool; params = tham số dùng chung với cha -> tương quan MP-DECLARE)
      graph connections (conns[i])         -> danh sách con của node i = tiền điều kiện của nó
  task["constraints"]               -> cây vị từ dữ liệu của goal -> DataCondition (chỉ vị từ loại "data")
      nút "single" (có thể có tiền tố "not ") là lá; "and"/"or"/"chain"/"gate" là nút trong (OPS)
  task["action_should_succeed"]     -> True: Existence(goal); False: Absence(goal thành công)
  task["constraint_parameters"]     -> tham số cho vị từ khi phát lại trên hệ thống strict
  task["initial_database"]          -> DB ban đầu để phát lại (chỉ phân tích offline, KHÔNG đưa cho Gate)
  get_default_dep_full(domain)      -> cây vị từ mặc định cho action KHÔNG phải goal (RuleSet.dep_full)
  <d>_assistant.constraint_links    -> vị từ "state" (login, xác thực): nối vị từ với tool tạo trạng thái -> Precedence
  <d>_assistant.constraint_processes-> vị từ "data": nhóm tool cho agent 'thấy' giá trị vị từ (verifying_tools)
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
    """Node tool trong DAG: nodes[i] = (tên_tool, params)."""
    name: str             # nodes[i][0]: tên tool -> tên activity trong DECLARE
    params: dict          # nodes[i][1]: tham số của Y -> tên biến dùng chung với X (điều kiện tương quan MP-DECLARE)
    sub: object = None    # các con của node trong DAG = tiền điều kiện của chính Y (Chain)


@dataclass
class Op:
    """Node toán tử trong DAG: nodes[i] là chuỗi "and" / "or"."""
    kind: str             # "and" | "or"
    parts: list           # các con của node (conns[i]) đã biên dịch


def _compile(nodes, conns, i):
    """Biên dịch node thứ i của DAG thành cây Act/Op.
    nodes: graph["nodes"]; conns[i]: tập chỉ số các node con của i (cạnh "i cần các con của nó")."""
    node = nodes[i]
    if isinstance(node, str):                 # node toán tử -> Op, con giữ nguyên cấu trúc
        return Op(node, [_compile(nodes, conns, c) for c in sorted(conns[i])])
    name, params = node                       # node tool -> Act
    kids = [_compile(nodes, conns, c) for c in sorted(conns[i])]
    # 0 con: không có tiền điều kiện; 1 con: dùng thẳng; nhiều con trực tiếp (không qua node and/or): ngầm hiểu là "and"
    sub = None if not kids else kids[0] if len(kids) == 1 else Op("and", kids)
    return Act(name, dict(params or {}), sub)


def graph_formula(graph):
    """DAG của SOPBench -> (Act gốc, inv_nodes). Gốc là action được kích hoạt."""
    # conns: node -> các con; inv: tên tool -> chỉ số node đầu tiên của tool đó. Node 0 luôn là gốc (action được kích hoạt).
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
    target: str           # activation: action bị ràng buộc (X); với Existence/Absence/DataCondition là user_goal
    sources: tuple = ()   # tên tool (hoặc nhóm) phải xảy ra trước (Y); rỗng với Existence/Absence/DataCondition
    detail: str = ""      # Choice: biểu thức DNF dạng chuỗi; DataCondition: tên vị từ (có thể kèm "not ")

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
        if isinstance(f, Act):                      # con là một tool Y         -> Precedence(Y, X)
            out.append(Constraint("Precedence", act.name, (f.name,)))
        elif f.kind == "and":                       # node "and"                -> tách thành các ràng buộc độc lập
            stack.extend(f.parts)
        elif all(isinstance(p, Act) for p in f.parts):   # "or", mọi nhánh là tool -> Branched({Y,Z,..}, X)
            out.append(Constraint("BranchedPrecedence", act.name, tuple(p.name for p in f.parts)))
        else:                                       # "or" có nhánh phức hợp    -> Choice (DNF dạng chuỗi)
            out.append(Constraint("ChoicePrecedence", act.name, (_dnf_str(f),)))
    # đệ quy xuống từng tool Y: tiền điều kiện của Y thành ràng buộc riêng trên Y (Chain)
    for y in _acts(act.sub):
        constraints_of(y, out)
    return out


# ---------------------------------------------------------------- vị từ dữ liệu
def pred_leaves(dep):
    """Lấy các lá của cây vị từ. dep = (loại, nội_dung): ("single", "tên_vị_từ") là lá;
    ("and"|"or"|"chain"|"gate", [con...]) là nút trong."""
    if not dep:
        return []
    if dep[0] == "single":
        return [dep]
    return [x for d in dep[1] for x in pred_leaves(d)]


def pred_name(leaf):
    """leaf = ("single", "not tên_vị_từ") -> "tên_vị_từ" (bỏ phủ định; phủ định chỉ đổi kết luận, không đổi tool cần kiểm)."""
    return leaf[1].replace("not ", "")


def verifying_tools(domain, pred):
    """Các tool cho agent 'thấy' giá trị của vị từ (để phân biệt 'chưa kiểm tra' và 'kiểm tra rồi vẫn làm')."""
    da = domain_assistant_keys[domain]
    tools = set()
    if pred in da.constraint_links:            # vị từ trạng thái: tool tạo trạng thái (vd login_user); có thể là tuple (tool, ...)
        cl = da.constraint_links[pred]
        tools.add(cl[0] if isinstance(cl, tuple) else cl)
    if pred in getattr(da, "constraint_processes", {}) and da.constraint_processes[pred]:
        # vị từ dữ liệu: cây vị từ thay thế -> các tool đọc dữ liệu cho phép tự đánh giá vị từ
        tools |= {pred_name(l) for l in pred_leaves(da.constraint_processes[pred])}
    if pred in da.action_descriptions:         # chính vị từ trùng tên một tool (vd get_account_balance)
        tools.add(pred)
    return tools


def pred_kind(domain, pred):
    """state: được Precedence trên tool liên kết bao phủ; data: điều kiện dữ liệu (MP-DECLARE)."""
    return "state" if pred in domain_assistant_keys[domain].constraint_links else "data"


# ---------------------------------------------------------------- load_rules
@dataclass
class RuleSet:
    domain: str
    task: dict                          # nguyên dict task trong data/<domain>_tasks.json
    goal: str                           # task["user_goal"]
    should_succeed: bool                # task["action_should_succeed"] -> Existence (True) / Absence (False)
    goal_graph: dict                    # task["directed_action_graph"] (bản sao) -> Precedence/Branched/Choice/Chain
    dep_full: dict                      # cây vị từ cho mọi action (goal đã thay bằng task["constraints"])
    action_params: dict                 # tên tham số của từng action (để khớp tương quan tham số)
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
        # (1) luồng điều khiển: DAG của task -> Precedence / Branched / Choice (kể cả Chain lồng nhau)
        root, _ = graph_formula(self.goal_graph)
        cs = constraints_of(root)
        # (2) điều kiện dữ liệu: lá của task["constraints"] loại "data" -> DataCondition (MP-DECLARE activation condition).
        #     Lá loại "state" đã được phủ bởi Precedence ở (1) nên bỏ qua.
        for leaf in pred_leaves(self.task["constraints"]):
            p = pred_name(leaf)
            if pred_kind(self.domain, p) == "data":
                cs.append(Constraint("DataCondition", self.goal, (), leaf[1]))
        # (3) nghĩa vụ: action_should_succeed quyết định goal phải xảy ra hay không được thành công
        cs.append(Constraint("Existence" if self.should_succeed else "Absence", self.goal))
        return list(dict.fromkeys(cs))


def load_rules(domain: str, task: dict) -> RuleSet:
    dep_full = get_default_dep_full(domain, "full")   # luật mặc định của domain cho MỌI action
    dep_full[task["user_goal"]] = task["constraints"]  # riêng goal: ghi đè bằng luật của task (đúng SOP agent nhận)
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
