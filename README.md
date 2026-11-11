# FrameGuard

**DECLARE-based recovery feedback for small LLM agents.**
Khung Gate tất định, dùng chung cho nhiều benchmark tuân thủ quy trình (SOP): khi agent gọi tool vi phạm luật,
Gate chặn và trả phản hồi sinh từ template DECLARE / alignment để agent tự sửa.

Câu hỏi nghiên cứu (Agentic BPM): phản hồi theo ngữ nghĩa ràng buộc có giúp model open-weight 2–8B
hoàn thành task sau khi bị chặn không? Benchmark đầu tiên: SOPBench; tiếp theo SOP-Bench (Amazon), τ²-bench.
Mô tả đầy đủ, câu hỏi nghiên cứu và quyết định thiết kế: [`CLAUDE.md`](CLAUDE.md).
Kết quả hiện tại: [`analysis/FINDINGS.md`](analysis/FINDINGS.md).

## Cài đặt
```bash
bash scripts/setup.sh        # clone SOPBench (commit cố định) vào external/, tạo .venv Python 3.12
```

## Chạy phân tích (giai đoạn 1, offline, không gọi API)
```bash
.venv/bin/python analysis/conformance.py             # DECLARE conformance + đối chiếu oracle, 7 domain
.venv/bin/python analysis/summarize_conformance.py   # bảng vi phạm theo nhóm
.venv/bin/python analysis/alignment.py               # alignment, phản hồi, agent lý tưởng
python3 -I analysis/failure_taxonomy.py external/SOPBench/output   # phân loại heuristic (giai đoạn 0)
```

## Cấu trúc
- `analysis/declare_rules.py` — `load_rules(domain, task)`: luật SOPBench → DECLARE / MP-DECLARE
- `analysis/conformance.py` — phát lại trajectory, ghi vi phạm theo template, kiểm định với oracle SOPBench
- `analysis/alignment.py` — alignment tối ưu (chuỗi sửa tối thiểu) và phản hồi `template` / `alignment`
- `analysis/out/` — kết quả JSON
- `external/` — mã ngoài (không đưa lên git)
