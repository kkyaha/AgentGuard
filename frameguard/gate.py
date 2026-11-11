"""Gate tất định (cách 1): chỉ ép nhóm Precedence, trạng thái chỉ cập nhật từ kết quả tool thật.

Dùng phần lõi đã kiểm định ở giai đoạn 1 (analysis/alignment.py, analysis/conformance.py).
Sẽ tách hẳn khỏi analysis/ khi tái cấu trúc frameguard/ + adapters/.
"""
import collections, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis"))
import conformance as C  # noqa: E402
from alignment import align_activation, record, state_tools  # noqa: E402
from declare_rules import Act  # noqa: E402
from frameguard.feedback import render  # noqa: E402


class Gate:
    def __init__(self, rules, mode):
        self.rs, self.mode = rules, mode
        self.hist = C.History()
        self.blocked_counts = collections.Counter()
        self.log = []                       # một dòng cho mỗi tool call đi qua Gate

    def check(self, name, args):
        """Trả về tin nhắn phản hồi nếu chặn, None nếu cho chạy."""
        if self.mode == "none" or name not in self.rs.action_params or not isinstance(args, dict):
            return None
        moves = align_activation(self.rs, name, args, self.hist)
        if not moves:
            return None
        f = self.rs.precondition(name)
        binding = {v: args.get(k) for k, v in f.params.items()} if isinstance(f, Act) else {}
        viol = C.unsatisfied(f.sub if isinstance(f, Act) else None, binding, self.hist)
        st = state_tools(self.rs.domain)
        failed = [m.tool for m in moves if m.tool in st and m.tool in self.hist.any]
        key = (name, C.norm(args))
        self.blocked_counts[key] += 1
        msg = render(self.mode, name, viol, moves, failed)
        self.log.append({"tool": name, "args": args, "decision": "blocked",
                         "violations": [list(v[:1]) + [list(v[1])] + [v[2]] for v in viol],
                         "repair": [m.tool for m in moves], "failed_state": failed,
                         "repeat_index": self.blocked_counts[key], "message": msg})
        return msg

    def observe(self, name, args, content):
        """Cập nhật trạng thái từ kết quả tool thật (kể cả khi mode=none, để có log so sánh)."""
        if name in self.rs.action_params and isinstance(args, dict):
            record(self.rs, self.hist, name, args, C.try_eval(content))
        self.log.append({"tool": name, "args": args, "decision": "allowed", "result": str(content)[:300]})

    def summary(self):
        b = [e for e in self.log if e["decision"] == "blocked"]
        return {"n_blocked": len(b), "n_repeat_blocked": sum(e["repeat_index"] > 1 for e in b),
                "templates": collections.Counter(v[0] for e in b for v in e["violations"])}
