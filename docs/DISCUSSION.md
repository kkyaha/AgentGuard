# FrameGuard — tổng hợp lý do, kiến thức nền, kết quả và ý tưởng "phản hồi theo goal"

*Bản thảo luận, 2026-11-13. Số liệu chi tiết: `analysis/FINDINGS.md`. Giải thích cho người mới: `docs/OVERVIEW.md`.*

---

## 1. Lý do phát triển

**Bối cảnh.** LLM agent ngày càng được dùng trong quy trình nghiệp vụ (ngân hàng, y tế, bán hàng), nơi mọi thao tác phải theo
quy trình chuẩn (SOP): đăng nhập trước khi xem số dư, kiểm tra điểm tín dụng trước khi mở thẻ, v.v. Có hai cách làm agent tuân thủ:

1. **Đưa SOP vào prompt** và hy vọng model làm đúng. Model nhỏ vi phạm rất nhiều: trên SOPBench, phần lớn lỗi của model nhỏ là
   **bỏ bước kiểm tra** (64–90%, giai đoạn 0 của dự án).
2. **Lớp kiểm soát tất định** (runtime enforcement) chặn mọi lời gọi tool sai quy trình: ContrAgent, NOMOS. Cách này đảm bảo
   **an toàn** (không làm sai), nhưng không đảm bảo **hoàn thành** (làm được việc khách cần).

**Khoảng trống.** Sau khi bị chặn, agent phải tự sửa: gọi bước còn thiếu, hỏi khách, hoặc từ chối đúng. Model lớn tự làm được;
model nhỏ (2–8B — rẻ, chạy cục bộ, giữ dữ liệu riêng tư) thì không chắc. Các công trình hiện có:
- chạy trực tiếp chủ yếu với model lớn (ContrAgent: Gemini Flash; NOMOS: gemma-4-26B, Llama-70B);
- dùng **một** kiểu phản hồi khi chặn, **không đo** khả năng phục hồi;
- Compile-Then-Page thấy hướng dẫn runtime dài có thể **làm hại** model yếu (Qwen2.5-7B −14.4 điểm trên bank).

→ **Câu hỏi của dự án:** khi Gate chặn, **phản hồi phải chứa thông tin gì** để model nhỏ phục hồi và hoàn thành task?

**Vì sao dùng DECLARE.** Luật SOPBench là cây tiền điều kiện (AND/OR), khớp với họ ràng buộc Precedence của DECLARE. DECLARE cho:
(i) chẩn đoán *ràng buộc nào* bị vi phạm (thay vì chỉ "sai"), (ii) tính **alignment** — chuỗi bước sửa tối thiểu — theo cách
dùng chung cho mọi domain và benchmark. Đây cũng là chủ đề "giải thích có thể hành động" (thách thức X3) trong APM Manifesto.

---

## 2. Kiến thức nền cần nắm

| Chủ đề | Cốt lõi cần hiểu | Đọc |
|---|---|---|
| LLM agent dùng tool | vòng lặp: model sinh tool call → môi trường trả kết quả → model đọc tiếp; function calling gốc | ReAct (Yao et al., ICLR 2023); tài liệu function calling của OpenAI |
| SOPBench | 7 domain, task sinh bằng cách **thay đổi tập ràng buộc theo từng task**; oracle 5 tiêu chí; hệ thống "strict" để phát lại | arXiv 2503.08669 (EMNLP 2026); `external/SOPBench/env/` |
| Kiểm soát lúc chạy | chặn hành động vi phạm đặc tả trước khi thực thi | Shielding (Alshiekh et al., AAAI 2018); ContrAgent (arXiv 2609.18128); NOMOS (arXiv 2610.11030) |
| DECLARE / LTLf | ràng buộc khai báo trên trace hữu hạn: Precedence, Response, Existence…; MP-DECLARE thêm điều kiện dữ liệu | De Giacomo & Vardi (IJCAI 2013); Di Ciccio & Montali (2022) "Declarative Process Specifications" |
| Conformance checking & alignment | so trace thật với mô hình; alignment = chuỗi move (log move / model move) chi phí nhỏ nhất | Carmona et al. (2018) *Conformance Checking* (Springer) |
| Phản hồi cho LLM | model sửa theo phản hồi bằng ngôn ngữ; phản hồi có thể hại | Reflexion (Shinn et al., NeurIPS 2023); Self-Refine (Madaan et al., NeurIPS 2023); CRITIC (Gou et al., ICLR 2024); Feedback That Backfires (arXiv 2608.23651); Compile-Then-Page (arXiv 2607.11346); Reason Less, Verify More (arXiv 2607.07405) |
| Thống kê theo cặp | cùng task, hai chế độ → McNemar chính xác; nhiều phép so → hiệu chỉnh Holm; cỡ mẫu theo tỷ lệ cặp bất đồng | sách thống kê cơ bản; bài báo SOPBench dùng pass rate |

---

## 3. Đã làm gì và thấy gì

| Bước | Làm gì | Kết quả chính |
|---|---|---|
| Giai đoạn 0 | Phân loại lỗi trên ~24k trajectory công bố | Model nhỏ chủ yếu **bỏ bước kiểm tra**; model mạnh lại hay **từ chối thừa** |
| Giai đoạn 1 | Biên dịch luật SOPBench → DECLARE, phát lại trajectory | Khớp oracle 93–100%; agent lý tưởng làm theo alignment pass 99.2% |
| Lỗi benchmark | Đọc tay + kiểm code | 4 lỗi (2 mới): thiếu schema tool, strict login, mất cờ tuple…; loại task không giải được |
| Đối chứng | Model *phát lại* (không thích nghi) qua Gate | Hoàn thành 36% → 45%: mốc "chỉ nhờ chặn" |
| Pilot | Qwen3.5-2B, **thinking bật**, bank 105 task | Pass 50% → 92–93%; bare ≈ alignment (bare đã gần trần) |
| E2 | Như pilot, **thinking tắt**, 5 chế độ | Pass 22% → 73–82%; phản hồi có nội dung hơn bare ~20 điểm hoàn thành; next_action ≈ template ≈ alignment |
| Offline 7 domain | Đo độ dài chuỗi sửa khi chặn | 63–84% chuỗi sửa **chỉ 1 bước**; 50–69% lần chặn (bank, dmv, healthcare, online_market) rơi vào **tool phụ** |

**Điều rút ra**
- ✅ Gate giúp model nhỏ hoàn thành nhiều hơn rất rõ, không chỉ nhờ chặn (vượt xa mốc model phát lại).
- ✅ Có tương tác **suy luận × phản hồi**: thinking bật thì "bị chặn" là đủ; thinking tắt thì cần phản hồi nói rõ bước cần làm.
- ❌ "Alignment hơn next_action" không đứng: chuỗi sửa thường 1 bước, và next_action của dự án cũng lấy từ alignment
  → hai chế độ chỉ khác cách trình bày.
- ⚠️ 15 task alignment còn trượt (E2) **không phải do thiếu chỉ dẫn sửa**: 8 task bị phản hồi đẩy vào đường cụt, 6 task không
  bị chặn lần nào nhưng model không làm việc khách cần.

---

## 4. Ý tưởng: phản hồi theo goal

### 4.1 Quan sát dẫn tới ý tưởng (task 28, E2, chế độ alignment)
```
Khách: gửi 500 USD tiền mặt vào tài khoản john_doe          (goal = deposit_funds)
SOP của deposit_funds: chỉ cần internal_check_username_exist   ← đã làm, OK
Model: gọi thêm get_account_balance (không cần cho việc gửi tiền)
Gate : chặn → "bước tối thiểu: 1. login_user(username, identification)"
Model: hỏi khách mật khẩu → khách không có → hỏi lại … đến hết lượt → TRƯỢT
```
Phản hồi đúng về mặt cục bộ ("muốn gọi get_account_balance thì phải đăng nhập"), nhưng **sai về mục đích**: việc khách cần không
đòi hỏi tool đó. Gate trả lời câu hỏi "làm sao để X chạy được", trong khi câu model cần là "**X có cần cho việc khách muốn không,
và còn thiếu gì để làm việc đó**".

### 4.2 Hình thức hóa (vẫn tất định, vẫn từ mô hình DECLARE)
Gọi G là action khách yêu cầu, φ_G là công thức tiền điều kiện của G (nhóm Precedence), cone(G) là tập tool xuất hiện trong φ_G.
Khi Gate chặn lời gọi X:

| Trường hợp | Phản hồi |
|---|---|
| X = G | như alignment hiện tại: chuỗi bước tối thiểu để G hợp lệ |
| X ∈ cone(G) | chuỗi bước cho X; nếu có tool tạo trạng thái đã thất bại (vd login_user sai) thì chỉ nhánh `or` khác của G tránh tool đó |
| X ∉ cone(G) | "X không cần cho G". Kèm alignment của φ_G trên lịch sử hiện tại: rỗng → "điều kiện của G đã đủ; đọc kết quả kiểm tra rồi gọi G hoặc giải thích cho khách"; không rỗng → các bước còn thiếu của G |

Khác biệt với next_action (kiểu ContrAgent): next_action nhìn **cục bộ** vào lời gọi bị chặn. Phản hồi theo goal so lời gọi đó
với **mô hình ràng buộc của cả mục tiêu** — đúng phần mà cách tiếp cận DECLARE/alignment làm được và cách cục bộ thì không.

### 4.3 Hai biến thể (để tách phần đóng góp đến từ việc *biết goal*)
- **`goal` — Gate biết G.** Tình huống triển khai tương ứng: có bước phân loại yêu cầu (intent/ticket) đứng trước agent.
  Trình bày như **cận trên**.
- **`purpose` — Gate không biết G**, chỉ dùng luật: Precedence ngược, req(X) = {A : X ∈ cone(A)}. Phản hồi: chuỗi bước cho X, cộng
  "X chỉ cần cho A, B, C; nếu yêu cầu của khách không thuộc các thao tác này, bỏ qua X". Model tự đối chiếu với yêu cầu của khách.

### 4.4 Phạm vi tác dụng và dự đoán
- Offline: 50–69% lần chặn ở 4/7 domain là chặn tool phụ → ý tưởng áp dụng rộng, không riêng bank.
  (Ở hotel/university gần như không có chặn tool phụ → dự đoán không có tác dụng ở đó; đây là kiểm chứng âm hữu ích.)
- E2 bank: nhắm vào 8/15 task alignment trượt vì đường cụt. Dự đoán cứu được một phần; **không** cứu 6 task "không bị chặn" (lỗi
  Existence — Gate chỉ thấy tool call, không thấy lúc model dừng).
- Tiêu chí thành công (bank, thinking tắt): `goal` hơn next_action ≥ ~4 task và giảm rõ nhóm đường cụt; `purpose` nằm giữa.

### 4.5 Rủi ro
- Phản hồi dài hơn → có thể hại model yếu (Compile-Then-Page). Cần đo token và so với next_action.
- `goal` dùng thông tin model không có trong prompt → bị hỏi về tính công bằng; vì vậy bắt buộc có `purpose`.
- Model có thể bỏ qua câu "không cần X" và vẫn hỏi khách → cần xem hành vi sau khi bị chặn, không chỉ pass.

---

## 5. Vấn đề hợp lệ (đã kiểm 2026-11-13)

1. **Luật thay đổi theo task — hợp lệ.** SOPBench cố ý thay đổi tập ràng buộc của action goal theo từng task (bank: 69/105 task
   sạch có luật goal khác luật mặc định của domain; dmv 58/96; healthcare 65/124). **Agent được thấy đúng luật đó trong system
   prompt** (`env/task.py: task_initializer → gather_dependency_instructions`, dùng `constraints_original` của user_goal).
   → Gate dùng **cùng SOP đã đưa cho agent**, không dùng thông tin ẩn. Cần sửa câu trong CLAUDE.md "luật theo domain, không theo
   task" thành "luật = đúng SOP agent nhận được".
2. **Danh tính goal — là thông tin thêm.** Prompt **không** nói action nào là yêu cầu của khách. Hàm `alternative()` hiện tại dùng
   `task["user_goal"]` → câu "Alternative: …" trong chế độ template/alignment ở E2 (~14 lần chặn ở bank) có thông tin mà
   next_action không có. Ảnh hưởng có lẽ nhỏ nhưng phải ghi rõ, hoặc chạy lại template/alignment không có câu này.
3. **next_action là bản mô phỏng** kiểu phản hồi của ContrAgent (bước kế tiếp tính bằng alignment của dự án), không phải mã ContrAgent.

---

## 6. Khung bài đề xuất

**Định vị:** nghiên cứu thực nghiệm *phản hồi cần thông tin gì để model nhỏ phục hồi dưới Gate tất định*, với phản hồi theo goal
dựa trên DECLARE là biến thể chính được đề xuất. Bài đứng được dù `goal` thắng hay không.

- **RQ1** — Model nhỏ vi phạm ràng buộc DECLARE nào, theo kiểu nào (giữ nguyên).
- **RQ2** — Mức thông tin trong phản hồi: không nội dung (bare) → bước kế tiếp cục bộ (next_action) → chẩn đoán theo goal
  (`purpose`, `goal`). Template/alignment đầy đủ thành ablation về cách trình bày.
- **RQ3** — Phản hồi tương tác với khả năng suy luận của model (thinking bật/tắt) thế nào.
- **Phụ:** các lỗi của SOPBench (4 lỗi, 2 mới), danh sách task không giải được.

Quy mô cần cho bài: 7 domain (775 task sạch), ≥2 model (Qwen3.5-2B, Gemma-4-E2B), thinking tắt là cấu hình chính.
Ước tính ~17 giờ GPU (2×T4) mỗi model cho 4 chế độ; phát hiện được chênh lệch ~4–5 điểm.

---

## 7. Câu hỏi cần thảo luận

1. **Khung bài:** đồng ý định vị ở mục 6 (thực nghiệm + biến thể goal), hay giữ "DECLARE/alignment là đóng góp chính"?
2. **Gate có được biết goal không?** Làm cả `goal` (cận trên) và `purpose`, hay chỉ `purpose`?
3. **E2 có cần chạy lại** template/alignment không có câu Alternative để so công bằng với next_action?
4. **Lỗi Existence** (model không bị chặn nhưng không làm việc khách cần): chỉ đo và báo cáo như giới hạn, hay mở rộng Gate kiểm
   lúc kết thúc (phải can thiệp vào vòng lặp agent, trái nguyên tắc "chỉ là middleware ở chỗ thực thi tool")?
5. **Model thứ hai:** Gemma-4-E2B (cùng cỡ, khác họ) hay một model 7–8B (kiểm tra hiệu ứng có giảm khi model mạnh lên)?

## 8. Kế hoạch đề xuất (sau khi chốt mục 7)
1. Hoàn thiện `goal` + `purpose` (code đang sửa dở trong `frameguard/gate.py`, chưa nối với `feedback.py`), kiểm offline trên
   8 task đường cụt và bằng model phát lại.
2. E2b: bank, thinking tắt, `goal` + `purpose` (+ alignment không Alternative nếu chọn ở câu 3) — ~1–1.5 giờ GPU; so cặp với E2.
3. Điểm quyết định: nếu `goal`/`purpose` hơn next_action rõ → mở rộng 7 domain × 2 model; nếu không → giữ khung thực nghiệm,
   mở rộng với bare/next_action/alignment.
