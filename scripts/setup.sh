#!/usr/bin/env bash
# Dựng lại môi trường: clone SOPBench đúng commit đã dùng, tạo .venv Python 3.12 bằng uv.
set -euo pipefail
cd "$(dirname "$0")/.."

SOPBENCH_COMMIT=8790ed7406acbd22270f90bd1c4038de3fc5db8f

mkdir -p external
if [ ! -d external/SOPBench ]; then
  git clone https://github.com/Leezekun/SOPBench.git external/SOPBench
fi
git -C external/SOPBench checkout -q "$SOPBENCH_COMMIT"

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user -q uv
  export PATH="$(python3 -c 'import site,os;print(os.path.join(site.USER_BASE,"bin"))'):$PATH"
fi
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -q -r external/SOPBench/requirements.txt
echo "Xong. Chạy phân tích: .venv/bin/python analysis/conformance.py"
