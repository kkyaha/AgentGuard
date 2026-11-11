# Dự án: Phục hồi sau khi bị chặn cho LLM agent cỡ nhỏ (SOPBench)

## Mục tiêu
Nghiên cứu Agentic BPM (thách thức X3 – giải thích có thể hành động – trong APM Manifesto).
Lớp kiểm soát tất định (ContrAgent, NOMOS) đã đảm bảo an toàn, nhưng model nhỏ (3–8B)
thường không hoàn thành task sau khi bị chặn. Câu hỏi chính:
**phản hồi sinh theo ngữ nghĩa ràng buộc DECLARE (template + alignment) có giúp model nhỏ phục hồi không?**

Đóng góp không nằm ở việc "đưa luật vào dạng hình thức" (ContrAgent/NOMOS/Compile-Then-Page đã làm),
mà ở: (1) chẩn đoán lỗi theo template DECLARE bị vi phạm, (2) phản hồi sinh từ template/alignment,
(3) đo trực tiếp khả năng phục hồi trên model 3–8B — chưa công trình nào làm (đối chiếu 2026-11-11).

## Câu hỏi nghiên cứu
- RQ1: Model nhỏ vi phạm template DECLARE nào, theo kiểu nào? Phân loại theo conformance checking:
  bỏ bước bắt buộc (Precedence) / hành động khi điều kiện dữ liệu sai (MP-DECLARE) / không hoàn thành (Existence)
  / lặp hành động bị chặn. Làm offline trên trajectory công bố (giai đoạn 1), sau đó trên trajectory có Gate (giai đoạn 2).
- RQ2: Kiểu phản hồi nào khôi phục tỷ lệ hoàn thành?
  `bare` / `reason` / `next_action` (kiểu ContrAgent) / **`template`** / **`alignment`** (chuỗi sửa tối thiểu),
  thêm biến thể xử lý lịch sử: giữ nguyên lời gọi bị chặn vs diễn đạt lại (xem Feedback That Backfires).
- RQ3 (để sau): Không chặn khi chỉ lệch thứ tự (operational) — dữ liệu SOPBench có rất ít ca loại này.

## Phát hiện đã có (giai đoạn 0, xem `analysis/FINDINGS.md`)
- 64–90% lỗi của model nhỏ là **bỏ bước kiểm tra** (vi phạm Precedence); "kiểm tra đủ rồi vẫn làm" ≈ 0.
  Giả thuyết "thiếu kỷ luật trạng thái" **không** được ủng hộ.
- Model mạnh lỗi theo hướng ngược lại (gpt-5: 85% lỗi là từ chối/bỏ cuộc).
- Oracle phạt cả lời gọi phụ thiếu tiền điều kiện → Gate và luật phải phủ **mọi action**, không chỉ user_goal.
- Task không giải được: bank — toàn bộ 21 task của cancel_credit_card, pay_bill_with_credit_card: (a) `credit_cards` là list nhưng code duyệt như dict
  (Compile-Then-Page đã báo, trích dẫn), (b) **schema tool của hai action này không được khai báo** → agent nhận "Tool not found" (phát hiện mới);
  hotel 18, library 6 (chưa rõ nguyên nhân). Danh sách loại trừ: `conformance.unsolvable()` + `BROKEN_GOALS`.
- Giai đoạn 1: ánh xạ DECLARE khớp oracle 96–100% (thứ tự), 93–100% (dữ liệu). Hỗn hợp vi phạm đổi theo năng lực:
  model yếu bỏ bước trước goal; model nhỏ khá vi phạm trên action phụ và "kiểm rồi vẫn làm"; model mạnh không hoàn thành.
  **Luôn báo cáo kết quả trên tập đã loại task không giải được**, kèm số trên tập đầy đủ.
- Rủi ro: Compile-Then-Page thấy hướng dẫn runtime làm Qwen2.5-7B giảm 14.4 điểm trên Bank → phản hồi dài có thể hại model nhỏ;
  đây cũng là một kết quả cần đo, không phải lý do bỏ.

## Biểu diễn luật: DECLARE / MP-DECLARE (không dùng BPMN/Petri net)
Petri net không hợp: luật SOPBench là cây điều kiện tiên quyết, không phải luồng; Petri net ép thứ tự và cần màu/dữ liệu cho OR, ngưỡng.

Nguồn luật trong SOPBench (đã kiểm tra với code):
- `task["directed_action_graph"]` (user_goal) và `env.helpers.dfsgather_ifg_func(..., "full")` (action khác):
  DAG AND/OR ở mức tool; node tool có thể có con (tiền điều kiện lồng nhau = Chain).
- `task["constraints"]` / `get_default_dep_full`: cây vị từ (`single`/`and`/`or`/`chain`/`gate`, tiền tố `not `).
  Vị từ trạng thái nối với tool qua `constraint_links`; vị từ dữ liệu được kiểm bằng nhóm tool thay thế `constraint_processes`.
- Oracle (`env/evaluator.py`): `dirgraph_satisfied` (thứ tự, chỉ xét có gọi + khớp tham số, không xét kết quả),
  `constraint_not_violated` (phát lại trên hệ thống strict), `database_match`, `action_called_correctly`.

| SOPBench | DECLARE | Ghi chú |
|---|---|---|
| Node tool → con là tool | Precedence(Y, X) | kèm điều kiện tương quan tham số (MP-DECLARE correlation) |
| Node `and` | Nhiều Precedence | thứ tự giữa các Y tùy ý |
| Node `or` (con đều là tool) | Branched Precedence({Y,Z}, X) | |
| Node `or` có con phức hợp | Lựa chọn giữa các nhóm Precedence (DNF) | ngoài DECLARE chuẩn, ghi rõ |
| Tool lồng nhau (Chain) | Precedence trên chính Y | |
| Vị từ dữ liệu của X | MP-DECLARE activation condition | đánh giá bằng phát lại strict |
| action_should_succeed | Existence(X) / Absence(X thành công) | |

**Phản hồi theo template:**
- Precedence chưa thỏa → "Cần gọi Y trước khi làm X".
- Precedence đã gọi nhưng kết quả không đạt / điều kiện dữ liệu sai → "Điều kiện Y không đạt: từ chối, không thử lại X".
- Branched Precedence chưa thỏa → "Cần một trong: Y hoặc Z".
- Existence chưa thỏa khi mọi điều kiện đạt → nhắc hoàn thành X (kiểm tra lúc kết thúc).

## Quyết định thiết kế Gate (2026-11-11)
- **Gate chỉ ép nhóm Precedence** (Precedence / Branched / Choice / Chain, kèm tương quan tham số), kiểm từ trace thật.
- **Gate không tự phán điều kiện dữ liệu** (~130 vị từ, ví dụ `sufficient_account_balance`): chỉ bảo đảm model đã gọi bước kiểm tra
  và đưa kết quả ra trước model; kết luận tiếp tục/từ chối để model làm. "Kiểm tra rồi vẫn làm" là **biến kết quả cần đo**, không bị chặn.
- Hệ thống strict / DB thật của SOPBench chỉ dùng cho phân tích offline và chấm điểm, **không bao giờ** cho Gate.
  Lưu ý: strict `login_user`/`authenticate_admin_password` đặt trạng thái trước khi kiểm thông tin (lỗi oracle, 6 domain).
- Tool tạo trạng thái (`constraint_links`: login, xác thực) chỉ thỏa Precedence khi **kết quả thật** trả về thành công.
- Alignment đã kiểm: agent lý tưởng làm theo phản hồi pass 99.2% (769/775 task sạch) — `analysis/alignment.py`.
- Alignment dùng chung mọi domain: chi phí 1/bước, hòa thì ưu tiên tool kiểm tra cụ thể hơn `internal_get_database`;
  tham số suy từ tương quan, tham số không suy được → "hỏi người dùng".

## Ràng buộc bắt buộc
- Chỉ model **open-weight 3–8B**; không fine-tune. Qwen2.5-7B/Llama-8B chỉ có số công bố ở chế độ ReAct;
  chạy chế độ function calling thì ghi rõ là không so được với mốc ~11%. Ưu tiên model còn nhiều dư địa (gemma-4-e2b, qwen3.5-2b, qwen2.5-7b).
- Bộ kiểm soát **tất định, không gọi LLM**; trạng thái chỉ cập nhật từ kết quả tool thật.
  Bộ diễn giải kết quả tool viết theo domain/tool, không theo task.
- Không viết prompt tay cho từng task; mọi phản hồi sinh từ template.
- Prompt hệ thống và định nghĩa tool của SOPBench **giữ nguyên** cho baseline.
- Tự chạy lại baseline cùng điều kiện; không so trực tiếp với số trong paper.
- Ghi log **mọi** trajectory ra JSON (mỗi task một file): model, nhà cung cấp, lượng tử hóa, cấu hình, tool call, kết quả,
  quyết định chặn, template vi phạm, tin nhắn phản hồi, số lần lặp lời gọi bị chặn.

## Hạ tầng
- Toàn bộ chạy qua API kiểu OpenAI (`BASE_URL`, `API_KEY`, `MODEL`); cố định một nhà cung cấp
  (OpenRouter: `provider.order` + `allow_fallbacks: false`), kiểm tra hỗ trợ function calling gốc.
- Python: `.venv` (3.12, tạo bằng uv) — SOPBench cần ≥3.10. Chạy `.venv/bin/python`.
- Mã ngoài: `external/SOPBench`, `external/ContrAgent` (chưa clone). Không sửa mã ngoài; sửa lỗi dữ liệu bằng danh sách loại trừ.

## Mã nguồn bên ngoài
- SOPBench (EMNLP 2026 Main): `https://github.com/Leezekun/SOPBench`
  - `env/evaluator.py` (oracle), `env/dep_eval.py` (đánh giá cây vị từ), `env/helpers.py` (dựng DAG), `env/task.py`
  - `env/domains/<d>/<d>_assistant.py`: `action_*_dependencies`, `constraint_links`, `constraint_processes`
  - `data/`, `output/<domain>/` (~24k trajectory), `run_evaluation.py` (cách trích tool call: chỉ lấy tool_call đầu mỗi tin nhắn)
- ContrAgent (preprint, baseline chính): `https://github.com/SponsioLabs/ContrAgent`.

## Kế hoạch
### Giai đoạn 1 – offline, không tốn API (đang làm)
1. ✅ `analysis/declare_rules.py`: `load_rules(domain, task)` → DECLARE/MP-DECLARE cho mọi action.
2. ✅ `analysis/conformance.py`: phát lại trajectory công bố, kiểm định với oracle (khớp 93–100%).
3. ✅ Bảng RQ1 sơ bộ (`analysis/summarize_conformance.py`, `analysis/FINDINGS.md`); còn: tách theo domain, kiểm định thống kê.
4. (Sau) Alignment tối ưu → chuỗi sửa tối thiểu, dùng cho phản hồi `alignment`.
5. Đọc tay ~30 trajectory để kiểm chứng nhãn.
### Giai đoạn 2 – gate chạy trực tiếp
6. `check_env.py` kiểm tra tool call qua API; chạy baseline Bank (tập clean) không Gate.
7. `frame_guard.py`: `Gate` + `FrameState` + các kiểu phản hồi; chèn vào vòng lặp SOPBench.
8. Chạy từng kiểu phản hồi; McNemar theo cặp.

## Chỉ số
Pass rate (tập clean và đầy đủ), tỷ lệ vi phạm theo template, tỷ lệ từ chối nhầm, **tỷ lệ phục hồi sau khi bị chặn**
(trong các task bị chặn ≥1 lần, tỷ lệ pass), số lần lặp cùng lời gọi bị chặn, số tool call và token mỗi task.
Baseline cận trên: gate tự từ chối/tự kiểm tra không qua LLM.

## Mở rộng sau (chưa làm)
- SOP-Bench (Amazon): 3–4 SOP, tự viết luật, kiểm tra tổng quát hóa.
- τ²-bench: khi có ngân sách user simulator.

## Công trình liên quan (tình trạng công bố kiểm tra 2026-11-11)
- SOPBench (arXiv 2503.08669) — **EMNLP 2026 Main**.
- ContrAgent (arXiv 2609.18128) — **preprint**. LTLf→DFA; chạy trực tiếp chỉ Gemini Flash/Flash-Lite; Qwen2.5-7B/Llama-8B chỉ replay offline;
  một kiểu phản hồi; không đo phục hồi.
- NOMOS (arXiv 2610.11030) — preprint (tác giả ghi workshop NeurIPS 2026, chưa xác minh). gemma-4-26B, Llama-70B; τ²/AgentDojo.
- Compile, Then Page (arXiv 2607.11346) — preprint. Không chặn (soft); paging hại model yếu; đã báo lỗi dữ liệu Bank.
- Reason Less, Verify More (arXiv 2607.07405) — workshop KDD-ETAAI '26. gpt-4o-mini, τ²-airline, +12.4pp.
- Feedback That Backfires (arXiv 2608.23651) — workshop KDD 2026. Model 135M–1.7B lặp lời gọi lỗi do dạng bề mặt còn trong ngữ cảnh;
  nguồn thứ cấp cho rằng xóa transcript tệ hơn diễn đạt lại — cần đọc bản gốc.
- FM SO.P (arXiv 2602.09336): fine-tune model nhỏ, Qwen2.5-7B 11.30% → 34.33%.
- Di Ciccio & Montali (2022), "Declarative Process Specifications": tham chiếu DECLARE.
