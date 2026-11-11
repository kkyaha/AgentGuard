"""Chạy SOPBench với FrameGuard Gate (adapter SOPBench).

Giữ nguyên cấu hình công bố của SOPBench (fc, tool_list full, env_mode prompt, constraint full/structured,
không user simulator, temperature 0, top_p 0.01, max_tokens 1024, max_turns 20, max_actions 10).
Không sửa mã SOPBench: Gate gắn bằng cách bọc Swarm.handle_tool_calls; kiểu dữ liệu vLLM đổi bằng cách bọc lệnh khởi động.

Ví dụ:
  python adapters/sopbench/runner.py --model qwen3.5-2b --domain bank --modes none,bare,alignment --task_set smoke
  python adapters/sopbench/runner.py --fake_replay qwen3.5-2b-mode_fc --domain bank --modes none,alignment --task_set smoke
"""
import argparse, copy, json, os, sys, time, traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOPBENCH = os.environ.setdefault("SOPBENCH", os.path.join(ROOT, "external", "SOPBench"))
sys.path[:0] = [ROOT, os.path.join(ROOT, "analysis"), SOPBENCH]
os.chdir(SOPBENCH)  # SOPBench dùng đường dẫn tương đối

import swarm.llm_handler as lh  # noqa: E402
import swarm.core as core  # noqa: E402
from swarm.types import Agent, Response  # noqa: E402
from swarm.util import function_to_json, construct_chatcompletion  # noqa: E402
import run_simulation as rsim  # noqa: E402
from env.task import task_default_dep_full  # noqa: E402
from env.evaluator import evaluator_function_directed_graph  # noqa: E402
from openai.types.chat import ChatCompletionMessageToolCall  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402

from declare_rules import load_rules  # noqa: E402
import conformance as C  # noqa: E402
from oracle_fix import goal_succeeded_fixed  # noqa: E402
from frameguard.gate import Gate  # noqa: E402

# ------------------------------------------------------------------ vLLM: đổi dtype / max-model-len khi cần (T4 không có bf16)
_Popen = lh.subprocess.Popen


def _popen(cmd, *a, **k):
    if isinstance(cmd, list) and cmd[:2] == ["vllm", "serve"]:
        cmd = list(cmd)
        if os.getenv("VLLM_DTYPE") and "--dtype" in cmd:
            cmd[cmd.index("--dtype") + 1] = os.environ["VLLM_DTYPE"]
        if os.getenv("VLLM_MAX_MODEL_LEN") and "--max-model-len" in cmd:
            cmd[cmd.index("--max-model-len") + 1] = os.environ["VLLM_MAX_MODEL_LEN"]
        print("[frameguard] vllm cmd:", " ".join(cmd), flush=True)
    return _Popen(cmd, *a, **k)


lh.subprocess.Popen = _popen

# ------------------------------------------------------------------ Gate gắn vào Swarm.handle_tool_calls
CURRENT_GATE = None
_orig_handle = core.Swarm.handle_tool_calls


def _gated_handle(self, tool_calls, functions, context_variables, debug):
    G = CURRENT_GATE
    msgs = []
    for tc in tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments)
        except Exception:
            args = None
        msg = G.check(name, args) if G else None
        if msg is not None:
            msgs.append({"role": "tool", "tool_call_id": tc.id, "tool_name": name, "content": msg})
            continue
        resp = _orig_handle(self, [tc], functions, context_variables, debug)
        for m in resp.messages:
            if G:
                G.observe(name, args, m.get("content"))
        msgs.extend(resp.messages)
    return Response(messages=msgs, agent=None, context_variables={})


core.Swarm.handle_tool_calls = _gated_handle


# ------------------------------------------------------------------ model giả: phát lại trajectory công bố (kiểm tra ống dẫn, không cần GPU)
class ReplayHandler(lh.OpenAIHandler):  # kế thừa để qua kiểm tra kiểu của Agent; không gọi __init__ gốc
    def __init__(self, domain, model_key):
        p = os.path.join(SOPBENCH, "output", domain, f"ast_{model_key}-dep_full-fmt_structured-tool_full-shuffle_False.json")
        self.data = json.load(open(p))
        self.model_name = self.model_name_huggingface = f"replay:{model_key}"
        self.script = []

    def start(self, idx):
        self.script = [m for m in self.data[idx]["interactions"][0]["interaction"]
                       if m.get("sender", "").endswith("assistant")]

    def inference(self, create_params, debug, mode="chat", tool_call_mode="fc"):
        if not self.script:
            tc = [ChatCompletionMessageToolCall(id="end", type="function", function=Function(name="exit_conversation", arguments="{}"))]
            return {"completion": construct_chatcompletion("assistant", "", tc)}
        m = self.script.pop(0)
        tcs = [ChatCompletionMessageToolCall(id=t["id"], type="function",
                                             function=Function(name=t["function"]["name"], arguments=t["function"]["arguments"]))
               for t in (m.get("tool_calls") or [])] or None
        return {"completion": construct_chatcompletion("assistant", m.get("content") or "", tcs)}

    def kill_process(self):
        pass

    def __del__(self):
        pass


# ------------------------------------------------------------------ chạy
def sop_args(a):
    argv = ["--domain", a.domain, "--assistant_model", a.model or "replay", "--tool_call_mode", "fc",
            "--tool_list", "full", "--env_mode", "prompt", "--default_constraint_option", "full",
            "--constraint_descr_format", "structured", "--assistant_temperature", "0.0", "--assistant_top_p", "0.01",
            "--assistant_max_tokens", str(a.max_tokens), "--max_num_turns", "20", "--max_num_actions", str(a.max_actions)]
    old = sys.argv
    sys.argv = ["run_simulation.py"] + argv
    try:
        return rsim.parse_args()
    finally:
        sys.argv = old


def load_tasks(domain):
    tasks_dict = json.load(open(os.path.join(SOPBENCH, "data", f"{domain}_tasks.json")))
    tasks = []
    for k, arr in tasks_dict.items():
        for t in copy.deepcopy(arr):
            t["user_goal"] = k
            tasks.append(t)
    return tasks


def select(a):
    sets = json.load(open(os.path.join(ROOT, "adapters", "sopbench", "task_sets.json")))
    if a.task_set == "smoke":
        s = sets[f"smoke_{a.domain}_qwen3.5-2b"]
        return s["gate_addressable_failures"] + s["published_passes"]
    if a.task_set == "clean":
        return sets[a.domain]["clean"]
    return [int(x) for x in a.task_set.split(",")]


def evaluate(domain, task, interaction, database):
    func_calls = [{"tool_name": c["name"], "arguments": c["args"], "content": c["result"]}
                  for c in C.extract_calls(interaction)]
    ev = evaluator_function_directed_graph(domain, task, interaction, func_calls, {"final_database": database}, "full")
    asc_fixed = goal_succeeded_fixed(task, interaction)
    ev["success_fixed"] = (ev["no_tool_call_error"] and ev["constraint_not_violated"] and ev["database_match"]
                           and ev["dirgraph_satisfied"] and asc_fixed == task["action_should_succeed"])
    return ev


def main():
    global CURRENT_GATE
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default="bank")
    p.add_argument("--model", default=None, help="tên model SOPBench, vd qwen3.5-2b, gemma-4-e2b-it")
    p.add_argument("--fake_replay", default=None, help="vd qwen3.5-2b-mode_fc: phát lại trajectory công bố thay cho model")
    p.add_argument("--modes", default="none,bare,alignment")
    p.add_argument("--task_set", default="smoke", help="smoke | clean | danh sách id cách nhau dấu phẩy")
    p.add_argument("--max_tokens", type=int, default=1024)
    p.add_argument("--max_actions", type=int, default=10)
    p.add_argument("--num_gpus", type=int, default=1)
    p.add_argument("--out", default=os.path.join(ROOT, "runs"))
    a = p.parse_args()

    args = sop_args(a)
    tasks = load_tasks(a.domain)
    ids = select(a)
    dep_innate_full, default_dep_full, default_dep_full_descr = task_default_dep_full(
        a.domain, "full", "structured", dependency_verb_dep_orig=True)

    if a.fake_replay:
        handler = ReplayHandler(a.domain, a.fake_replay)
        run_name = f"replay_{a.fake_replay}"
    else:
        handler = lh.OpenAIHandler(model_name=a.model, num_gpus=a.num_gpus, gpu_memory_utilization=0.92, tool_calling=True)
        run_name = a.model
    assistant = Agent(name="domain assistant", client=handler, temperature=0.0, top_p=0.01,
                      max_tokens=a.max_tokens, tool_call_mode="fc", instructions="", functions=[])
    user = Agent(name="user", client=None, default_response="", response_repeat=True)

    summary = []
    try:
        for mode in a.modes.split(","):
            out_dir = os.path.join(a.out, a.domain, run_name, mode)
            os.makedirs(out_dir, exist_ok=True)
            for i in ids:
                f = os.path.join(out_dir, f"task_{i:04d}.json")
                if os.path.exists(f):           # chạy tiếp được khi phiên bị ngắt
                    summary.append(json.load(open(f))["summary"])
                    continue
                task = copy.deepcopy(tasks[i])
                CURRENT_GATE = Gate(load_rules(a.domain, task), mode)
                if a.fake_replay:
                    handler.start(i)
                t0 = time.time()
                try:
                    res = rsim.run_task_simulation(args=args, task=task, dep_innate_full=dep_innate_full,
                                                   default_dep_full=default_dep_full,
                                                   default_dep_full_descr=default_dep_full_descr,
                                                   assistant_agent=assistant, user_agent=user)
                except Exception as e:
                    traceback.print_exc()
                    res = {"interaction": [], "database": task["initial_database"], "error": repr(e)}
                inter = res["interaction"]
                for m in inter:
                    m.pop("role", None)
                ev = evaluate(a.domain, task, inter, res["database"])
                gs = CURRENT_GATE.summary()
                s = {"task": i, "goal": task["user_goal"], "should_succeed": task["action_should_succeed"], "mode": mode,
                     "success": ev["success"], "success_fixed": ev["success_fixed"], "n_blocked": gs["n_blocked"],
                     "n_repeat_blocked": gs["n_repeat_blocked"], "n_tool_calls": ev["num_function_calls"],
                     "seconds": round(time.time() - t0, 1)}
                json.dump({"config": {"model": run_name, "domain": a.domain, "mode": mode, "vllm_dtype": os.getenv("VLLM_DTYPE", "bfloat16"),
                                      "thinking": {"qwen": os.getenv("QWEN35_THINKING"), "gemma": os.getenv("GEMMA4_THINKING")},
                                      "max_tokens": a.max_tokens, "max_actions": a.max_actions},
                           "task": task, "interaction": inter, "database": res["database"], "evaluation": ev,
                           "gate_log": CURRENT_GATE.log, "summary": s},
                          open(f, "w"), indent=1, ensure_ascii=False, default=str)
                summary.append(s)
                print(f"[frameguard] {mode:11s} task {i:3d} {task['user_goal']:28s} success={ev['success']!s:5s} "
                      f"fixed={ev['success_fixed']!s:5s} blocked={gs['n_blocked']} {s['seconds']}s", flush=True)
    finally:
        if hasattr(handler, "kill_process"):
            handler.kill_process()
    report(summary)


def report(summary):
    import collections
    by = collections.defaultdict(list)
    for s in summary:
        by[s["mode"]].append(s)
    print("\nmode         n   pass  pass(sửa)  bị chặn≥1  phục hồi*  lặp-chặn  giây/task")
    for mode, rows in by.items():
        n = len(rows)
        blocked = [r for r in rows if r["n_blocked"] > 0]
        rec = sum(r["success_fixed"] for r in blocked)
        print(f"{mode:11s} {n:3d} {sum(r['success'] for r in rows):5d} {sum(r['success_fixed'] for r in rows):9d} "
              f"{len(blocked):10d} {f'{rec}/{len(blocked)}':>10s} {sum(r['n_repeat_blocked'] for r in rows):9d} "
              f"{sum(r['seconds'] for r in rows) / max(1, n):10.1f}")
    print("* phục hồi = số task pass (oracle đã sửa) trong các task bị chặn ít nhất một lần")


if __name__ == "__main__":
    main()
