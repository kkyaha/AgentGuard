"""Gate tất định (cách 1): chỉ ép nhóm Precedence, trạng thái chỉ cập nhật từ kết quả tool thật.

Dùng phần lõi đã kiểm định ở giai đoạn 1 (analysis/alignment.py, analysis/conformance.py).
Sẽ tách hẳn khỏi analysis/ khi tái cấu trúc frameguard/ + adapters/.
"""
import collections, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis"))
import conformance as C  # noqa: E402
from alignment import align_activation, record, state_tools, repair, _cost  # noqa: E402
from declare_rules import Act, Op  # noqa: E402
from frameguard.feedback import render  # noqa: E402


def _contains(f, name):
    """X xuất hiện ở bất kỳ đâu trong công thức (kể cả tiền điều kiện lồng nhau của một Act)."""
    if f is None:
        return False
    if isinstance(f, Act):
        return f.name == name or _contains(f.sub, name)
    return any(_contains(p, name) for p in f.parts)


def _repair_avoid(f, binding, hist, avoid):
    """Như alignment.repair nhưng ở nhánh `or` bỏ các nhánh cần tool trong `avoid` (nếu còn nhánh khác)."""
    if f is None:
        return []
    if isinstance(f, Op) and f.kind == "or":
        opts = [_repair_avoid(p, binding, hist, avoid) for p in f.parts]
        ok = [o for o in opts if not any(m.tool in avoid for m in o)]
        return min(ok or opts, key=_cost)
    if isinstance(f, Op):
        out, seen = [], set()
        for p in f.parts:
            for m in _repair_avoid(p, binding, hist, avoid):
                if m.key() not in seen:
                    seen.add(m.key())
                    out.append(m)
        return out
    if hist.match(f, binding, hist.conformant):
        return []
    return _repair_avoid(f.sub, binding, hist, avoid) + repair(Act(f.name, f.params, None), binding, hist)


def _ginfo_log(g):
    if not g:
        return None
    return {k: ([m.tool for m in v] if k == "goal_steps" else v) for k, v in g.items()}


class Gate:
    def __init__(self, rules, mode):
        self.rs, self.mode = rules, mode
        self.hist = C.History()
        self.blocked_counts = collections.Counter()
        self.log = []                       # một dòng cho mỗi tool call đi qua Gate

    def check(self, name, args):
        """Trả về tin nhắn phản hồi nếu chặn, None nếu cho chạy."""
        if name not in self.rs.action_params or not isinstance(args, dict):
            return None
        moves = align_activation(self.rs, name, args, self.hist)
        if not moves:
            return None
        if self.mode == "none":
            # chế độ bóng: ghi lại "lẽ ra chặn ở đâu" để so với các chế độ có Gate, nhưng không chặn
            self.log.append({"tool": name, "args": args, "decision": "would_block", "repair": [m.tool for m in moves]})
            return None
        f = self.rs.precondition(name)
        binding = {v: args.get(k) for k, v in f.params.items()} if isinstance(f, Act) else {}
        viol = C.unsatisfied(f.sub if isinstance(f, Act) else None, binding, self.hist)
        st = state_tools(self.rs.domain)
        failed = [m.tool for m in moves if m.tool in st and m.tool in self.hist.any]
        alt = self.alternative(name, args)
        key = (name, C.norm(args))
        self.blocked_counts[key] += 1
        ginfo = None
        if self.mode == "goal":
            ginfo = self.goal_info(name, args, failed)
        elif self.mode == "purpose":
            ginfo = {"required_by": self.required_by(name)}
        msg = render(self.mode, name, viol, moves, failed, alt, ginfo)
        self.log.append({"tool": name, "args": args, "decision": "blocked",
                         "violations": [list(v[:1]) + [list(v[1])] + [v[2]] for v in viol],
                         "repair": [m.tool for m in moves], "alternative": [m.tool for m in alt],
                         "failed_state": failed, "repeat_index": self.blocked_counts[key], "message": msg,
                         "goal_info": _ginfo_log(ginfo)})
        return msg

    # ------------------------------------------------------------ phản hồi theo goal
    def _seen_values(self, args):
        """Giá trị tham số đã xuất hiện trong các lời gọi (để điền tham số cho các bước của goal)."""
        seen = {}
        for e in self.log:
            if isinstance(e.get("args"), dict):
                seen.update({k: v for k, v in e["args"].items() if v is not None})
        seen.update({k: v for k, v in args.items() if v is not None})
        return seen

    def goal_info(self, name, args, failed):
        """Chế độ `goal` (Gate biết loại yêu cầu G). So lời gọi bị chặn X với mô hình ràng buộc của G:
        - needed   : X có trên một đường tới G (có thể trong nhánh `or`)
        - not_needed: X không nằm trong tiền điều kiện của G → chỉ ra các bước còn thiếu của G (rỗng = gọi G được)
        Chuỗi bước của G tránh tool tạo trạng thái đã thất bại (vd login_user trả False) nếu có nhánh khác."""
        G = self.rs.goal
        if name == G:
            return {"goal": G, "relation": "is_goal"}
        g = self.rs.precondition(G)
        sub = g.sub if isinstance(g, Act) else None
        binding = self._seen_values(args)
        steps = _repair_avoid(sub, binding, self.hist, set(failed)) if sub is not None else []
        rel = "needed" if _contains(sub, name) else "not_needed"
        return {"goal": G, "relation": rel, "goal_steps": steps}

    def required_by(self, name):
        """Chế độ `purpose` (không biết goal): các action của domain có X trong tiền điều kiện (Precedence ngược)."""
        out = []
        for a in sorted(self.rs.action_params):
            if a == name:
                continue
            f = self.rs.precondition(a)
            if isinstance(f, Act) and _contains(f.sub, name):
                out.append(a)
        return out

    def alternative(self, name, args):
        """Đường thay thế cho tool phụ bị chặn, lấy từ nhánh `or` (Branched/Choice Precedence) của goal.
        Ví dụ: pay_loan cần (get_account_balance | internal_get_database); get_account_balance cần login_user
        → nếu không đăng nhập được thì dùng internal_get_database. Trả [] nếu không có."""
        if name == self.rs.goal:
            return []
        g = self.rs.precondition(self.rs.goal)
        if not isinstance(g, Act) or g.sub is None:
            return []
        f = self.rs.precondition(name)
        binding = {v: args.get(k) for k, v in f.params.items()} if isinstance(f, Act) else {}

        def contains(x):
            return (isinstance(x, Act) and x.name == name) or (isinstance(x, Op) and any(contains(p) for p in x.parts))

        best = []
        stack = [g.sub]
        while stack:
            x = stack.pop()
            if isinstance(x, Act):
                if x.sub is not None:
                    stack.append(x.sub)
                continue
            if x.kind == "or" and any(contains(p) for p in x.parts):
                for p in x.parts:
                    if contains(p):
                        continue
                    r = repair(p, binding, self.hist)
                    if r and (not best or _cost(r) < _cost(best)):
                        best = r
            stack.extend(x.parts)
        return best

    def observe(self, name, args, content):
        """Cập nhật trạng thái từ kết quả tool thật (kể cả khi mode=none, để có log so sánh)."""
        if name in self.rs.action_params and isinstance(args, dict):
            record(self.rs, self.hist, name, args, C.try_eval(content))
        self.log.append({"tool": name, "args": args, "decision": "allowed", "result": str(content)[:300]})

    def summary(self):
        b = [e for e in self.log if e["decision"] == "blocked"]
        return {"n_blocked": len(b), "n_repeat_blocked": sum(e["repeat_index"] > 1 for e in b),
                "n_would_block": sum(e["decision"] == "would_block" for e in self.log),
                "templates": collections.Counter(v[0] for e in b for v in e["violations"])}
