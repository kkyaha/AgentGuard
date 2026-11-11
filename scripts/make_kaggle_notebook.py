"""Sinh notebook Kaggle thử nhanh (notebooks/kaggle_smoke_test.ipynb), nhúng sẵn mã FrameGuard để chỉ cần tải lên 1 file.

Chạy lại script này mỗi khi sửa mã:  python3 scripts/make_kaggle_notebook.py
"""
import json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOPBENCH_COMMIT = "8790ed7406acbd22270f90bd1c4038de3fc5db8f"
FILES = ["analysis/declare_rules.py", "analysis/conformance.py", "analysis/failure_taxonomy.py",
         "analysis/alignment.py", "analysis/oracle_fix.py", "frameguard/__init__.py", "frameguard/feedback.py",
         "frameguard/gate.py", "adapters/sopbench/runner.py", "adapters/sopbench/task_sets.json"]

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(True)})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": s.strip("\n").splitlines(True)})


md("""
# FrameGuard — thử nhanh trên Kaggle

Mục tiêu: trả lời nhanh 3 câu hỏi trước khi đầu tư tiếp.
1. **Chạy được không?** vLLM + Qwen3.5-2B (fp16 trên T4) có gọi tool đúng định dạng, có thinking.
2. **Có giống baseline công bố không?** Chế độ `none` (không Gate) trên 12 task bank so với kết quả SOPBench đã công bố.
3. **Có tín hiệu tích cực không?** Gate + phản hồi `alignment` có giúp model hoàn thành các task mà baseline thất bại không, so với `bare` (chỉ báo bị chặn).

**Thiết lập trước khi chạy** (cột phải → *Session options*):
- *Accelerator*: **GPU T4 x2**
- *Internet*: **On** (cần tài khoản đã xác minh số điện thoại)
- Bấm **Save Version → Save & Run All (Commit)** để chạy nền; có thể tắt trình duyệt.

Tập 12 task là **tập làm giàu**: 8 task mà Qwen3.5-2B đã thất bại vì bỏ bước kiểm tra + 4 task đã pass.
Không dùng để ước lượng pass rate, chỉ để xem có tín hiệu hay không.
""")

code("""
# ===== Cấu hình =====
MODEL    = "qwen3.5-2b"              # hoặc "gemma-4-e2b-it" (lưu ý: Gemma có thể không ổn định với fp16)
DOMAIN   = "bank"
MODES    = "none,bare,alignment"     # thêm reason,next_action,template nếu còn thời gian
TASK_SET = "smoke"                   # "smoke" (12 task) | "clean" (toàn bộ task sạch) | "8,67,81"
import os
os.environ["VLLM_DTYPE"] = "float16"          # T4 không hỗ trợ bf16 (SOPBench gốc dùng bf16)
os.environ["QWEN35_THINKING"] = "1"           # bản công bố chạy CÓ thinking
os.environ["GEMMA4_THINKING"] = "1"
# os.environ["VLLM_MAX_MODEL_LEN"] = "16384"  # bật nếu bị thiếu bộ nhớ (mặc định SOPBench: 32000)
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
WORK = "/kaggle/working/frameguard"
""")

code("""
!nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv
""")

code(f"""
%%bash
set -e
mkdir -p /kaggle/working/frameguard/external && cd /kaggle/working/frameguard/external
if [ ! -d SOPBench ]; then
  # bỏ thư mục output/ (1.9GB trajectory công bố) cho nhẹ
  git clone -q --filter=blob:none --no-checkout https://github.com/Leezekun/SOPBench.git
  cd SOPBench
  git sparse-checkout set --no-cone '/*' '!/output/'
  git checkout -q {SOPBENCH_COMMIT}
fi
echo "SOPBench @ $(git -C /kaggle/working/frameguard/external/SOPBench rev-parse --short HEAD)"
""")

code("""
%%bash
# vLLM 0.25.0 là bản SOPBench dùng cho Qwen3.5 / Gemma-4 (cài mất khoảng 5–10 phút)
pip install -q "vllm==0.25.0" 2>&1 | tail -3
pip install -q "openai>=1.71.0" "anthropic>=0.49.0" python-dotenv "pydantic>=2.9.2" termcolor colorama tqdm 2>&1 | tail -3
python -c "import vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
""")

md("## Mã FrameGuard (nhúng sẵn, sinh từ repo)")
for rel in FILES:
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    if not src.strip():
        src = "# (file trống)\n"   # %%writefile báo lỗi nếu thân ô trống
    code(f"%%writefile /kaggle/working/frameguard/{rel}\n{src}")
    # %%writefile cần thư mục tồn tại -> tạo trước
cells.insert([i for i, c in enumerate(cells) if c["cell_type"] == "markdown" and "Mã FrameGuard" in "".join(c["source"])][0] + 1,
             {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
              "source": ["!mkdir -p /kaggle/working/frameguard/analysis /kaggle/working/frameguard/frameguard "
                         "/kaggle/working/frameguard/adapters/sopbench"]})

md("""
## Bước 1 — kiểm tra 1 task (khởi động vLLM mất vài phút)
Nếu lỗi ở đây: xem log `[frameguard] vllm cmd` và thông báo của vLLM (thiếu bộ nhớ → bật `VLLM_MAX_MODEL_LEN`).
""")
code("""
!cd /kaggle/working/frameguard && python adapters/sopbench/runner.py --model $MODEL --domain $DOMAIN --modes none --task_set 8 2>&1 | grep -E "frameguard|Error|error|mode |^none" | tail -20
""".replace("$MODEL", "{MODEL}").replace("$DOMAIN", "{DOMAIN}"))

md("## Bước 2 — thử nhanh: 12 task × các chế độ")
code("""
!cd /kaggle/working/frameguard && python adapters/sopbench/runner.py --model {MODEL} --domain {DOMAIN} --modes {MODES} --task_set {TASK_SET} 2>&1 | grep -E "^\\[frameguard\\] (none|bare|reason|next|template|align)|^mode|^none|^bare|^reason|^next|^template|^alignment|phục hồi"
""")

md("## Bước 3 — đọc kết quả")
code("""
import json, glob, collections
PUBLISHED = {8:False,67:False,81:False,82:False,83:False,91:False,92:False,121:False,71:True,78:True,113:True,124:True}  # qwen3.5-2b công bố
rows = [json.load(open(f))["summary"] for f in glob.glob(f"{WORK}/runs/{DOMAIN}/{MODEL}/*/task_*.json")]
by = collections.defaultdict(dict)
for r in rows: by[r["mode"]][r["task"]] = r
print("Task  goal                     công bố | " + " | ".join(f"{m:>9s}" for m in by))
for t, pub in PUBLISHED.items():
    goal = next((by[m][t]["goal"] for m in by if t in by[m]), "?")
    cells = []
    for m in by:
        r = by[m].get(t)
        cells.append("    -    " if r is None else f"{'PASS' if r['success_fixed'] else 'fail'} b={r['n_blocked']:<2d}")
    print(f"{t:4d}  {goal:24s} {'PASS' if pub else 'fail':>6s} | " + " | ".join(f"{c:>9s}" for c in cells))
if "none" in by:
    agree = sum(by["none"][t]["success_fixed"] == p for t, p in PUBLISHED.items() if t in by["none"])
    print(f"\\nE0 — chế độ none khớp kết quả công bố: {agree}/{len(by['none'])}")
for m in by:
    fails = [t for t, p in PUBLISHED.items() if not p and t in by[m]]
    passes = [t for t, p in PUBLISHED.items() if p and t in by[m]]
    print(f"{m:10s}: cứu được {sum(by[m][t]['success_fixed'] for t in fails)}/{len(fails)} task từng thất bại; "
          f"giữ được {sum(by[m][t]['success_fixed'] for t in passes)}/{len(passes)} task từng pass; "
          f"trung bình {sum(r['seconds'] for r in by[m].values())/max(1,len(by[m])):.0f} giây/task")
""")

code("""
!cd /kaggle/working && zip -qr frameguard_runs.zip frameguard/runs && ls -lh frameguard_runs.zip
""")

md("""
## Cách đọc
| Câu hỏi | Tín hiệu tích cực | Nếu không đạt |
|---|---|---|
| Chạy được? | Bước 1 không lỗi, có tool call, `n_tool_calls` > 0 | thử `VLLM_MAX_MODEL_LEN=16384`; nếu kernel không hỗ trợ T4 → cần GPU đời mới (Colab L4/A100) |
| Giống baseline? | `none` khớp công bố ≥ 9/12 | fp16/T4 lệch nhiều → kết quả chính nên chạy bf16 |
| Có tín hiệu? | `alignment` cứu được ≥ 3/8 task thất bại **và** hơn `bare`, giữ được 4/4 task pass | xem `gate_log` trong file JSON: model lặp lời gọi bị chặn hay bỏ cuộc? |

Tải `frameguard_runs.zip` (tab *Output*) và gửi lại để phân tích chi tiết (mỗi task một file JSON: hội thoại, tool call, quyết định chặn, tin nhắn phản hồi).
""")

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"},
                                   "kaggle": {"accelerator": "nvidiaTeslaT4", "isInternetEnabled": True, "isGpuEnabled": True}},
      "nbformat": 4, "nbformat_minor": 5}
os.makedirs(os.path.join(ROOT, "notebooks"), exist_ok=True)
out = os.path.join(ROOT, "notebooks", "kaggle_smoke_test.ipynb")
json.dump(nb, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", out, len(cells), "cells")
