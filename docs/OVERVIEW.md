# FrameGuard, giải thích từ đầu

Toàn bộ dự án gói trong một câu:

> **Khi một "người gác cổng" tự động chặn một hành động sai của AI cỡ nhỏ, nên nói gì với AI để nó tự sửa và làm xong việc?**

Tài liệu đi theo thứ tự: bối cảnh, các khái niệm nền, những gì đã làm, số liệu, kế hoạch tiếp theo, và tài liệu nên đọc.

---

## 1. Bối cảnh: bài toán là gì

### 1.1 AI agent và tool
Một **LLM agent** là mô hình ngôn ngữ (như ChatGPT, Qwen, Gemma) được phép **gọi công cụ (tool)**, tức các hàm như `login_user`, `get_account_balance`, `cancel_credit_card`. Agent đọc yêu cầu của khách, tự quyết định gọi tool nào, đọc kết quả, rồi trả lời.

### 1.2 SOP: quy trình bắt buộc
Doanh nghiệp có **SOP (Standard Operating Procedure)**, tức các quy định bắt buộc. Ví dụ ở ngân hàng:
- Muốn hủy thẻ tín dụng thì khách phải **đăng nhập**, rồi **xác thực mật khẩu quản trị**, rồi phải **kiểm tra thẻ không còn nợ**.
- Nếu thẻ còn nợ thì **phải từ chối**.

Agent phải tuân thủ các luật này. Nếu bỏ bước kiểm tra mà hủy luôn, đó là vi phạm.

### 1.3 Vấn đề của model nhỏ
- Model lớn (GPT-5, Gemini) tuân thủ khá tốt.
- Model **nhỏ, mã nguồn mở, 2–8 tỷ tham số** (Qwen2.5-7B, Gemma-4-e2b…) thì rất kém. Theo số liệu đã công bố, Qwen2.5-7B chỉ đạt khoảng 11% trên SOPBench.
- Doanh nghiệp vẫn muốn dùng model nhỏ vì rẻ, chạy được nội bộ và giữ dữ liệu riêng tư.

### 1.4 Giải pháp hiện có: "người gác cổng" (gate)
Các nghiên cứu gần đây (ContrAgent, NOMOS) đặt một **gate tất định**, tức một đoạn code thường, không phải AI, đứng giữa agent và tool:
- Agent định gọi `cancel_credit_card` khi chưa đăng nhập, thì gate **chặn**.
- Nhờ vậy **an toàn được bảo đảm**: không có hành động sai nào được thực thi.

Nhưng có một lỗ hổng: **bị chặn rồi thì sao?** Model nhỏ thường lặp lại đúng lời gọi bị chặn, bỏ cuộc, hoặc từ chối khách sai. Kết quả là an toàn nhưng **không làm xong việc**.

### 1.5 Câu hỏi của dự án
Khi chặn, gate gửi lại một tin nhắn cho agent. **Tin nhắn đó viết thế nào thì model nhỏ phục hồi tốt nhất?**
- Chỉ nói "Bị chặn"?
- Giải thích lý do?
- Chỉ ra bước tiếp theo?
- Hay sinh tin nhắn có hệ thống từ **loại luật bị vi phạm**, dùng lý thuyết quản lý quy trình (BPM)?

Đây là đóng góp cho thách thức **X3, "giải thích có thể hành động"**, trong APM Manifesto, tức tài liệu định hướng của lĩnh vực Agentic BPM.

---

## 2. Kiến thức nền

### 2.1 Mô hình quy trình: mệnh lệnh và khai báo
Có hai cách mô tả một quy trình:
- **Mệnh lệnh (imperative):** vẽ sơ đồ từng bước, kiểu BPMN hay Petri net. Mọi đường đi đều phải vẽ ra.
- **Khai báo (declarative):** chỉ nêu **các ràng buộc**, còn lại tùy ý. Ví dụ: "phải đăng nhập trước khi hủy thẻ". Thứ tự các bước khác không quan trọng.

Luật của SOPBench là dạng "điều kiện tiên quyết", nên **dạng khai báo phù hợp hơn**. Đó là lý do dự án chọn DECLARE thay vì Petri net.

### 2.2 DECLARE
**DECLARE** là ngôn ngữ mô hình quy trình khai báo. Nó gồm một bộ **template**, tức các mẫu ràng buộc có tên. Dự án dùng mấy template sau:

| Template | Ý nghĩa | Ví dụ ngân hàng |
|---|---|---|
| **Precedence(Y, X)** | X chỉ được làm nếu Y đã xảy ra trước đó | phải `login_user` trước `cancel_credit_card` |
| **Branched Precedence({Y,Z}, X)** | trước X phải có Y **hoặc** Z | kiểm tra số dư bằng `get_account_balance` hoặc `internal_get_database` |
| **Existence(X)** | X phải xảy ra ít nhất một lần | task hợp lệ thì phải thực hiện hành động chính |
| **Absence(X)** | X không được xảy ra | task phải từ chối thì không được thực hiện |

Mỗi template thực chất là một công thức **LTLf** (logic thời gian trên chuỗi hữu hạn). Ví dụ Precedence(Y, X) viết là `(¬X U Y) ∨ G¬X`, đọc là "không có X cho đến khi có Y, hoặc không bao giờ có X". Không cần thành thạo LTLf, chỉ cần biết DECLARE có nền logic chặt chẽ.

### 2.3 MP-DECLARE: ràng buộc có điều kiện dữ liệu
DECLARE thường chỉ xét **thứ tự**. **MP-DECLARE** (Multi-Perspective) thêm **điều kiện dữ liệu**:
- *Điều kiện kích hoạt:* "chỉ được chuyển tiền **nếu số dư ≥ số tiền**".
- *Điều kiện tương quan:* "lần đăng nhập phải cùng `username` với lần chuyển tiền".

### 2.4 Conformance checking: kiểm tra tuân thủ
Trong **process mining**, conformance checking là đối chiếu **nhật ký thực tế** (trace, tức chuỗi hành động agent đã làm) với **mô hình luật**, để tìm vi phạm. Dự án dùng kỹ thuật này để phân loại lỗi của AI theo từng template bị vi phạm.

### 2.5 Alignment: cách sửa tối thiểu
**Alignment** là khái niệm trong conformance checking. Câu hỏi của nó: *"Phải chèn hoặc xóa ít bước nhất là bao nhiêu để trace trở nên hợp lệ?"*
- **Model move:** chèn một bước còn thiếu, ví dụ "chèn `login_user`".
- **Log move:** bỏ một bước không được phép, ví dụ "đừng hủy thẻ, hãy từ chối".

Chuỗi sửa tối thiểu này **chính là một chỉ dẫn hành động**. Dự án dùng nó để sinh tin nhắn phản hồi kiểu `alignment`.

### 2.6 Các kiểu phản hồi sẽ so sánh
Giả sử agent gọi `borrow_book` khi chưa kiểm tra sách còn hay không:

| Kiểu | Nội dung tin nhắn |
|---|---|
| `bare` | "BLOCKED." |
| `reason` | "Bị chặn vì vi phạm quy định mượn sách." |
| `next_action` (kiểu ContrAgent) | "Hãy gọi `internal_check_book_available` trước." |
| `template` | "Precedence bị vi phạm: phải gọi `internal_check_book_available` trước `borrow_book`." |
| `alignment` | "Các bước tối thiểu: 1. kiểm tra sách còn; 2. kiểm tra số sách đang mượn; 3. kiểm tra sách tồn tại. Chỉ gọi lại `borrow_book` nếu mọi bước đạt, nếu không thì báo khách là không thể thực hiện." |

### 2.7 Một số thuật ngữ khác
- **Tất định (deterministic):** cùng đầu vào thì luôn cùng đầu ra. Gate không dùng AI nên không "đoán".
- **Oracle:** bộ chấm điểm tự động của benchmark.
- **Pass rate:** tỷ lệ task làm đúng hoàn toàn.
- **Tỷ lệ phục hồi:** trong số task từng bị chặn ít nhất một lần, tỷ lệ cuối cùng vẫn làm đúng. Đây là chỉ số chính của dự án.
- **McNemar test:** kiểm định thống kê để so hai cấu hình trên **cùng một bộ task** (task nào cấu hình A đúng mà B sai, và ngược lại).
- **Open-weight:** model công bố trọng số, ai cũng tải về chạy được.
- **Function calling và ReAct:** hai cách để model gọi tool. Function calling dùng định dạng có cấu trúc, ReAct cho model viết "Thought/Action" bằng chữ. Model nhỏ ở chế độ ReAct hay bị vỡ định dạng.

---

## 3. Bộ dữ liệu: SOPBench

**SOPBench** (EMNLP 2026, hội nghị chính) là benchmark đo khả năng tuân thủ SOP:
- **7 domain:** ngân hàng, DMV (cục đăng kiểm xe), y tế, khách sạn, thư viện, chợ trực tuyến, đại học.
- **830 task.** Mỗi task gồm một yêu cầu của khách, một database, một bộ luật, và một nhãn cho biết task **nên thành công** hay **nên bị từ chối**.
- **167 tool** chạy được thật.
- **Oracle tự động** chấm 5 tiêu chí: không lỗi tool, không vi phạm điều kiện, database cuối đúng, quyết định làm/từ chối đúng, thứ tự đúng.
- **Khoảng 24 nghìn trajectory đã công bố** của nhiều model. Dự án dùng phần này để phân tích **miễn phí**, không tốn tiền gọi API.

Luật trong SOPBench có sẵn dạng máy đọc được: một đồ thị AND/OR ở mức tool, cộng một cây điều kiện. Nhờ vậy có thể dịch tự động sang DECLARE.

---

## 4. Những gì đã làm và số liệu

### 4.1 Giai đoạn 0: phân loại lỗi sơ bộ
Script `analysis/failure_taxonomy.py`. Kết quả chính: **64–90% lỗi của model nhỏ là bỏ bước kiểm tra**. Model mạnh thì sai theo hướng ngược lại: quá thận trọng, không chịu làm.

### 4.2 Giai đoạn 1: dịch luật sang DECLARE và kiểm tra tuân thủ

**Bước 1. Dịch luật** (`analysis/declare_rules.py`). Hàm `load_rules` biến luật SOPBench thành DECLARE và MP-DECLARE, áp cho **mọi action**.

**Bước 2. Kiểm định bản dịch** (`analysis/conformance.py`). Bộ kiểm tra của dự án chạy song song với oracle của SOPBench trên cùng các trace. Nếu hai bên kết luận giống nhau thì bản dịch đúng.

| Domain | Khớp phần thứ tự | Khớp phần dữ liệu |
|---|---|---|
| bank | 100% | 100% |
| dmv | 99,5% | 98,5% |
| healthcare | 99,9% | 99,5% |
| hotel | 96,2% | 99,2% |
| library | 98,9% | 93,3% |
| online_market | 100% | 100% |
| university | 99,7% | 99,7% |

Kết luận: **cách biểu diễn DECLARE mô tả đúng luật SOPBench.**

**Bước 3. Phân loại lỗi theo template.** Bảng dưới tính vi phạm **đầu tiên** trong các trace thất bại:

| Model | Pass | Bỏ bước trước hành động chính | Thiếu điều kiện ở action phụ | Kiểm tra rồi vẫn làm | Không hoàn thành |
|---|---|---|---|---|---|
| qwen2.5-7b | 10% | **91%** | 5% | 0% | 3% |
| llama3.1-8b | 15% | **82%** | 8% | 0% | 6% |
| gemma-4-e2b | 28% | **85%** | 8% | 2% | 3% |
| qwen3.5-2b | 50% | 38% | **32%** | 8% | 11% |
| gemma-4-e4b | 59% | **70%** | 14% | 2% | 9% |
| qwen3.5-4b | 73% | 27% | **27%** | **16%** | 16% |
| gpt-5 | 76% | 14% | 0% | 0% | **85%** |

Cách đọc bảng:
- **Model nhỏ yếu** gần như chỉ mắc một lỗi: **bỏ qua bước kiểm tra**.
- **Model nhỏ khá hơn** chuyển sang các lỗi tinh vi hơn: gọi tool phụ khi chưa đăng nhập, hoặc đã kiểm tra mà vẫn làm.
- **Model mạnh** lại quá thận trọng.

Vậy **kiểu lỗi đổi theo năng lực model**, và có lẽ kiểu phản hồi tốt nhất cũng đổi theo.

**Bước 4. Alignment** (`analysis/alignment.py`).
- **"Agent lý tưởng"**, tức một agent chỉ làm đúng theo tin nhắn alignment, pass **769/775 task (99,2%)**. Vậy **tin nhắn alignment chứa đủ thông tin để hoàn thành task**. Phần còn lại phụ thuộc model có làm theo được hay không. Đây là cận trên: giả định người dùng trả lời đúng và agent đọc đúng kết quả kiểm tra.
- Các bước alignment đề xuất **khớp 80–100%** với cách làm thật của model mạnh khi thành công.
- Model yếu thường cần **3–4 bước sửa trở lên** ngay lần bị chặn đầu tiên, còn model khá thường chỉ cần 1 bước. Vì vậy câu hỏi "phản hồi ngắn hay dài tốt hơn cho model yếu" là câu hỏi thật.

### 4.3 Ba lỗi của SOPBench do dự án phát hiện
1. **Bank:** `credit_cards` được lưu dạng danh sách nhưng code đọc như từ điển, nên không bao giờ tìm thấy thẻ. *Lỗi này Compile Then Page đã báo trước.*
2. **Bank:** hai tool `cancel_credit_card` và `pay_bill_with_credit_card` **không được khai báo cho agent**. Agent nhận "Tool not found" 189 lần, nên phải loại toàn bộ 21 task của hai goal này. *Phát hiện mới.*
3. **6 domain:** hệ thống chấm đặt trạng thái "đã đăng nhập" **trước khi** kiểm tra mật khẩu, nên đăng nhập sai vẫn được coi là đã đăng nhập. *Phát hiện mới.*

Ngoài ra, có 18 task hotel và 6 task library mà không model nào giải được, nguyên nhân chưa rõ. Mọi kết quả đều báo cáo trên **tập đã loại các task hỏng**.

---

## 5. Thiết kế đã chốt

### 5.1 Gate làm gì và không làm gì (cách 1)
- **Làm:** ép thứ tự (Precedence và các biến thể). Gate chỉ dựa trên **kết quả tool thật**. Ví dụ đăng nhập trả về False thì chưa coi là đã đăng nhập.
- **Không làm:** tự phán điều kiện dữ liệu, ví dụ "số dư có đủ không". Gate chỉ bảo đảm agent **đã gọi** bước kiểm tra và có kết quả trước mặt. Việc kết luận làm hay từ chối là của agent.
- **Lý do:**
  - Có khoảng 130 điều kiện dữ liệu khác nhau trên 7 domain. Viết hàm đánh giá cho từng cái vừa tốn công vừa khó tổng quát hóa.
  - Lỗi "kiểm tra rồi vẫn làm" trở thành **một biến cần đo**: phản hồi tốt có giúp agent tự rút kết luận đúng không?

### 5.2 Khung FrameGuard
- **Lõi** `frameguard/` không phụ thuộc bộ dữ liệu: biểu diễn luật, Gate, alignment, sinh phản hồi, ghi log, chỉ số.
- **Adapter** cho từng benchmark, mỗi adapter có 4 phần:
  1. luật → biểu diễn chung,
  2. diễn giải kết quả tool,
  3. điểm móc vào chỗ thực thi tool,
  4. oracle.
- Gate là **middleware**: chèn vào harness có sẵn của benchmark, không tự viết agent mới. Nhờ vậy kết quả so được với baseline.

### 5.3 Giả thuyết
- **H1:** Gate chặn được vi phạm, nhưng nếu chỉ nói "BLOCKED" thì model nhỏ không làm xong việc tốt hơn.
- **H2:** Phản hồi theo `template`/`alignment` cho tỷ lệ phục hồi cao hơn `bare`/`reason`.
- **H3:** Model yếu hợp với phản hồi ngắn, model khá hợp với chuỗi sửa đầy đủ.

---

## 6. Các nghiên cứu liên quan và vị trí của dự án

| Bài | Đã làm gì | Còn thiếu gì (chỗ của dự án) | Tình trạng |
|---|---|---|---|
| **SOPBench** | benchmark + oracle | không có gate | EMNLP 2026 |
| **ContrAgent** | gate LTLf→DFA trên SOPBench | chỉ chạy trực tiếp với Gemini; 1 kiểu phản hồi; không đo phục hồi | preprint |
| **NOMOS** | biên dịch policy thành gate | model 26B–70B; không so phản hồi | preprint |
| **Compile, Then Page** | biên dịch SOP thành chương trình | không chặn; thấy hướng dẫn **làm hại** Qwen2.5-7B | preprint |
| **Reason Less, Verify More** | gate trên τ²-bench, gpt-4o-mini | không so phản hồi, không đo phục hồi | workshop KDD |
| **Feedback That Backfires** | model nhỏ lặp lại lời gọi lỗi | model rất nhỏ (≤1,7B), không phải gate quy trình | workshop KDD |
| **AgentLTL** | đặc tả LTL + chặn | benchmark tổng hợp; không có model 2–8B chạy trực tiếp; không đo phục hồi | preprint |

**Khoảng trống của dự án:** đo **trực tiếp** trên model 2–8B, **so các kiểu phản hồi**, **đo khả năng phục hồi**, và dùng **DECLARE và alignment** để sinh phản hồi. Chưa bài nào làm đủ cả bốn điều này.

---

## 7. Kế hoạch tiếp theo

1. **Hoàn tất giai đoạn 1:** đọc tay khoảng 30 trajectory để kiểm chứng nhãn tự động.
2. **Tách code** thành `frameguard/` và `adapters/sopbench/`, rồi chạy lại để chắc kết quả không đổi.
3. **Giai đoạn 2:**
   - viết `check_env.py` để kiểm tra model gọi tool qua API;
   - chọn nhà cung cấp và cố định cấu hình;
   - chạy baseline không có Gate;
   - chạy với 5 kiểu phản hồi;
   - so sánh bằng McNemar.
4. **Mở rộng:** kiểm tra khả thi SOP-Bench (Amazon) làm bộ thứ hai. Bộ này có luật dạng văn bản, nên kiểm tra được khả năng tổng quát hóa. τ²-bench là bộ thứ ba nếu có ngân sách.

---

## 8. Tài liệu nên đọc (theo thứ tự ưu tiên)

### Tuần 1: hiểu bài toán
1. **SOPBench**: Li và cộng sự, *Evaluating Language Agents at Following Standard Operating Procedures and Constraints*, arXiv 2503.08669 (EMNLP 2026). Đọc kỹ phần thiết kế task và oracle.
2. **ContrAgent**: *Symbolic Temporal Supervision of LLM Agents Using Contracts*, arXiv 2609.18128. Đây là baseline chính.
3. **ReAct**: Yao và cộng sự, *ReAct: Synergizing Reasoning and Acting in Language Models*, ICLR 2023. Nền tảng về agent gọi tool.

### Tuần 2: nền tảng BPM và DECLARE
4. **Dumas, La Rosa, Mendling, Reijers**, *Fundamentals of Business Process Management* (sách). Đọc chương mở đầu và chương về process mining.
5. **Pesic, Schonenberg, van der Aalst** (2007), *DECLARE: Full Support for Loosely-Structured Processes*, EDOC. Bài gốc của DECLARE.
6. **Di Ciccio & Montali** (2022), *Declarative Process Specifications: Reasoning, Discovery, Monitoring*, chương trong *Process Mining Handbook* (LNBIP 448). **Tài liệu tham chiếu chính về DECLARE.**
7. **De Giacomo & Vardi** (2013), *Linear Temporal Logic and Linear Dynamic Logic on Finite Traces*, IJCAI. Chỉ cần đọc phần định nghĩa LTLf.

### Tuần 3: conformance checking và alignment
8. **Carmona, van Dongen, Solti, Weidlich** (2018), *Conformance Checking: Relating Processes and Models* (sách). Đọc chương về alignment.
9. **de Leoni, Maggi, van der Aalst** (2015), *An alignment-based framework to check the conformance of declarative process models…*, Information Systems. Alignment cho DECLARE, nền trực tiếp của kiểu phản hồi `alignment`.
10. **Burattin, Maggi, Sperduti** (2016), *Conformance checking based on multi-perspective declarative process models*, Expert Systems with Applications. Về MP-DECLARE.

### Tuần 4: các bài cùng hướng
11. **Compile, Then Page** (arXiv 2607.11346). Đặc biệt chú ý phần "hướng dẫn làm hại model yếu".
12. **Feedback That Backfires** (arXiv 2608.23651). Hiểu vì sao model nhỏ lặp lại lời gọi lỗi.
13. **NOMOS** (arXiv 2610.11030) và **Reason Less, Verify More** (arXiv 2607.07405). Gate trên τ²-bench.
14. **AgentLTL** (arXiv 2607.02599). Bài cần phân biệt rõ với dự án.
15. **FM SO.P** (arXiv 2602.09336). Hướng fine-tune, dùng làm đối chiếu.

### Khi chuẩn bị mở rộng
16. **SOP-Bench**: Amazon, KDD 2026 (arXiv 2506.08119).
17. **τ-bench / τ²-bench**: Yao và cộng sự, 2024 / Sierra Research.

### Thống kê
18. Bất kỳ tài liệu giới thiệu nào về **McNemar test**, đủ để hiểu vì sao dùng nó khi so hai cấu hình trên cùng tập task.

---

## 9. Các file trong dự án

| File | Nội dung |
|---|---|
| `CLAUDE.md` | mô tả đầy đủ dự án, quyết định, ràng buộc |
| `README.md` | cách cài đặt và chạy |
| `docs/OVERVIEW.md` | tài liệu này |
| `analysis/FINDINGS.md` | **toàn bộ số liệu và phát hiện**, nên đọc sau tài liệu này |
| `analysis/declare_rules.py` | dịch luật sang DECLARE |
| `analysis/conformance.py` | kiểm tra tuân thủ, đối chiếu oracle |
| `analysis/alignment.py` | alignment và sinh phản hồi |
| `analysis/out/` | kết quả dạng JSON |
| `scripts/setup.sh` | dựng lại môi trường |
