"""Gate tất định (cách 1): chỉ ép nhóm Precedence, trạng thái chỉ cập nhật từ kết quả tool thật.

Dùng phần lõi đã kiểm định ở giai đoạn 1 (analysis/alignment.py, analysis/conformance.py).
Sẽ tách hẳn khỏi analysis/ khi tái cấu trúc frameguard/ + adapters/.
"""
import collections, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis"))
import conformance as C  # noqa: E402
from alignment import align_activation, record, state_tools, repair, _cost  # noqa: E402
from declare_rules import Act, Op  # noqa: E402
from frameguard.feedback import render, render_existence  # noqa: E402


def _contains(f, name):
    """X xuất hiện ở bất kỳ đâu trong công thức (kể cả tiền điều kiện lồng nhau của một Act)."""
    if f is None:
        return False
    if isinstance(f, Act):
        return f.name == name or _contains(f.sub, name)
    return any(_contains(p, name) for p in f.parts)


def _ginfo_log(g):
    if not g:
        return None
    return {k: ([m.tool for m in v] if k == "goal_steps" else v) for k, v in g.items()}


class Gate:
    def __init__(self, rules, mode):
        self.rs, self.mode = rules, mode
        # Tool có trong luật nhưng agent không được cấp (vd internal_get_database: SOPBench mặc định
        # provide_database_getter=False). Không bao giờ đề xuất; lời gọi tới chúng không chặn, không tính là thỏa.
        self.unavailable = frozenset()
        self.hist = C.History()
        self.blocked_counts = collections.Counter()
        self.reminded = False               # goal_ex: đã nhắc nghĩa vụ Existence(G) chưa (tối đa 1 lần)
        self.log = []                       # một dòng cho mỗi tool call đi qua Gate

    def set_tools(self, names):
        """Danh sách tool thật của agent (lấy từ harness lúc chạy)."""
        self.unavailable = frozenset(set(self.rs.action_params) - set(names))

    def check(self, name, args):
        """Trả về tin nhắn phản hồi nếu chặn, None nếu cho chạy."""
        if name not in self.rs.action_params or name in self.unavailable or not isinstance(args, dict):
            return None
        moves = align_activation(self.rs, name, args, self.hist, self.unavailable)
        if not moves:
            return None
        if self.mode == "none":
            # chế độ bóng: ghi lại "lẽ ra chặn ở đâu" để so với các chế độ có Gate, nhưng không chặn
            self.log.append({"tool": name, "args": args, "decision": "would_block", "repair": [m.tool for m in moves]})
            return None
        f = self.rs.precondition(name)
        binding = {v: args.get(k) for k, v in f.params.items()} if isinstance(f, Act) else {}
        viol = C.unsatisfied(f.sub if isinstance(f, Act) else None, binding, self.hist)
        # không nêu tool agent không có trong các lựa chọn của Branched Precedence
        viol = [(t, tuple(x for x in src if x not in self.unavailable) or src, k) for t, src, k in viol]
        viol = [("Precedence" if len(src) == 1 else t, src, k) for t, src, k in viol]
        impossible = [m.tool for m in moves if m.tool in self.unavailable]   # không còn nhánh nào dùng được
        st = state_tools(self.rs.domain)
        failed = [m.tool for m in moves if m.tool in st and m.tool in self.hist.any]
        alt = self.alternative(name, args)
        key = (name, C.norm(args))
        self.blocked_counts[key] += 1
        ginfo = None
        if self.mode in ("goal", "goal_ex"):
            ginfo = self.goal_info(name, args, failed)
        elif self.mode == "purpose":
            ginfo = {"required_by": self.required_by(name)}
        elif self.mode == "purpose_v2":
            ginfo = {"required_by": self.required_by_v2(name, failed)}
        msg = render(self.mode, name, viol, moves, failed, alt, ginfo, impossible)
        self.log.append({"tool": name, "args": args, "decision": "blocked",
                         "violations": [list(v[:1]) + [list(v[1])] + [v[2]] for v in viol],
                         "repair": [m.tool for m in moves], "alternative": [m.tool for m in alt],
                         "failed_state": failed, "impossible": impossible, "repeat_index": self.blocked_counts[key], "message": msg,
                         "goal_info": _ginfo_log(ginfo)})
        return msg

    # ------------------------------------------------------------ phản hồi theo goal
    def _seen_values(self, args):
        """Giá trị tham số để điền cho các bước của goal (Gate không biết tham số của G).
        Chỉ lấy từ lời gọi hợp lệ đã thành công (hist.conformant), không từ lời gọi thất bại hay lời gọi đang bị chặn.
        Tham số có hơn một giá trị (vd username của người gửi và người nhận) thì bỏ trống: không đoán; khi trống,
        mọi lời gọi hợp lệ cùng tên đều tính là thỏa, và bước cần làm sẽ ghi "hỏi người dùng"."""
        vals = collections.defaultdict(set)
        for calls in self.hist.conformant.values():
            for a in calls:
                if isinstance(a, dict):
                    for k, v in a.items():
                        if v is not None:
                            vals[k].add(C.norm(v))
        seen = {}
        for calls in self.hist.conformant.values():
            for a in calls:
                if isinstance(a, dict):
                    seen.update({k: v for k, v in a.items() if v is not None and len(vals[k]) == 1})
        return seen

    def goal_info(self, name, args, failed):
        """Chế độ `goal` (Gate biết loại yêu cầu G). So lời gọi bị chặn X với mô hình ràng buộc của G:
        - needed   : X có trên một đường tới G (có thể trong nhánh `or`)
        - not_needed: X không nằm trong tiền điều kiện của G → chỉ ra các bước còn thiếu của G (rỗng = gọi G được)
        Chuỗi bước của G tránh tool tạo trạng thái đã thất bại (vd login_user trả False) nếu có nhánh khác."""
        G = self.rs.goal
        if name == G:
            return {"goal": G, "relation": "is_goal"}
        steps = self.goal_steps(failed)
        # Liên quan theo alignment (không theo đồ thị): X "cần" chỉ khi nằm trên chuỗi sửa tối ưu của G;
        # X có trong mô hình của G nhưng ngoài chuỗi tối ưu (nhánh Branched/Choice khác rẻ hơn / nhánh qua X đã hỏng) = "optional".
        if any(m.tool == name for m in steps):
            rel = "needed"
        elif _contains(self._goal_sub(), name):
            rel = "optional"
        else:
            rel = "not_needed"
        return {"goal": G, "relation": rel, "goal_steps": steps}

    def _goal_sub(self):
        g = self.rs.precondition(self.rs.goal)
        return g.sub if isinstance(g, Act) else None

    def goal_steps(self, failed=()):
        """Chuỗi sửa tối thiểu còn thiếu để gọi được G (prefix alignment trên mô hình của G)."""
        sub = self._goal_sub()
        if sub is None:
            return []
        return repair(sub, self._seen_values({}), self.hist, frozenset(failed) | self.unavailable)

    def failed_state(self):
        st = state_tools(self.rs.domain)
        ok = {t for t in self.hist.conformant}
        return [t for t in st if t in self.hist.any and t not in ok]

    def existence_reminder(self):
        """Chế độ `goal_ex`: nghĩa vụ liveness Existence(G). Gọi khi agent vừa trả lời bằng văn bản (không tool call).
        Nhắc MỘT lần nếu: G chưa được gọi (bị chặn rồi bỏ cũng tính là chưa gọi), và G chưa rơi vào đường cụt
        (mọi đường tới G cần tool tạo trạng thái đã thất bại). Trả về tin nhắn hoặc None."""
        if self.mode != "goal_ex" or self.reminded:
            return None
        G = self.rs.goal
        if G in self.hist.any:
            return None
        failed = self.failed_state()
        steps = self.goal_steps(failed)
        if any(m.tool in failed for m in steps):    # đường cụt: mọi nhánh tới G cần tool đã thất bại → từ chối là đúng
            return None
        self.reminded = True
        msg = render_existence(G, steps, self.rs.action_params.get(G, {}))
        self.log.append({"tool": None, "args": None, "decision": "existence_reminder", "goal": G,
                         "goal_steps": [m.tool for m in steps], "message": msg})
        return msg

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

    def required_by_v2(self, name, failed=()):
        """Chế độ `purpose_v2`: action (agent CÓ) mà X nằm trên chuỗi sửa tối ưu của nó, với lịch sử hiện tại.
        Khác `purpose`: lọc tool không có; tiêu chí alignment thay vì "có xuất hiện trong cây"."""
        excl = frozenset(failed) | self.unavailable
        out = []
        for a in sorted(self.rs.action_params):
            if a == name or a in self.unavailable:
                continue
            f = self.rs.precondition(a)
            if not (isinstance(f, Act) and f.sub is not None and _contains(f.sub, name)):
                continue
            if any(m.tool == name for m in repair(f.sub, {}, self.hist, excl)):
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
                    r = repair(p, binding, self.hist, self.unavailable)
                    if any(m.tool in self.unavailable for m in r):
                        continue
                    if r and (not best or _cost(r) < _cost(best)):
                        best = r
            stack.extend(x.parts)
        return best

    def observe(self, name, args, content):
        """Cập nhật trạng thái từ kết quả tool thật (kể cả khi mode=none, để có log so sánh)."""
        if name in self.unavailable:
            self.log.append({"tool": name, "args": args, "decision": "unavailable", "result": str(content)[:300]})
            return
        if name in self.rs.action_params and isinstance(args, dict):
            record(self.rs, self.hist, name, args, C.try_eval(content))
        self.log.append({"tool": name, "args": args, "decision": "allowed", "result": str(content)[:300]})

    def summary(self):
        b = [e for e in self.log if e["decision"] == "blocked"]
        return {"n_blocked": len(b), "n_repeat_blocked": sum(e["repeat_index"] > 1 for e in b),
                "n_would_block": sum(e["decision"] == "would_block" for e in self.log),
                "n_reminders": sum(e["decision"] == "existence_reminder" for e in self.log),
                "templates": collections.Counter(v[0] for e in b for v in e["violations"])}
