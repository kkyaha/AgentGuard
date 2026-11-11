"""Sinh tin nhắn phản hồi khi Gate chặn. Mọi câu chữ sinh từ template, không viết tay theo task.

Các kiểu: bare / reason / next_action / template / alignment (xem CLAUDE.md, RQ2).
Tiếng Anh vì prompt và tool của SOPBench là tiếng Anh.
"""
import json

MODES = ("none", "bare", "reason", "next_action", "template", "alignment")


def _args(a):
    return ", ".join(f"{k}={json.dumps(v)}" for k, v in a.items())


def render(mode, blocked, violations, moves, failed_state):
    """
    blocked       : tên tool bị chặn
    violations    : [(template, (sources...), kind)] — ràng buộc DECLARE chưa thỏa
    moves         : chuỗi sửa tối thiểu (alignment.Move), theo thứ tự
    failed_state  : tool tạo trạng thái đã gọi nhưng thất bại (vd login_user trả False)
    """
    if mode == "bare":
        return f"Error: the call to `{blocked}` was blocked."
    if mode == "reason":
        return (f"Error: the call to `{blocked}` was blocked because it violates the standard operating procedure: "
                f"a required prerequisite has not been satisfied.")
    if mode == "next_action":
        if failed_state:
            return (f"Error: the call to `{blocked}` was blocked. Next action: tell the user the request cannot be "
                    f"completed, because `{failed_state[0]}` did not succeed.")
        m = moves[0]
        return f"Error: the call to `{blocked}` was blocked. Next action: call `{m.tool}`."
    if mode == "template":
        lines = [f"Error: the call to `{blocked}` was blocked by the procedure."]
        for tpl, src, kind in violations:
            fs = [s for s in src if s in failed_state]
            if fs:
                lines.append(f"- `{fs[0]}` was called but did not succeed, so the requirement for `{blocked}` is not met. "
                             f"Do not retry `{blocked}`; tell the user the request cannot be completed.")
            elif tpl == "Precedence":
                lines.append(f"- Precedence: you must successfully call `{src[0]}` before `{blocked}`.")
            else:
                alts = " or ".join(f"`{s}`" for s in src)
                lines.append(f"- You must successfully call one of {alts} before `{blocked}`.")
        lines.append("Do not repeat the blocked call unchanged.")
        return "\n".join(lines)
    if mode == "alignment":
        if failed_state:
            return (f"Error: the call to `{blocked}` was blocked. `{failed_state[0]}` was called but did not succeed, "
                    f"so `{blocked}` is not allowed. Do not retry it; tell the user the request cannot be completed.")
        lines = [f"Error: the call to `{blocked}` was blocked. Minimal steps to make it allowed, in order:"]
        for i, m in enumerate(moves, 1):
            ask = (f"; use the user's {', '.join(m.ask_user)} (ask the user only if you do not have it)"
                   if m.ask_user else "")
            lines.append(f"  {i}. call `{m.tool}`({_args(m.args)}){ask}")
        lines.append(f"Then call `{blocked}` again only if every check above succeeds; "
                     f"if a check fails, tell the user the request cannot be completed.")
        return "\n".join(lines)
    raise ValueError(mode)
