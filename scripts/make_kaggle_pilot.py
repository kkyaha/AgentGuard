"""Sinh notebook Kaggle cho PILOT (notebooks/kaggle_pilot.ipynb), nhúng sẵn mã FrameGuard.

Pilot: Qwen3.5-2B, bank, 105 task sạch × {none, bare, alignment} + chạy lặp 2 lần × 30 task × {none, alignment}.
Chạy lại script này mỗi khi sửa mã:  .venv/bin/python scripts/make_kaggle_pilot.py
"""
import json, os, sys
PRESET = sys.argv[1] if len(sys.argv) > 1 else "e2"
PRESETS = {
    "remaining": dict(PART="remaining", MODES="none,bare,alignment", THINKING="True", out="kaggle_pilot_remaining.ipynb",
                      title="FrameGuard — PILOT phần còn lại (alignment + chạy lặp, thinking BẬT)"),
    "e2": dict(PART="all", MODES="none,bare,next_action,template,alignment", THINKING="False", out="kaggle_e2_nothink.ipynb",
               title="FrameGuard — E2: thinking TẮT (bank, none/bare/next_action/template/alignment)"),
}
P = PRESETS[PRESET]

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOPBENCH_COMMIT = "8790ed7406acbd22270f90bd1c4038de3fc5db8f"
FILES = ["analysis/declare_rules.py", "analysis/conformance.py", "analysis/failure_taxonomy.py",
         "analysis/alignment.py", "analysis/oracle_fix.py", "analysis/pilot_report.py",
         "frameguard/__init__.py", "frameguard/feedback.py", "frameguard/gate.py",
         "adapters/sopbench/runner.py", "adapters/sopbench/task_sets.json"]
cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": s.strip("\n").splitlines(True)})


md("""
# {TITLE}

**Câu hỏi:** Gate + phản hồi `alignment` có giúp model 2B *hoàn thành* nhiều task hơn `bare` và `none` không, có ý nghĩa thống kê không?

**Chạy gì (một lần khởi động vLLM, chạy song song):**
- 105 task sạch của bank × các chế độ `{MODES}` (105 lượt mỗi chế độ)
- Chạy lặp thêm 2 lần × 30 task × `none` / `alignment` = 120 lượt (đo nhiễu)

**Trước khi chạy** (cột phải → *Session options*): **GPU T4 x2**, **Internet On**.
Rồi **Save Version → Save & Run All (Commit)** — không chạy từng ô ở editor. Ước tính: thinking bật ~4–5 giờ, thinking tắt nhanh hơn nhiều (2 GPU).

**Khi xong:** mở *Logs* của phiên bản, kéo xuống cuối, copy toàn bộ phần **BÁO CÁO PILOT** gửi lại.
""")

code("""
# ===== Cấu hình =====
MODEL   = "qwen3.5-2b"
DOMAIN  = "bank"
WORKERS = 6            # số task chạy song song MỖI GPU (vLLM gộp request). Giảm xuống 4 nếu bị lỗi bộ nhớ.
USE_2_GPUS = True      # True: 2 tiến trình, mỗi tiến trình 1 GPU T4, chia đôi công việc (nhanh gấp ~2)
PART = "{PART}"  # "all": toàn bộ | "remaining": chỉ alignment + chạy lặp (khi đã có none, bare của cùng cấu hình)
import os
MODES   = "{MODES}"  # có thể thêm template,next_action
THINKING = {THINKING}  # True: như bản công bố. False: tắt suy nghĩ -> model phải dựa vào nội dung phản hồi (E2)
os.environ["VLLM_DTYPE"] = "float16"          # T4 không hỗ trợ bf16 (SOPBench gốc dùng bf16)
for k in ("QWEN35_THINKING", "GEMMA4_THINKING", "QWEN35_NOTHINK"):
    os.environ.pop(k, None)
if THINKING:
    os.environ["QWEN35_THINKING"] = "1"; os.environ["GEMMA4_THINKING"] = "1"
else:
    os.environ["QWEN35_NOTHINK"] = "1"        # Qwen3.5: tắt thinking; Gemma-4: mặc định không thinking
OUT = "runs" if THINKING else "runs_nothink"  # mỗi cấu hình một thư mục -> không lẫn / không dùng nhầm kết quả
# os.environ["VLLM_MAX_MODEL_LEN"] = "16384"  # bật nếu thiếu bộ nhớ (mặc định SOPBench: 32000)
WORK = "/kaggle/working/frameguard"
""")

code("""
# Dừng sớm nếu phiên không có GPU
import subprocess, shutil
r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,compute_cap", "--format=csv"],
                   capture_output=True, text=True) if shutil.which("nvidia-smi") else None
if r is None or r.returncode != 0:
    raise SystemExit("KHÔNG CÓ GPU. Vào Session options -> Accelerator -> GPU T4 x2, rồi commit lại.")
print(r.stdout)
""")

code(f"""
%%bash
set -e
mkdir -p /kaggle/working/frameguard/external && cd /kaggle/working/frameguard/external
if [ ! -d SOPBench ]; then
  git clone -q --filter=blob:none --no-checkout https://github.com/Leezekun/SOPBench.git
  cd SOPBench
  git sparse-checkout set --no-cone '/*' '!/output/'
  git checkout -q {SOPBENCH_COMMIT}
fi
echo "SOPBench @ $(git -C /kaggle/working/frameguard/external/SOPBench rev-parse --short HEAD)"
""")

code("""
%%bash
pip install -q "vllm==0.25.0" 2>&1 | tail -3
pip install -q "openai>=1.71.0" "anthropic>=0.49.0" python-dotenv "pydantic>=2.9.2" termcolor colorama tqdm 2>&1 | tail -3
python -c "import vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
""")

md("## Mã FrameGuard (nhúng sẵn, sinh từ repo)")
code("!mkdir -p /kaggle/working/frameguard/analysis /kaggle/working/frameguard/frameguard /kaggle/working/frameguard/adapters/sopbench")
for rel in FILES:
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    if not src.strip():
        src = "# (file trống)\n"
    code(f"%%writefile /kaggle/working/frameguard/{rel}\n{src}")

md("""
## Chạy pilot
Mặc định dùng **cả 2 GPU T4**: 2 tiến trình chạy song song, mỗi tiến trình một GPU, chia đôi công việc.
Log đầy đủ: `/kaggle/working/pilot_gpu0.log`, `pilot_gpu1.log`; ô này in tiến độ mỗi 10 phút.
Kết quả chạy tiếp được: nếu commit bị ngắt, chạy lại sẽ bỏ qua lượt đã xong (cùng phiên bản code).
""")
code("""
import subprocess, time, os
base = ["python", "adapters/sopbench/runner.py", "--model", MODEL, "--domain", DOMAIN, "--workers", str(WORKERS),
        "--out", f"{WORK}/{OUT}"]
all_modes = MODES
GPU0_SET = ("none", "bare", "next_action")  # cân tải: GPU0 3 chế độ (315 lượt), GPU1 template+alignment+chạy lặp (330 lượt)
gpu0_modes = ",".join(m for m in MODES.split(",") if m in GPU0_SET)
gpu1_modes = ",".join(m for m in MODES.split(",") if m not in GPU0_SET)
if PART == "remaining":
    # đã có none + bare (105 task) từ lần chạy trước. GPU 0: alignment 105 task; GPU 1: chạy lặp r1, r2 (120 lượt).
    jobs = [("0", base + ["--modes", "alignment", "--task_set", "clean"], "/kaggle/working/pilot_gpu0.log"),
            ("1", base + ["--modes", "none,alignment", "--task_set", "pilot_repeat", "--runs", "1,2"], "/kaggle/working/pilot_gpu1.log")]
    if not USE_2_GPUS:
        jobs = [("0", base + ["--modes", "alignment", "--task_set", "clean", "--repeat_set", "pilot_repeat",
                              "--repeat_modes", "none,alignment", "--repeat_runs", "1,2"], "/kaggle/working/pilot_gpu0.log")]
elif USE_2_GPUS:
    # GPU 0: none/bare/next_action; GPU 1: các chế độ còn lại + chạy lặp. Mỗi lượt ghi file riêng -> không xung đột.
    jobs = [("0", base + ["--modes", gpu0_modes, "--task_set", "clean"], "/kaggle/working/pilot_gpu0.log"),
            ("1", base + ["--modes", gpu1_modes, "--task_set", "clean", "--repeat_set", "pilot_repeat",
                          "--repeat_modes", "none,alignment", "--repeat_runs", "1,2"], "/kaggle/working/pilot_gpu1.log")]
else:
    jobs = [("0", base + ["--modes", all_modes, "--task_set", "clean", "--repeat_set", "pilot_repeat",
                          "--repeat_modes", "none,alignment", "--repeat_runs", "1,2"], "/kaggle/working/pilot_gpu0.log")]
# Dọn tiến trình cũ nếu ô này bị chạy lại (tránh 2 vLLM tranh 1 GPU). Kết quả đã xong vẫn được giữ và bỏ qua.
subprocess.run("pkill -f adapters/sopbench/runner.py; pkill -f 'vllm serve'", shell=True)
time.sleep(5)
procs = []
t0 = time.time()
for gpu, cmd, logf in jobs:
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu)
    procs.append((gpu, subprocess.Popen(cmd, cwd=WORK, env=env, stdout=open(logf, "a"), stderr=subprocess.STDOUT), logf))
    print(f"Đã khởi động GPU{gpu}: {' '.join(cmd[8:])}", flush=True)
    if gpu != jobs[-1][0]:
        print("  chờ 90 giây trước khi khởi động GPU tiếp theo (tránh 2 vLLM nạp model cùng lúc)...", flush=True)
        time.sleep(90)
print("Đang chạy. Tiến độ in mỗi 2 phút; vLLM nạp model mất ~3–5 phút đầu. ĐỪNG bấm Stop.", flush=True)
while any(p.poll() is None for _, p, _ in procs):
    time.sleep(120)
    for gpu, p, logf in procs:
        txt = open(logf, errors="ignore").read().splitlines()
        prog = [l for l in txt if "tiến độ" in l or "LỖI" in l or "DỪNG" in l]
        done = sum(1 for l in txt if l.startswith("[frameguard] ") and " task " in l and "pass=" in l)
        state = "xong" if p.poll() is not None else ("đang nạp model..." if not done else "đang chạy")
        print(f"[{(time.time() - t0) / 60:5.0f} phút] GPU{gpu} ({state}): {done} lượt xong"
              + (f" | {prog[-1].strip()}" if prog else ""), flush=True)
for gpu, p, logf in procs:
    print(f"GPU{gpu} kết thúc, mã thoát {p.returncode}")
    !grep -E "code_version|lượt chạy|LỖI|DỪNG|Traceback|^mode|^none|^bare|^alignment" {logf} | tail -25
""")

md("## Báo cáo")
code("""
print("=" * 25, "BÁO CÁO PILOT", "=" * 25)
!cd /kaggle/working/frameguard && python analysis/pilot_report.py {OUT}/{DOMAIN}/{MODEL}
print("=" * 25, "HẾT BÁO CÁO", "=" * 25)
""")

code("""
!tail -15 /kaggle/working/pilot_gpu*.log
!cd /kaggle/working && zip -qr frameguard_pilot.zip frameguard/runs* pilot_gpu*.log && ls -lh frameguard_pilot.zip
""")

md("""
## Cách đọc báo cáo
- **Bảng 1:** *hoàn thành* (task nên thành công) là chỉ số chính. Đối chứng không có model thích nghi (model phát lại,
  chạy sẵn trên máy): none 36% → bare/alignment 45% chỉ nhờ việc chặn. Phản hồi có tác dụng thật khi **vượt 45%** và `alignment` > `bare`.
- **Bảng 3:** McNemar `alignment vs bare`: p < 0.05 là khác biệt có ý nghĩa thống kê.
- **Bảng 4:** sau khi bị chặn, model *làm theo chuỗi sửa* bao nhiêu %.
- **Bảng 6:** nhiễu giữa các lần chạy — để biết chênh lệch nào là thật.
""")

for c in cells:
    c["source"] = ["".join(c["source"]).replace("{TITLE}", P["title"]).replace("{PART}", P["PART"])
                   .replace("{MODES}", P["MODES"]).replace("{THINKING}", P["THINKING"])]
    c["source"] = c["source"][0].splitlines(True)
nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"},
                                   "kaggle": {"accelerator": "nvidiaTeslaT4", "isInternetEnabled": True, "isGpuEnabled": True}},
      "nbformat": 4, "nbformat_minor": 5}
out = os.path.join(ROOT, "notebooks", P["out"])
json.dump(nb, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", out, len(cells), "cells")
