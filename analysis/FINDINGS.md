# Phân tích lỗi trên trajectory công bố của SOPBench (2026-11-11)

Script: `analysis/failure_taxonomy.py` (gán nhãn tự động theo flag của oracle + chuỗi tool call).
Dữ liệu: `external/SOPBench/output/<domain>/ast_*-tool_full-shuffle_False.json`, 7 domain, 830 task.

## Nhãn
- A = không kiểm tra / bỏ bước tiên quyết rồi hành động (Precedence bị vi phạm)
- C = kiểm tra một phần hoặc toàn bộ, điều kiện không đạt, vẫn hành động
- R = nên thành công nhưng không làm (từ chối sai / bỏ cuộc / gọi nhưng thất bại)
- F = lỗi định dạng / tool call

## Kết quả chính (gộp 7 domain)
| model | pass | % lỗi A+C (gate xử lý được) | % lỗi R | % lỗi F |
|---|---|---|---|---|
| qwen2.5-7b (react) | 9.0% | 90% | 6% | 4% |
| llama3.1-8b (react) | 14.6% | 71% | 10% | 19% |
| gemma-4-e2b (fc) | 27.0% | 80% | 8% | 12% |
| qwen3.5-2b (fc) | 46.6% | 71% | 17% | 10% |
| gemma-4-e4b (fc) | 55.9% | 76% | 15% | 6% |
| qwen3.5-4b (fc) | 68.7% | 64% | 22% | 9% |
| gpt-4o (fc) | 60.1% | 74% | 17% | 5% |
| o4-mini-high (fc) | 75.3% | 50% | 38% | 7% |
| gpt-5 (fc) | 72.9% | 11% | 85% | 2% |

1. Model nhỏ thất bại chủ yếu vì **bỏ bước kiểm tra** (A), không phải vì "kiểm tra rồi phớt lờ".
   Nhãn "kiểm tra đủ rồi vẫn làm" gần như bằng 0 ở mọi model → giả thuyết "thiếu kỷ luật trạng thái" không được ủng hộ.
   Nhãn C (kiểm tra một phần) có đáng kể ở qwen3.5-2b/4b, gpt-4o.
2. Hướng lỗi ngược nhau: model nhỏ làm liều (A), model mạnh quá thận trọng (gpt-5: 85% lỗi là R).
3. Oracle phạt cả lời gọi phụ thiếu tiền điều kiện (vd. `get_credit_cards` khi chưa login) dù hành động chính đúng
   → Gate phải áp cho **mọi** action, không chỉ user_goal.
4. Qwen2.5-7B và Llama-3.1-8B chỉ có kết quả ở chế độ ReAct (không có fc); nhiều trajectory vỡ định dạng.

## Lỗi benchmark (task không giải được)
- Task không model nào giải được (trong 24–36 model): bank 15, hotel 18, library 6, dmv 1, online_market 1. Gần như tất cả là task should_succeed.
- Bank: `credit_cards` trong data là list các dict, code `bank.py` duyệt như dict (so dict với chuỗi) →
  `internal_check_credit_card_exist`/`cancel_credit_card` luôn False. Ít nhất 8 task bank (cancel_credit_card, pay_bill_with_credit_card) không giải được.
  `bank.py:202-203` còn có điều kiện bị đảo khi thêm thẻ.
- Hotel/library: chưa tìm nguyên nhân.

## Đối chiếu công trình liên quan (2026-11-11; một phần chỉ đọc qua tóm tắt, cần kiểm lại bản PDF)
- Compile, Then Page (2607.11346) **đã phát hiện** lỗi cancel_credit_card / pay_bill_with_credit_card và loại 9 task Bank
  (bộ "clean" 125 task) → dùng lại bộ loại trừ của họ và trích dẫn, không coi là đóng góp mới.
  Runtime của họ không chặn (soft enforcement). Paging làm Qwen2.5-7B giảm 14.4 điểm trên Bank (cảnh báo: thêm hướng dẫn có thể hại model nhỏ).
- ContrAgent (2609.18128): chạy trực tiếp chỉ với gemini-2.5-flash / flash-lite; Qwen2.5-7B, Llama-8B chỉ có replay offline
  (recall ~78–79%, FPR 2.5–4.5%). Phản hồi = id contract + giải thích + hành động tiếp theo. Không so kiểu phản hồi, không đo phục hồi.
- NOMOS (2610.11030): gemma-4-26B, Llama-3.3-70B trên τ²/AgentDojo; phản hồi = id luật + điều khoản; không so kiểu phản hồi, không đo phục hồi.
- Reason Less, Verify More (2607.07405): gpt-4o-mini trên τ²-airline, +12.4pp; không so kiểu phản hồi; có ca agent lặp vào lời từ chối.
- Feedback That Backfires (2608.23651): model 135M–1.7B; tác hại chủ yếu do lời gọi lỗi còn nằm trong ngữ cảnh.

## Giai đoạn 1: conformance checking DECLARE (2026-11-11)
Script: `analysis/declare_rules.py` (load_rules), `analysis/conformance.py` (phát lại + kiểm định), `analysis/summarize_conformance.py`.
Chạy: `.venv/bin/python analysis/conformance.py && .venv/bin/python analysis/summarize_conformance.py`

**Kiểm định ánh xạ với oracle SOPBench** (cùng trace, 9 model):
| domain | thứ tự (dirgraph) | dữ liệu (constraint) | pass/fail |
|---|---|---|---|
| bank | 100% | 100% | 99.8% |
| dmv | 99.5% | 98.5% | 99.1% |
| healthcare | 99.9% | 99.5% | 99.5% |
| hotel | 96.2% | 99.2% | 99.4% |
| library | 98.9% | 93.3% | 94.1% |
| online_market | 100% | 100% | 99.5% |
| university | 99.7% | 99.7% | 99.2% |
Hai quirk của oracle được giữ để đối chiếu: (a) phụ thuộc bẩm sinh chỉ xét nhánh đầu của and/or;
(b) `constraint_not_violated` gộp cả vị từ trạng thái (chưa login) — DECLARE tách thành Precedence.

**Vi phạm đầu tiên trong trace thất bại (% số trace thất bại, 7 domain, đã loại task hỏng):**
| model | pass | G1 Prec. goal bỏ bước | G2 Prec. action phụ | G3 dữ liệu: kiểm rồi vẫn làm | G6/G7 không hoàn thành |
|---|---|---|---|---|---|
| qwen2.5-7b (react) | 9.7% | 91% | 5% | 0% | 3% |
| llama3.1-8b (react) | 15.2% | 82% | 8% | 0% | 6% |
| gemma-4-e2b | 28.3% | 85% | 8% | 2% | 3% |
| qwen3.5-2b | 49.5% | 38% | 32% | 8% | 11% |
| gemma-4-e4b | 58.5% | 70% | 14% | 2% | 9% |
| qwen3.5-4b | 72.5% | 27% | 27% | 16% | 16% |
| gpt-4o | 63.5% | 59% | 4% | 14% | 12% |
| o4-mini-high | 79.0% | 55% | 3% | 4% | 30% |
| gpt-5 | 76.3% | 14% | 0% | 0% | 85% |

Nhận xét:
1. Model nhỏ yếu: >80% lỗi là bỏ bước bắt buộc trước goal → phản hồi Precedence là then chốt.
2. Model nhỏ khá hơn (qwen3.5-2b/4b): lỗi chuyển sang action phụ thiếu tiền điều kiện (G2, chủ yếu thiếu login_user,
   get_order_details) và "kiểm tra rồi vẫn làm" (G3, 16% ở qwen3.5-4b). Bảng heuristic giai đoạn 0 báo G3≈0 vì đòi kiểm đủ mọi điều kiện — conformance theo từng vị từ sửa lại kết luận này.
3. Model mạnh: lỗi là Existence (không làm dù được phép) → cần kiểm tra lúc kết thúc, Gate không giúp.
4. Tiền điều kiện bị bỏ nhiều nhất (model nhỏ): internal_get_interaction_time (288), get_product_details|internal_get_database (177),
   show_available_rooms (146), login_user (118 trên goal + 189 trên action phụ).
5. Phần Gate có thể bắt (G1–G5): ~97% lỗi của qwen2.5-7b/gemma-e2b, ~84% qwen3.5-2b, ~76% qwen3.5-4b.

**Lỗi benchmark mới:** `bank_assistant.py` không khai báo schema tool `cancel_credit_card` và `pay_bill_with_credit_card`
(trajectory nhận "Error: Tool ... not found", 189 lần) → loại toàn bộ 21 task của hai goal này (không chỉ 9 task should_succeed như Compile-Then-Page).

## Alignment (2026-11-11) — `analysis/alignment.py`
Gate theo cách 1 (chỉ Precedence; tool tạo trạng thái chỉ tính khi kết quả thật thành công). Chi phí: 1/bước, DB dump = 2.
- **Agent lý tưởng** (chỉ làm theo phản hồi alignment, người dùng trả lời đúng, đọc đúng kết quả kiểm tra) pass oracle:
  bank 100%, dmv 97.9%, healthcare 99.2%, hotel 100%, library 96.7%, online_market 99.4%, university 100% → **769/775 = 99.2%**.
  → Phản hồi alignment là ĐỦ để hoàn thành; khoảng cách còn lại do model. (Cận trên: giả định model đọc đúng kết quả kiểm tra.)
- Bước alignment đề xuất có trong trace thành công của model mạnh: 80% (bank) – 100% (dmv, university).
- Độ dài chuỗi sửa ở lần chặn đầu: model nhỏ yếu thường cần 3–4+ bước (qwen2.5-7b hotel: 74/174 cần ≥4);
  model nhỏ khá chủ yếu 1 bước. → so `template` (1 bước) với `alignment` (đủ chuỗi) là câu hỏi thật.
- Tỷ lệ phải hỏi người dùng (mật khẩu, định danh) phụ thuộc domain: bank 65–88%, hotel 0–10%.

**Lỗi oracle SOPBench mới:** `*_Strict.login_user` / `authenticate_admin_password` gọi `state_tracker.set_*` TRƯỚC khi kiểm tra
thông tin đăng nhập (bank, dmv, healthcare, library, online_market, university) → đăng nhập sai vẫn được coi là đã đăng nhập.
Oracle vẫn phạt nhờ `action_should_succeed`, nhưng trạng thái trung gian của hệ thống strict sai.

## Đọc tay 32 trajectory thất bại của model nhỏ (2026-11-12)
Mẫu phân tầng theo nhóm, seed 7 (G1:8, G1b:1, G2:6, G3:5, G4:2, G5:2, G6:3, G7:2, G0:3).
| Nhóm | Nhãn đúng nguyên nhân | Ghi chú |
|---|---|---|
| G1 bỏ bước trước goal | 8/8 | gọi thẳng goal hoặc thiếu đúng bước kiểm tra; #2 còn làm tiếp sau khi login thất bại |
| G1b | 1/1 | thiếu kiểm tra tham số thứ hai (target_owner) |
| G2 action phụ | 6/6 | **5/6 quyết định cuối ĐÚNG** (từ chối/hoàn thành đúng), trượt chỉ vì gọi tool đọc phụ (get_order_details, check_return_date) thiếu tiền điều kiện → oracle rất chặt; liên quan RQ3 |
| G3 kiểm rồi vẫn làm | 5/5 | đúng hơn nên gọi là "đã lấy dữ liệu nhưng phán sai" (so sánh số, ngày, tổng tiền), không phải phớt lờ kết quả False |
| G4 | 0/2 | #21 lỗi giả: logout sau khi đóng tài khoản; #22 vị từ chỉ trên tham số, nhãn "chưa kiểm tra" vô nghĩa |
| G5 | 1/2 | #24 thực chất là bịa tham số (new_major sai) |
| G6 | 2/3 | #27 thực chất là bịa tên tool |
| G7 | 0/2 | **lỗi oracle** (xem dưới): model làm đúng nhưng bị chấm trượt |
| G0 | 2/3 | lỗi gọi tool sai tham số; #30 chưa rõ |
Tổng: **25/32 (78%)** đúng nguyên nhân; các nhóm lớn G1/G2/G3 đúng 20/20. Sai số tập trung ở nhóm nhỏ (<15% lỗi của model nhỏ).

**Lỗi oracle thứ 4:** `swarm/core.py` (bản mới) bỏ cờ của kết quả tuple `(True, value)` trước khi ghi log
→ `action_successfully_called` luôn False với goal trả tuple → task should_succeed của các goal đó không thể pass ở mọi lượt chạy mới
(gpt-5, o4-mini, qwen3.5, gemma-4, qwen2.5-7b, llama-8b; lượt cũ như gpt-4o ghi "(True, ...)" nên không bị).
Sửa trong `analysis/oracle_fix.py`: pass rate tăng +0.5 đến +1.8 điểm (qwen3.5-4b 72.5→74.3, gpt-5 76.3→77.9).
Goal should_succeed không model nào pass: dmv/update_test_status, hotel/{find_booking_info, process_guest_checkin, process_guest_checkout, show_available_rooms}, library/{add_book, check_return_date}.

**Hệ quả cho giai đoạn 2:**
- Harness của ta phải giữ cờ thành công khi ghi log và chấm bằng oracle đã sửa.
- Lời gọi bị Gate chặn vẫn bị tính vào `max_num_actions=10` của SOPBench → phải quyết định có tính hay không và báo cáo.
- Báo cáo pass rate hai cách: oracle gốc và oracle "không phạt lời gọi đọc phụ" (RQ3).

## Thử nhanh trên Kaggle (2026-11-12) — Qwen3.5-2B, vLLM 0.25 fp16, T4, thinking bật, bank, 12 task làm giàu
- E0 (`none`) khớp kết quả công bố 9/12; ~1/4 task đổi kết quả giữa các lần chạy → pilot cần chạy lặp.
- **Lỗi chấm điểm của runner (đã sửa):** lời gọi bị Gate chặn vẫn nằm trong log nên oracle phạt như đã thực thi
  → mọi task bị chặn đều trượt. Lần chạy đầu "0/7" là do lỗi này. Nay loại lời gọi bị chặn khỏi phần chấm
  (ghi thêm `success_with_blocked`).
- **Gate tự "cứu" task nên-từ-chối chỉ bằng việc chặn** (model phát lại không đọc phản hồi: 4/12 → 9/12).
  → Báo cáo tách: hoàn thành (task nên thành công = phục hồi) và từ chối đúng; dùng model phát lại làm đối chứng.
- Kết quả (4 task alignment 8/67/92/121 là kết quả cũ chấm lại; runner đã sửa để không dùng nhầm file cũ):
  | | none | bare | alignment |
  |---|---|---|---|
  | Hoàn thành (5 task nên thành công) | 1/5 | 3/5 | 4/5 |
  | Từ chối đúng (7 task nên từ chối) | 4/7 | 7/7 | 7/7 |
  Model 2B có phục hồi thật (thinking trích đúng phản hồi rồi làm theo). alignment > bare rõ nhất ở task 78
  (bare lạc sang open_account/set_admin_password). Task 67: khách không có mật khẩu → cần đường thay thế
  (internal_get_database) — đã thêm vào phản hồi (template/alignment), chưa thử.
- Tín hiệu đủ để làm pilot, chưa đủ để báo cáo (12 task làm giàu, 1 lần chạy).

## Đối chứng pilot: model phát lại qua Gate (bank, 105 task sạch, không cần GPU)
Model không thích nghi (trajectory công bố của qwen3.5-2b phát lại), chỉ có tác dụng của việc chặn:
| | none | bare | alignment |
|---|---|---|---|
| Pass | 46/105 (44%) | 84/105 (80%) | 84/105 (80%) |
| Hoàn thành (33 task nên thành công) | 12/33 (36%) | 15/33 (45%) | 15/33 (45%) |
| Từ chối đúng (72 task nên từ chối) | 34/72 (47%) | 69/72 (96%) | 69/72 (96%) |
→ Ngưỡng cho pilot thật: phản hồi có tác dụng khi **hoàn thành > 45%** và alignment > bare.
Runner song song (6–8 luồng) cho kết quả giống hệt chạy tuần tự trên cả 315 lượt (kể cả gate_log).

## Pilot thật (2026-11-13) — Qwen3.5-2B, thinking bật, vLLM 0.25 fp16, 2×T4, bank, 105 task sạch
code_version `ad4aff198756` cho mọi lượt. none/bare r0: `pilot.log` (chỉ có dòng log mỗi task, file JSON chi tiết đã mất);
alignment r0 + lặp r1/r2: `frameguard_pilot.zip` (JSON đầy đủ).
| | none | bare | alignment |
|---|---|---|---|
| Pass | 53/105 (50%) | 97/105 (92%) | 98/105 (93%) |
| Hoàn thành (33 nên thành công) | 15/33 (45%) | 27/33 (82%) | 29/33 (88%) |
| Từ chối đúng (72) | 38/72 (53%) | 70/72 (97%) | 69/72 (96%) |
| Phục hồi (pass / bị chặn ≥1) | – | 46/53 (87%) | 54/59 (92%) |
| Lặp lại lời gọi bị chặn | – | 40 | 12 |
McNemar chính xác (b = A pass & B trượt, c = ngược lại):
- bare vs none: mọi task 45/1 p=1e-12; nên thành công 12/0 p=0.0005.
- alignment vs none: mọi task 48/3 p=2e-11; nên thành công 15/1 p=0.0005.
- **alignment vs bare: mọi task 6/5 p=1.0; nên thành công 4/2 p=0.69; task bare bị chặn 6/2 p=0.29 → chưa phân biệt được.**
Hoàn thành vượt mốc model phát lại (45%) rất xa → tác dụng không chỉ đến từ việc chặn, model thật sự sửa theo phản hồi.
Hành vi sau lần chặn đầu (alignment): làm theo chuỗi sửa 68%, dừng/hỏi khách 19%, đổi hướng 10%, lặp đúng lời gọi 3%.
Alignment trượt 7: action_called_correctly 6, constraint_not_violated 3, database_match 2.
Nhiễu (30 task chạy lặp): alignment 29/29/26, none 16/16/15; 10% task alignment đổi kết quả giữa các lần
→ chênh lệch 1–2 task giữa alignment và bare nằm trong nhiễu.
Kết luận: Gate + phản hồi bất kỳ tăng mạnh (50% → 92–93%); ở bank với model 2B thinking, phản hồi trần đã gần trần,
alignment chỉ hơn về quá trình (ít lặp chặn hơn 3 lần). Để tách alignment khỏi bare cần điều kiện khó hơn:
tắt thinking (E2), domain nhiều nhánh/tham số hơn (hotel, E3), model khác (Gemma-4-E2B, E4).

## E2 (2026-11-13) — như pilot nhưng thinking TẮT, 5 chế độ — `runs/e2_nothink/`
| | none | bare | next_action | template | alignment |
|---|---|---|---|---|---|
| Pass | 23/105 (22%) | 77 (73%) | 83 (79%) | **86 (82%)** | 83 (79%) |
| Hoàn thành (33) | 4 (12%) | 12 (36%) | 19 (58%) | 19 (58%) | 18 (55%) |
| Từ chối đúng (72) | 19 (26%) | 65 (90%) | 64 (89%) | 67 (93%) | 65 (90%) |
| Phục hồi | – | 54/73 (74%) | 61/73 (84%) | 63/72 (88%) | 61/73 (84%) |
| Lặp lời gọi bị chặn | – | 36 | 10 | 10 | 9 |
| Làm theo chuỗi sửa sau lần chặn đầu | – | 63% | 93% | 86% | 89% |
McNemar (mọi task / nên thành công): template vs bare 12/3 p=0.035 / 8/1 p=0.039 (chưa hiệu chỉnh nhiều phép so;
Holm trên 8 cặp → không còn ý nghĩa); alignment vs bare 12/6 p=0.24 / 9/3 p=0.15; next_action vs bare 12/6 p=0.24 / 9/2 p=0.07;
alignment vs next_action 3/3 p=1.0; alignment vs template 2/5 p=0.45. Nhiễu: alignment 26/26 (r1/r2), 1/30 task đổi kết quả.
Kết luận:
- Tắt thinking làm model yếu đi nhiều (none 50% → 22%), bare không còn gần trần (92% → 73%);
  **phản hồi có thông tin (next_action/template/alignment) hơn bare ~6–9 điểm pass, ~20 điểm hoàn thành**, lặp chặn giảm 3–4 lần.
- **Ba kiểu phản hồi có thông tin ngang nhau.** Ở bank, 70% chuỗi sửa chỉ 1 bước (chủ yếu login_user) → alignment ≈ next_action
  về nội dung; chưa có điều kiện để alignment thể hiện khác biệt.
- Lỗi hoàn thành còn lại (alignment 15 task, các chế độ Gate tương tự) chia hai nhóm, **không phải lỗi phục hồi theo nghĩa hẹp**:
  (a) 8 task bị chặn ở **tool phụ không cần cho goal** (vd deposit_funds chỉ cần internal_check_username_exist, model gọi thêm
  get_account_balance → bị chặn → phản hồi bảo login_user → khách không có mật khẩu → hỏi đi hỏi lại tới hết lượt) — phản hồi
  hiện tại đẩy model vào đường cụt; (b) 6 task không bị chặn lần nào, model tự đòi xác thực thừa rồi không gọi goal
  (Existence không thỏa, Gate hiện không xử lý). Task alignment (a): 6, 28, 69, 70, 78, 98, 117, 122; (b): 30, 33, 35, 67, 111, 115.
- Hướng sửa (chưa làm): phản hồi **biết goal** — khi tool bị chặn là tool phụ và tiền điều kiện của goal đã thỏa, nói
  "X không cần cho yêu cầu này; điều kiện của goal đã đủ, có thể gọi goal"; với (b) cần kiểm tra Existence lúc kết thúc.

## Chưa làm
- Đọc tay ~30 trajectory lỗi (kiểm chứng nhãn tự động).
- Tìm nguyên nhân các task không giải được ở hotel/library.
