"""Tra cứu task SOPBench theo số thứ tự (đúng cách đánh số của runner và tên file task_XXXX_rK.json).

Số thứ tự = vị trí trong danh sách phẳng của data/<domain>_tasks.json: duyệt các nhóm goal theo thứ tự trong file,
mỗi nhóm duyệt các task theo thứ tự, đánh số từ 0.

Dùng:
  .venv/bin/python scripts/show_task.py bank                 # bảng mọi task: số, goal, nên thành công?, sạch/loại
  .venv/bin/python scripts/show_task.py bank 28              # chi tiết task 28
  .venv/bin/python scripts/show_task.py bank 28 --runs runs/e2_nothink/bank/qwen3.5-2b   # + kết quả từng chế độ
"""
import argparse, glob, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOPBENCH = os.path.join(ROOT, "external", "SOPBench")


def load_tasks(domain):
    tasks = []
    for goal, arr in json.load(open(os.path.join(SOPBENCH, "data", f"{domain}_tasks.json"))).items():
        for t in arr:
            t["user_goal"] = goal
            tasks.append(t)
    return tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("task", nargs="?", type=int)
    ap.add_argument("--runs", help="thư mục kết quả của một model, vd runs/e2_nothink/bank/qwen3.5-2b")
    a = ap.parse_args()
    tasks = load_tasks(a.domain)
    sets = json.load(open(os.path.join(ROOT, "adapters", "sopbench", "task_sets.json")))
    clean = set(sets.get(a.domain, {}).get("clean", []))

    if a.task is None:
        print(f"{a.domain}: {len(tasks)} task, {len(clean)} sạch\n")
        print(f"{'số':>4}  {'goal':28s} {'nên TC':7s} tập")
        for i, t in enumerate(tasks):
            print(f"{i:4d}  {t['user_goal']:28s} {str(t['action_should_succeed']):7s} {'sạch' if i in clean else 'LOẠI'}")
        return

    t = tasks[a.task]
    print(f"# {a.domain} task {a.task} — {'sạch' if a.task in clean else 'BỊ LOẠI (không giải được)'}")
    for k in ("user_goal", "action_should_succeed", "user_instruction", "user_known",
              "constraints_original", "constraints", "directed_action_graph", "constraint_parameters"):
        print(f"\n## {k}\n{json.dumps(t[k], ensure_ascii=False, indent=1)}")

    if a.runs:
        print("\n## Kết quả đã chạy")
        for f in sorted(glob.glob(os.path.join(a.runs, "*", f"task_{a.task:04d}_r*.json"))):
            x = json.load(open(f))
            s = x["summary"]
            seq = " → ".join(("✗" if e["decision"] == "blocked" else "") + e["tool"]
                             for e in x["gate_log"] if e["decision"] in ("allowed", "blocked"))
            print(f"  {s['mode']:11s} r{s.get('run', 0)}  pass={s['success_fixed']!s:5s}  chặn={s['n_blocked']}  {seq}")
        print("  (✗ = lời gọi bị Gate chặn)")


if __name__ == "__main__":
    main()
