"""Chạy SOPBench với FrameGuard Gate (adapter SOPBench).

Giữ nguyên cấu hình công bố của SOPBench (fc, tool_list full, env_mode prompt, constraint full/structured,
không user simulator, temperature 0, top_p 0.01, max_tokens 1024, max_turns 20, max_actions 10).
Không sửa mã SOPBench: Gate gắn bằng cách bọc Swarm.handle_tool_calls; kiểu dữ liệu vLLM đổi bằng cách bọc lệnh khởi động.

Chạy song song: mỗi task một luồng, có Gate / agent / bộ đếm token riêng (thread-local); vLLM gộp request.
Lời gọi bị Gate chặn VẪN tính vào max_actions của SOPBench (giữ ngân sách như baseline; ghi trong config).

Ví dụ:
  python adapters/sopbench/runner.py --model qwen3.5-2b --domain bank --modes none,bare,alignment --task_set clean --workers 6
  python adapters/sopbench/runner.py --model qwen3.5-2b --modes none,alignment --task_set pilot_repeat --runs 1,2 --workers 6
  python adapters/sopbench/runner.py --fake_replay qwen3.5-2b-mode_fc --modes none,bare,alignment --task_set clean --workers 8
"""
import argparse, collections, copy, hashlib, json, os, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOPBENCH = os.environ.setdefault("SOPBENCH", os.path.join(ROOT, "external", "SOPBench"))
sys.path[:0] = [ROOT, os.path.join(ROOT, "analysis"), SOPBENCH]
os.chdir(SOPBENCH)  # SOPBench dùng đường dẫn tương đối

import swarm.llm_handler as lh  # noqa: E402
import swarm.core as core  # noqa: E402
from swarm.types import Agent, Response  # noqa: E402
from swarm.util import construct_chatcompletion  # noqa: E402
import run_simulation as rsim  # noqa: E402
from env.task import task_default_dep_full  # noqa: E402
from env.evaluator import evaluator_function_directed_graph  # noqa: E402
from openai.types.chat import ChatCompletionMessageToolCall  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402

from declare_rules import load_rules  # noqa: E402
import conformance as C  # noqa: E402
from oracle_fix import goal_succeeded_fixed  # noqa: E402
from frameguard.gate import Gate  # noqa: E402

TLS = threading.local()          # Gate + bộ đếm token của task đang chạy trong luồng này
PRINT_LOCK = threading.Lock()


def log(*a):
    with PRINT_LOCK:
        print(*a, flush=True)


# ------------------------------------------------------------------ vLLM: đổi dtype / max-model-len khi cần (T4 không có bf16)
_Popen = lh.subprocess.Popen


def _popen(cmd, *a, **k):
    if isinstance(cmd, list) and cmd[:2] == ["vllm", "serve"]:
        cmd = list(cmd)
        if os.getenv("VLLM_DTYPE") and "--dtype" in cmd:
            cmd[cmd.index("--dtype") + 1] = os.environ["VLLM_DTYPE"]
        if os.getenv("VLLM_MAX_MODEL_LEN") and "--max-model-len" in cmd:
            cmd[cmd.index("--max-model-len") + 1] = os.environ["VLLM_MAX_MODEL_LEN"]
        if os.getenv("VLLM_MAX_NUM_SEQS"):
            cmd += ["--max-num-seqs", os.environ["VLLM_MAX_NUM_SEQS"]]
        log("[frameguard] vllm cmd:", " ".join(cmd))
    return _Popen(cmd, *a, **k)


lh.subprocess.Popen = _popen

# ------------------------------------------------------------------ Gate gắn vào Swarm.handle_tool_calls (theo luồng)
_orig_handle = core.Swarm.handle_tool_calls


def _gated_handle(self, tool_calls, functions, context_variables, debug):
    G = getattr(TLS, "gate", None)
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


def count_tokens(handler):
    """Bọc handler.inference để cộng token theo luồng (usage từ vLLM)."""
    orig = handler.inference

    def wrapped(*a, **k):
        out = orig(*a, **k)
        u = getattr(out.get("completion"), "usage", None)
        if u is not None and hasattr(TLS, "tokens"):
            TLS.tokens["prompt"] += getattr(u, "prompt_tokens", 0) or 0
            TLS.tokens["completion"] += getattr(u, "completion_tokens", 0) or 0
            TLS.tokens["llm_calls"] += 1
        return out
    handler.inference = wrapped


# ------------------------------------------------------------------ model giả: phát lại trajectory công bố (không cần GPU)
class ReplayHandler(lh.OpenAIHandler):  # kế thừa để qua kiểm tra kiểu của Agent; không gọi __init__ gốc
    _cache = {}

    def __init__(self, domain, model_key, idx):
        p = os.path.join(SOPBENCH, "output", domain, f"ast_{model_key}-dep_full-fmt_structured-tool_full-shuffle_False.json")
        if p not in self._cache:
            self._cache[p] = json.load(open(p))
        self.model_name = self.model_name_huggingface = f"replay:{model_key}"
        self.script = [m for m in self._cache[p][idx]["interactions"][0]["interaction"]
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


# ------------------------------------------------------------------ phiên bản code: chỉ dùng lại kết quả cũ khi cùng code + cấu hình
CODE_FILES = ["frameguard/gate.py", "frameguard/feedback.py", "adapters/sopbench/runner.py", "analysis/alignment.py",
              "analysis/conformance.py", "analysis/declare_rules.py", "analysis/oracle_fix.py"]


def code_version():
    h = hashlib.sha1()
    for rel in CODE_FILES:
        h.update(open(os.path.join(ROOT, rel), "rb").read())
    return h.hexdigest()[:12]


def vllm_version():
    try:
        import importlib.metadata as md
        return md.version("vllm")
    except Exception:
        return None


# ------------------------------------------------------------------ dữ liệu
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
    if a.task_set == "pilot_repeat":
        return sets[f"pilot_repeat_{a.domain}"]
    return [int(x) for x in a.task_set.split(",")]


BLOCK_PREFIX = "Error: the call to `"   # mọi tin nhắn phản hồi của Gate bắt đầu bằng chuỗi này


def evaluate(domain, task, interaction, database):
    """Chấm bằng oracle SOPBench trên các lời gọi ĐÃ THỰC THI.
    Lời gọi bị Gate chặn không chạy → loại khỏi danh sách (oracle mặc định mọi lời gọi trong log đều đã chạy).
    Ghi thêm success_with_blocked (giữ lời gọi bị chặn) để minh bạch."""
    calls = C.extract_calls(interaction)
    executed = [c for c in calls if not str(c["result"]).startswith(BLOCK_PREFIX)]

    def run(cs):
        fc = [{"tool_name": c["name"], "arguments": c["args"], "content": c["result"]} for c in cs]
        return evaluator_function_directed_graph(domain, task, interaction, fc, {"final_database": database}, "full")

    ev = run(executed)
    asc_fixed = goal_succeeded_fixed(task, interaction)
    ev["success_fixed"] = (ev["no_tool_call_error"] and ev["constraint_not_violated"] and ev["database_match"]
                           and ev["dirgraph_satisfied"] and asc_fixed == task["action_should_succeed"])
    ev["success_with_blocked"] = run(calls)["success"]
    ev["n_blocked_in_log"] = len(calls) - len(executed)
    return ev


# ------------------------------------------------------------------ một task
def run_one(ctx, mode, i, run_k):
    a, tasks = ctx["a"], ctx["tasks"]
    f = os.path.join(a.out, a.domain, ctx["run_name"], mode, f"task_{i:04d}_r{run_k}.json")
    if os.path.exists(f):           # chạy tiếp khi phiên bị ngắt — chỉ khi cùng code + cấu hình
        try:
            old = json.load(open(f))
            oc = old.get("config", {})
            if all(oc.get(k) == ctx["config"][k] for k in ("code_version", "max_tokens", "max_actions", "vllm_dtype")):
                return old["summary"]
        except Exception:
            pass
        log(f"[frameguard] task {i} ({mode}, r{run_k}): file cũ khác phiên bản code/cấu hình -> chạy lại")
    task = copy.deepcopy(tasks[i])
    handler = ReplayHandler(a.domain, a.fake_replay, i) if a.fake_replay else ctx["handler"]
    assistant = Agent(name="domain assistant", client=handler, temperature=0.0, top_p=0.01,
                      max_tokens=a.max_tokens, tool_call_mode="fc", instructions="", functions=[])
    user = Agent(name="user", client=None, default_response="", response_repeat=True)
    TLS.gate = Gate(load_rules(a.domain, task), mode)
    TLS.tokens = collections.Counter()
    t0 = time.time()
    err = None
    try:
        res = rsim.run_task_simulation(args=ctx["args"], task=task, dep_innate_full=copy.deepcopy(ctx["dep_innate_full"]),
                                       default_dep_full=copy.deepcopy(ctx["default_dep_full"]),
                                       default_dep_full_descr=copy.deepcopy(ctx["default_dep_full_descr"]),
                                       assistant_agent=assistant, user_agent=user)
    except Exception as e:
        log(traceback.format_exc())
        err = repr(e)
        res = {"interaction": [], "database": task["initial_database"]}
    inter = res["interaction"]
    for m in inter:
        m.pop("role", None)
    ev = evaluate(a.domain, task, inter, res["database"])
    G = TLS.gate
    gs = G.summary()
    s = {"task": i, "run": run_k, "goal": task["user_goal"], "should_succeed": task["action_should_succeed"], "mode": mode,
         "success": ev["success"], "success_fixed": ev["success_fixed"], "success_with_blocked": ev["success_with_blocked"],
         "n_blocked": gs["n_blocked"], "n_repeat_blocked": gs["n_repeat_blocked"], "n_would_block": gs["n_would_block"],
         "n_tool_calls": ev["num_function_calls"], "tokens": dict(TLS.tokens), "error": err,
         "seconds": round(time.time() - t0, 1)}
    os.makedirs(os.path.dirname(f), exist_ok=True)
    json.dump({"config": ctx["config"], "task": task, "interaction": inter, "database": res["database"],
               "evaluation": ev, "gate_log": G.log, "summary": s},
              open(f, "w"), indent=1, ensure_ascii=False, default=str)
    log(f"[frameguard] {mode:11s} r{run_k} task {i:3d} {task['user_goal']:26s} pass={ev['success_fixed']!s:5s} "
        f"chặn={gs['n_blocked']} tok={TLS.tokens['prompt'] + TLS.tokens['completion']} {s['seconds']}s"
        + (f" LỖI {err}" if err else ""))
    return s


# ------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default="bank")
    p.add_argument("--model", default=None, help="tên model SOPBench, vd qwen3.5-2b, gemma-4-e2b-it")
    p.add_argument("--fake_replay", default=None, help="vd qwen3.5-2b-mode_fc: phát lại trajectory công bố thay cho model")
    p.add_argument("--modes", default="none,bare,alignment")
    p.add_argument("--task_set", default="smoke", help="smoke | clean | pilot_repeat | danh sách id cách nhau dấu phẩy")
    p.add_argument("--runs", default="0", help="chỉ số lần chạy, vd '0' hoặc '1,2' (chạy lặp)")
    p.add_argument("--workers", type=int, default=1, help="số task chạy song song")
    p.add_argument("--repeat_set", default=None, help="tập task chạy lặp thêm, vd pilot_repeat")
    p.add_argument("--repeat_modes", default="none,alignment")
    p.add_argument("--repeat_runs", default="1,2")
    p.add_argument("--max_tokens", type=int, default=1024)
    p.add_argument("--max_actions", type=int, default=10)
    p.add_argument("--num_gpus", type=int, default=1)
    p.add_argument("--out", default=os.path.join(ROOT, "runs"))
    a = p.parse_args()

    dep_innate_full, default_dep_full, default_dep_full_descr = task_default_dep_full(
        a.domain, "full", "structured", dependency_verb_dep_orig=True)
    run_name = f"replay_{a.fake_replay}" if a.fake_replay else a.model
    ctx = {"a": a, "args": sop_args(a), "tasks": load_tasks(a.domain), "run_name": run_name,
           "dep_innate_full": dep_innate_full, "default_dep_full": default_dep_full,
           "default_dep_full_descr": default_dep_full_descr,
           "config": {"model": run_name, "domain": a.domain, "code_version": code_version(), "vllm_version": vllm_version(),
                      "vllm_dtype": os.getenv("VLLM_DTYPE", "bfloat16"),
                      "thinking": {"qwen": os.getenv("QWEN35_THINKING"), "gemma": os.getenv("GEMMA4_THINKING")},
                      "max_tokens": a.max_tokens, "max_actions": a.max_actions, "workers": a.workers,
                      "blocked_calls_count_toward_max_actions": True}}
    log(f"[frameguard] code_version={ctx['config']['code_version']} vllm={ctx['config']['vllm_version']} workers={a.workers}")
    ids = select(a)
    jobs = [(m, i, int(k)) for k in a.runs.split(",") for m in a.modes.split(",") for i in ids]
    log(f"[frameguard] {len(jobs)} lượt chạy chính: {len(ids)} task × {a.modes} × runs {a.runs}")
    if a.repeat_set:
        rids = select(argparse.Namespace(task_set=a.repeat_set, domain=a.domain))
        extra = [(m, i, int(k)) for k in a.repeat_runs.split(",") for m in a.repeat_modes.split(",") for i in rids]
        jobs += extra
        log(f"[frameguard] + {len(extra)} lượt chạy lặp: {len(rids)} task × {a.repeat_modes} × runs {a.repeat_runs}")

    handler = None
    if not a.fake_replay:
        handler = lh.OpenAIHandler(model_name=a.model, num_gpus=a.num_gpus, gpu_memory_utilization=0.92, tool_calling=True)
        count_tokens(handler)
    ctx["handler"] = handler

    summary, n_err, t0 = [], 0, time.time()
    try:
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            futs = {ex.submit(run_one, ctx, m, i, k): (m, i, k) for (m, i, k) in jobs}
            for n, fut in enumerate(as_completed(futs), 1):
                s = fut.result()
                summary.append(s)
                n_err = n_err + 1 if s.get("error") else 0
                if n_err >= 5:
                    log("[frameguard] DỪNG: 5 task liên tiếp lỗi — xem traceback ở trên.")
                    os._exit(1)
                if n % 10 == 0:
                    el = time.time() - t0
                    log(f"[frameguard] tiến độ {n}/{len(jobs)} — {el / 60:.0f} phút, còn ~{el / n * (len(jobs) - n) / 60:.0f} phút")
    finally:
        if handler is not None:
            handler.kill_process()
    report(summary)


def report(summary):
    by = collections.defaultdict(list)
    for s in summary:
        by[(s["mode"], s.get("run", 0))].append(s)
    print("\nmode        run   n  pass  hoàn_thành  từ_chối_đúng  bị_chặn≥1  phục_hồi  lặp_chặn  giây/task")
    for (mode, rk), rows in sorted(by.items()):
        n = len(rows)
        ss = [r for r in rows if r["should_succeed"]]
        sf = [r for r in rows if not r["should_succeed"]]
        bl = [r for r in rows if r["n_blocked"] > 0]
        print(f"{mode:11s} r{rk:<3d}{n:4d} {sum(r['success_fixed'] for r in rows):5d} "
              f"{sum(r['success_fixed'] for r in ss):6d}/{len(ss):<4d} {sum(r['success_fixed'] for r in sf):7d}/{len(sf):<5d} "
              f"{len(bl):9d} {sum(r['success_fixed'] for r in bl):5d}/{len(bl):<4d} {sum(r['n_repeat_blocked'] for r in rows):7d} "
              f"{sum(r['seconds'] for r in rows) / max(1, n):9.1f}")


if __name__ == "__main__":
    main()
