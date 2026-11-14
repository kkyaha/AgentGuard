# FrameGuard — Tài liệu chuyển đổi hướng nghiên cứu (đến 2026-11-14)

Tài liệu ghi lại hướng nghiên cứu ban đầu, các bằng chứng đã làm hướng thay đổi, và hướng hiện tại.
Mỗi thay đổi đều nêu **bằng chứng → hệ quả**, để người đọc (giảng viên, đồng tác giả, chính mình sau này) thấy vì sao hướng đổi,
không chỉ thấy nó đã đổi.

Tài liệu liên quan: `CLAUDE.md` (trạng thái làm việc), `analysis/FINDINGS.md` (số liệu giai đoạn 1),
`docs/DISCUSSION.md` (thảo luận thiết kế), `docs/OVERVIEW.md` (giải thích cho người mới).

---

## 1. Tóm tắt một trang

| | Hướng ban đầu (2026-11-11) | Hướng hiện tại (2026-11-14) |
|---|---|---|
| Câu hỏi | Phản hồi sinh theo DECLARE (template + alignment) có giúp model nhỏ phục hồi sau khi bị chặn không? | Bộ giám sát tất định chặn agent thì nên **nói gì** (chẩn đoán / cách sửa / liên quan đến goal), và những gì việc chặn **không thể** xử lý (liveness) thì làm thế nào? |
| Động lực | "Model nhỏ không hoàn thành task sau khi bị chặn" | "Chặn đã khôi phục phần lớn; câu hỏi là phần dư" — và phần dư nằm ở task nên thành công |
| Vai trò DECLARE | Đóng góp chính ("phản hồi theo DECLARE") | Ngôn ngữ mô hình + bộ lý thuyết đi kèm (LTLf, giám sát RV-LTL, alignment, goal là công thức) làm **cơ sở** cho khung phản hồi |
| Đóng góp trung tâm | Template + alignment | Mức **liên quan đến goal** + phân biệt **safety/liveness** (trần của việc chặn) |
| Thiết kế thí nghiệm | Thang 5 chế độ (bare → alignment) | 3 yếu tố thông tin (chẩn đoán / sửa / liên quan goal) + nhắc nghĩa vụ liveness; giả thuyết ghi trước kèm ngưỡng |
| Tổng quát hóa | "Sau đó thêm benchmark" | Dự đoán trước theo domain bằng conformance offline; ≥2 benchmark, ≥2 họ model, lý tưởng gắn vào Gate có sẵn |
| Khẳng định tính mới | "Chưa công trình nào làm" | Hẹp: *phản hồi sinh từ cấu trúc ràng buộc (gồm liên quan đến goal), so có kiểm soát trên SOPBench với model 2–8B, đo hoàn thành sau chặn* |
| Model | 3–8B | 2–8B (thêm qwen3.5-2b, gemma-4-e2b) |

---

## 2. Dòng thời gian

| Ngày | Sự kiện | Ảnh hưởng tới hướng |
|---|---|---|
| 11-11 | Giai đoạn 1: ánh xạ SOPBench → DECLARE, conformance trên ~24k trajectory công bố, alignment | Xác nhận DECLARE mô tả đúng luật SOPBench (khớp oracle 93–100%) |
| 11-11 | Đổi tên FrameGuard; kiến trúc lõi tách khỏi bộ dữ liệu | Chuẩn bị cho nhiều benchmark |
| 11-12 | Đọc tay 32 trajectory; lỗi oracle thứ 4; mở rộng model sang 2–8B | Thêm hai model nhỏ nhất có baseline |
| 11-12 | Gate + 5 chế độ phản hồi, runner SOPBench, notebook Kaggle | Bắt đầu giai đoạn 2 (chạy trực tiếp) |
| 11-12/13 | Pilot (thinking bật) | `bare` gần trần → phải tắt thinking để có chỗ đo |
| 11-13 | E2 (thinking tắt) | 3 kiểu có nội dung ngang nhau; phát hiện 8 task đường cụt → ý tưởng `goal`/`purpose` |
| 11-14 | Kiểm harness với code; sửa Gate (tool không có, giá trị thất bại); thêm `goal`/`purpose` | Gate chỉ đề xuất tool agent có |
| 11-14 | Kiểm tính mới (AgentLTL, Bala và cộng sự, ContrAgent, NOMOS…) | Thu hẹp khẳng định; DECLARE-cho-agent không mới |
| 11-14 | Phản biện bên ngoài + kiểm lại số liệu E2 | Phát hiện 72/105 task là task nên từ chối → đổi chỉ số chính, viết lại động lực |
| 11-14 | E2b (7 chế độ) + phân tích từng task | `goal` sửa đường cụt 6/8; `purpose` thất bại; phần dư = liveness + dữ liệu |
| 11-14 | Lo ngại "quá chi tiết, thiếu tổng quát" | Nâng lên khung 3 câu hỏi + safety/liveness trên nền LTLf |

---

## 3. Hướng ban đầu (v0)

**Câu hỏi.** Lớp kiểm soát tất định (ContrAgent, NOMOS) bảo đảm an toàn, nhưng model nhỏ thường không hoàn thành task sau khi bị chặn.
Phản hồi sinh theo ngữ nghĩa DECLARE có giúp model nhỏ phục hồi không?

**Đóng góp dự kiến.** (1) chẩn đoán lỗi theo template DECLARE bị vi phạm; (2) phản hồi sinh từ template/alignment;
(3) đo phục hồi trên model 3–8B — "chưa công trình nào làm".

**Câu hỏi nghiên cứu.** RQ1 phân loại vi phạm theo template; RQ2 so `bare` / `reason` / `next_action` / `template` / `alignment`;
RQ3 (để sau) không chặn khi chỉ lệch thứ tự.

**Giả định ngầm** (về sau được kiểm và một số sai):
- G1. Model nhỏ thất bại vì không biết sửa → phản hồi giàu hơn sẽ tốt hơn theo thang.
- G2. "Hoàn thành" đo bằng pass trên mọi task.
- G3. DECLARE tự nó là điểm mới.
- G4. Alignment (chuỗi sửa đầy đủ) sẽ hơn template (một bước).
- G5. Cấu hình harness (thinking, tool có sẵn, người dùng giả) không ảnh hưởng nhiều.

---

## 4. Các bằng chứng làm thay đổi hướng

### 4.1 Giai đoạn 0–1 (offline, trajectory công bố)
| Bằng chứng | Hệ quả |
|---|---|
| 64–90% lỗi của model nhỏ là bỏ bước kiểm tra (Precedence); "kiểm rồi vẫn làm" ≈ 0 ở model yếu | Gate tập trung vào nhóm Precedence |
| Hỗn hợp lỗi đổi theo năng lực: model yếu bỏ bước trước goal; qwen3.5-2b/4b lỗi trên **tool phụ** (32%/27%) và "kiểm rồi vẫn làm"; gpt-5 85% là không hoàn thành (Existence) | Mầm của ý "nhu cầu thông tin đổi theo năng lực model" và của phân biệt liveness |
| Oracle phạt cả lời gọi phụ thiếu tiền điều kiện | Luật phải phủ **mọi action**, không chỉ goal |
| Agent lý tưởng làm theo alignment pass 99.2% (không có `internal_get_database`: 99.9%, xem 4.2) | Phản hồi alignment là **đủ** về mặt thông tin; khoảng cách còn lại do model |
| 70% chuỗi sửa ở bank chỉ 1 bước | Dự báo sớm rằng template ≈ alignment ở bank (G4 yếu) |
| Lỗi benchmark: schema `cancel_credit_card`/`pay_bill_with_credit_card` không khai báo; lỗi oracle login strict | Danh sách loại trừ; luôn báo cáo trên tập sạch |

### 4.2 Kiểm harness SOPBench với code (11-14)
| Bằng chứng | Hệ quả |
|---|---|
| Agent **không có** `internal_get_database`, nhưng DAG coi đó là nhánh OR hợp lệ; ở E2 Gate đã gợi ý nó 31 lần, 6 lần "Tool not found" | Gate lấy danh sách tool thật lúc chạy (`set_tools`), không đề xuất tool không có; agent lý tưởng 99.2% → 97.9%, rồi 99.9% sau khi sửa lỗi mô phỏng (login thiếu `identification`); bank 67 không giải được |
| Người dùng giả trả một câu cố định (`user_known` + nhắc `exit_conversation`) | Mọi phản hồi kiểu "hỏi khách" không kiểm được → giới hạn ngoại suy |
| `max_actions=10` tính cả lời gọi bị chặn | Nhiễu ngân sách: phản hồi tốt có thể thắng chỉ nhờ tiết kiệm lời gọi |
| Số công bố cho model nhỏ chạy **thinking bật** | Mốc so là `none` cùng lượt; ghi rõ cấu hình |
| Prompt dựng từ `constraints_original`; library 48 task, hotel 4 task oracle đòi nhiều hơn prompt | Xử lý trước khi mở rộng sang library |
| Chế độ `goal` dùng lại giá trị của lời gọi thất bại (task 122: gợi ý login lại bằng mật khẩu sai) | Chỉ lấy tham số từ lời gọi thành công; tham số nhiều giá trị để trống |

→ **G5 sai**: cấu hình harness ảnh hưởng đáng kể; mọi chi tiết này phải ghi trong bài.

### 4.3 Pilot (thinking bật)
`bare` đã gần trần (ghi chép cũ 92%; thư mục hiện chỉ còn đủ `alignment`: 29/33 task nên thành công, 98/105 mọi task).
→ Không phân biệt được các kiểu phản hồi. **Chuyển sang thinking tắt** để có chỗ đo; trở thành rủi ro "headroom" cần nói rõ.

### 4.4 E2 (thinking tắt, 5 chế độ)
Ban đầu đọc là "none 22% → bare 73% → template 82%". Ba kiểu có nội dung ngang nhau; template vs bare mất ý nghĩa sau Holm.
Phát hiện **8 task đường cụt**: bị chặn ở tool phụ không cần cho goal, phản hồi đẩy agent đi login mà khách không có mật khẩu.
→ Ý tưởng `goal` (Gate biết G) và `purpose` (không biết G, dùng Precedence ngược).

### 4.5 Kiểm tính mới (11-14)
| Công trình | Trùng | Khác |
|---|---|---|
| AgentLTL (arXiv 2607.02599) | Chặn trước bằng luật thời gian; nêu DECLARE là nguồn gốc | Không đổi nội dung phản hồi, không alignment, không goal, benchmark tổng hợp, model ≥26B (4B chỉ fine-tune) |
| Bala, Fournier, Limonad, Metzger (arXiv 2607.04948) | Declare cho agent, cộng đồng BPM | Khai phá Declare từ log để **sinh** agent; không chặn/phản hồi lúc chạy; case study |
| ContrAgent, NOMOS | Gate tất định, phản hồi có id luật + bước kế tiếp | Một kiểu phản hồi; model lớn; ContrAgent giảm ở healthcare vì agent không thử lại sau khi bị chặn |
| Outcome Monitors, Feedback That Backfires | Đã so nội dung phản hồi/lỗi | Không phải SOP, không Gate tất định theo ràng buộc |

→ **G3 sai**: "dùng DECLARE cho agent" và "so nội dung phản hồi" đều không mới. Khẳng định phải hẹp lại.

### 4.6 Phản biện bên ngoài và kiểm lại số liệu E2
Phản biện nêu: động lực mạnh hơn dữ liệu; DECLARE chủ yếu là tên gọi; thang 7 mức chưa có lý thuyết; khẳng định tính mới mâu thuẫn
với chính phần công trình liên quan; nhiễu ngân sách; người dùng giả; cỡ mẫu; `goal` dùng thông tin model không có.

Kiểm lại với dữ liệu cho thấy một điểm **cả phản biện lẫn tài liệu đều sai**:

| E2 | none | bare | next_action | template | alignment |
|---|---|---|---|---|---|
| pass mọi task /105 | 23 | 77 | 83 | 86 | 83 |
| **nên thành công /33** | 4 | 12 | 19 | 19 | 18 |
| nên từ chối /72 | 19 | 65 | 64 | 67 | 65 |

- 105 task = 33 nên thành công + **72 nên từ chối**. Bước none → bare chủ yếu là **từ chối đúng nhờ chặn**.
- Nội dung phản hồi tác động gần như hết ở task nên thành công (12 → 18–19/33, ~20 điểm) — "phần dư" lớn hơn phản biện tính.
- Nhiễu ngân sách có một phần: 3/9 task nội dung thắng bare là do bare hết 10 lời gọi.
- Đường cụt: bare pass 3/8, alignment 0/8 → phản hồi alignment làm **xấu hơn bare** ở nhóm này.

→ **G2 sai**: chỉ số chính đổi thành **pass trên task nên thành công**. Động lực viết lại theo "phần dư sau chặn".
→ Thang phản hồi được tổ chức lại thành 3 loại thông tin, mỗi loại gắn một kiểu thất bại (giả thuyết H1–H3).

### 4.7 E2b (thinking tắt, 7 chế độ, cùng phiên bản code)
| | none | bare | next_action | template | alignment | goal | purpose |
|---|---|---|---|---|---|---|---|
| pass /105 | 23 | 76 | 89 | 84 | 87 | **91** | 83 |
| nên thành công /33 | 4 | 12 | 21 | 18 | 20 | **25** | 20 |
| lặp chặn | 0 | 28 | 19 | 10 | 8 | 12 | 15 |
| đường cụt /8 | 0 | 3 | 3 | 1 | 2 | **6** | 3 |
| trượt vì hết ngân sách | 5 | 8 | 2 | 3 | 1 | 0 | 5 |

- Holm trên 13 cặp: chỉ next_action vs bare (14–1, p=0.001) và các chế độ vs none còn ý nghĩa.
- H2 ✓: thông tin cách sửa giúp hoàn thành (bare 12 → next_action 21/33).
- H1 ✓ một phần: chẩn đoán giảm lặp chặn (template 10 vs next_action 19) nhưng **không** tăng pass (template 0–5 next_action).
- H3 ✓ về cơ chế: `goal` sửa đường cụt 6/8 (vs next_action 4–1); trên task nên thành công 6–2, p=0.29 — chưa đủ ý nghĩa.
- `purpose` thất bại (thua goal 0–8, p=0.0078).
- Dao động do đổi code (next_action 83 → 89) cùng cỡ hiệu ứng `goal` → chỉ so trong cùng lượt.

→ **G1 và G4 sai một phần**: thông tin phản hồi không cộng dồn theo thang; mỗi loại sửa một kiểu lỗi riêng; chuỗi sửa đầy đủ
không hơn một bước khi chuỗi chỉ dài 1.

### 4.8 Phân tích từng task E2b
| Câu hỏi | Kết quả | Hệ quả |
|---|---|---|
| Có lần chặn nào "cần theo đồ thị nhưng không nằm trong chuỗi sửa tối ưu"? | 0/38 | Định nghĩa liên quan-theo-alignment không đổi kết quả bank; vẫn cài để định nghĩa chặt |
| Vì sao `purpose` hại? | (a) lỗi: liệt kê tool agent không có; (b) danh sách tới 10 action với login/admin; (c) câu "continue with the action the user asked for" đẩy model làm goal ở task nên từ chối (5/8 trận thua) | `purpose_v2` |
| Suy được G chỉ từ tiền tố trace không? | G trong ứng viên 40/73, top-1 chỉ 5/73 | Không làm `purpose` công bằng bằng cấu trúc; `goal` cần **định tuyến ý định** — đó là điều kiện áp dụng |
| 8 task `goal` còn trượt là gì? | 5 **Existence** (không gọi G, đa số không bị chặn lần nào, model đòi khách thông tin không cần) + 3 **điều kiện dữ liệu** (41, 115, 122) | Phần dư nằm đúng ở hai template ngoài nhóm Precedence → động lực cho liveness |

### 4.9 Lo ngại về tính tổng quát
Đổi domain: dữ liệu giai đoạn 1 cho thấy hỗn hợp lỗi khác hẳn nhau giữa domain (qwen3.5-2b, % lỗi đầu tiên trong trace trượt):

| | bank | dmv | healthcare | hotel | library | online_market | university |
|---|---|---|---|---|---|---|---|
| Precedence trên goal | 28 | 56 | 33 | 51 | 79 | 21 | 42 |
| Precedence trên tool phụ (đường cụt) | 57 | 30 | 27 | 0 | 3 | 66 | 0 |
| Existence | 8 | 12 | 20 | 18 | 8 | 7 | 0 |
| Kiểm rồi vẫn làm | 5 | 2 | 16 | 21 | 10 | 5 | 58 |

gemma-4-e2b: 65–99% là Precedence trên goal ở mọi domain.

→ Câu chuyện "goal sửa đường cụt ở bank" quá hẹp. Nhưng sự khác nhau giữa domain có thể biến thành **dự đoán kiểm được**:
tác dụng của mỗi can thiệp tỷ lệ với tỷ lệ kiểu lỗi nó nhắm tới. Đồng thời câu hỏi được nâng lên mức không phụ thuộc DECLARE hay
SOPBench (mục 5).

---

## 5. Hướng hiện tại (v3)

### 5.1 Bài toán
Các lớp kiểm soát tất định đã chặn được hành động sai, nhưng phản hồi khi chặn nghèo nàn (id luật + một câu).
Model nhỏ không biết làm gì tiếp. **Khi bộ giám sát chặn agent, nó nên nói gì để model nhỏ hoàn thành task —
và những gì việc chặn không xử lý được thì làm thế nào?**

### 5.2 Khung lý thuyết
Nền: **LTLf** (logic thời gian tuyến tính trên trace hữu hạn). **DECLARE** là bộ template LTLf có tên
(Existence = **F** G; Precedence(B, A) = (¬A) **U** B ∨ **G**¬A; Response = **G**(A → **F** B)…).
Đi kèm là lý thuyết giám sát lúc chạy và conformance checking của cộng đồng BPM.

**Phản hồi khi chặn trả lời ba câu hỏi, tính tất định từ mô hình:**
| Câu hỏi | Khái niệm | Chế độ |
|---|---|---|
| Sai gì? | Ràng buộc nào sắp vi phạm vĩnh viễn, template nào | `reason`, `template` |
| Sửa thế nào? | Prefix alignment chi phí nhỏ nhất (conformance checking online) | `next_action`, `alignment` |
| Sửa có phục vụ goal không? | Goal là công thức `Existence(G)`; activation không cần cho G → ràng buộc lẽ ra thỏa trống (predictive monitoring / operational support) | `goal` |

**Bốn trạng thái giám sát RV-LTL → hai loại can thiệp:**
| Trạng thái | Loại ràng buộc | Can thiệp |
|---|---|---|
| Sắp vi phạm vĩnh viễn (Precedence, Absence) | **Safety** | Chặn + phản hồi |
| Vi phạm tạm thời (Existence, Response) | **Liveness** | Nhắc nghĩa vụ (không chặn được) |
| Tổ hợp ràng buộc vi phạm vĩnh viễn | Xung đột | Báo đường cụt: "không làm được" |
| Điều kiện dữ liệu (MP-DECLARE) | Điều kiện kích hoạt | Không phán xét; bảo đảm kết quả kiểm tra hiện ra |

Vì mọi khái niệm định nghĩa trên LTLf, khung áp dụng được cho các Gate khác cùng họ (ContrAgent: LTLf→DFA; AgentLTL: FO-LTL).

### 5.3 Đóng góp
1. Cách sinh phản hồi từ cấu trúc ràng buộc (chẩn đoán / sửa / liên quan goal), không phụ thuộc ngôn ngữ luật.
2. Thực nghiệm có kiểm soát: loại thông tin nào giúp model 2–8B phục hồi; đối chứng `none`, `bare`, phát lại, ngân sách.
3. Chỉ ra **trần của việc chặn**: phần dư sau chặn là liveness và điều kiện dữ liệu; kiểm nhắc nghĩa vụ.

**Khẳng định an toàn:** *phản hồi sinh từ cấu trúc ràng buộc (gồm liên quan đến goal) được so có kiểm soát trên SOPBench với model 2–8B,
đo hoàn thành sau khi bị chặn.* Không viết "lần đầu dùng DECLARE", không viết "lần đầu so nội dung phản hồi".
Không khái niệm lý thuyết nào là mới; phần mới là dùng chúng làm nội dung phản hồi cho LLM agent bị chặn và đo.

### 5.4 Câu hỏi nghiên cứu
- **RQ1.** Loại thông tin nào (chẩn đoán / sửa / liên quan goal) giúp phục hồi? Tác dụng đổi theo năng lực model thế nào?
- **RQ2.** Liveness chiếm bao nhiêu phần dư sau chặn? Nhắc nghĩa vụ có xử lý được không?
- **RQ3.** Kết quả có giữ khi đổi domain, benchmark, họ model, và khi gắn vào Gate có sẵn?

### 5.5 Giả thuyết ghi trước
| | Dự đoán | Ngưỡng | Trạng thái |
|---|---|---|---|
| H1 | Chẩn đoán giảm lặp chặn | lặp chặn thấp hơn `next_action` | ✓ (E2b), không tăng pass |
| H2 | Thông tin sửa giúp task nên thành công; alignment > next_action chỉ khi chuỗi ≥2 bước | McNemar vs bare | ✓ phần đầu; phần sau chờ hotel |
| H3 | Liên quan goal sửa đường cụt; không tác dụng ở hotel/university | ≥5/8 đường cụt; ≥~4 task | ✓ cơ chế, chưa đủ ý nghĩa |
| H4 | Nhắc nghĩa vụ sửa lỗi Existence, không giảm từ chối đúng | +≥3 task, từ chối đúng giảm ≤2 | chờ E3 |
| H5 | `purpose_v2` không thua `next_action` | chênh ≥ −1 | chờ E3 |
| Xuyên domain | Tác dụng mỗi can thiệp tỷ lệ với tỷ lệ kiểu lỗi nó nhắm tới (bảng 4.9) | đúng thứ tự dự đoán | chờ mở rộng |

---

## 6. Bảng chuyển đổi khái niệm (cũ → mới)

| Cũ | Mới | Lý do |
|---|---|---|
| "Phản hồi theo DECLARE" là đóng góp | DECLARE/LTLf là cơ sở; đóng góp là khung phản hồi + đo | 4.5 |
| Thang bare → reason → next_action → template → alignment | 3 loại thông tin + nhắc nghĩa vụ | 4.6, 4.7 |
| "Hoàn thành" = pass mọi task | Chỉ số chính = pass trên task nên thành công; từ chối đúng là chỉ số chặn chiều xấu | 4.6 |
| Lỗi Existence = giới hạn, Gate không thấy | Lỗi liveness = trần của việc chặn, có can thiệp riêng (nhắc nghĩa vụ) | 4.8 |
| `goal` = cận trên | `goal` = Gate biết ý định (áp dụng khi hệ thống định tuyến ý định) | 4.8 |
| `purpose` = phiên bản công bằng | Kết quả âm; `purpose_v2` sửa lỗi; suy G từ cấu trúc không khả thi | 4.8 |
| "needed" = X có trong cây tiền điều kiện của G | needed_now / optional / not_needed theo alignment | 4.8, 5.2 |
| Đường cụt = lỗi model | Đường cụt = tổ hợp ràng buộc vi phạm vĩnh viễn + phản hồi đẩy sai hướng | 4.6, 5.2 |
| Điểm neo X3 (APM Manifesto) | Điểm neo framed autonomy + conformance checking/operational support; X3 chưa xác minh và ngược chiều (agent→người dùng) | phản biện |
| Mở rộng domain = thêm số liệu | Mở rộng domain = kiểm dự đoán (có đối chứng âm) | 4.9 |

## 7. Giữ / bỏ / hạ cấp

- **Giữ:** Gate tất định là middleware ở chỗ thực thi tool; luật = đúng SOP agent nhận được; Gate chỉ ép nhóm Precedence và không phán điều kiện dữ liệu;
  trạng thái chỉ cập nhật từ kết quả tool thật; so cặp McNemar + Holm trong cùng phiên bản code; ghi log mọi trajectory.
- **Thêm:** nhắc nghĩa vụ liveness (`goal_ex`); liên quan-theo-alignment; `purpose_v2`; đối chứng ngân sách; dự đoán xuyên domain.
- **Hạ cấp:** `template` vs `alignment` ở bank (không phân biệt được vì chuỗi 1 bước) → chuyển kiểm sang hotel.
- **Bỏ khỏi câu chuyện chính:** "lần đầu dùng DECLARE"; thang 7 mức như một danh sách; X3 làm điểm neo chính.

---

## 8. Trạng thái mã nguồn (chưa commit)

| File | Thay đổi |
|---|---|
| `frameguard/gate.py` | `set_tools` (tool thật của agent), bỏ đề xuất tool không có, thông điệp "impossible", `goal_info`, `required_by`, `_seen_values` chỉ từ lời gọi thành công |
| `frameguard/feedback.py` | Chế độ `goal`, `purpose`; thông điệp đường cụt; thông điệp tool không dùng được |
| `analysis/alignment.py` | Tham số `exclude`; `--no-db-dump` |
| `adapters/sopbench/runner.py` | Gọi `set_tools` với danh sách tool của harness |
| `analysis/pilot_report.py` | Chế độ mới, McNemar mới, bảng 4b |
| `analysis/check_constraints_orig.py` | Mới: so `constraints` với `constraints_original` |
| `scripts/make_kaggle_pilot.py`, `notebooks/kaggle_e2b_nothink.ipynb` | Preset E2b |
| `runs/e2b_nothink/` | Kết quả E2b (giải nén từ `frameguard_pilot_E2b.zip`) |
| `CLAUDE.md` | Cập nhật theo các mục trên |

**Đã cài cho E3 (chưa chạy GPU):** `goal_ex` (bọc `Swarm.get_chat_completion`, nhắc một lần khi G chưa gọi và chưa đường cụt);
`purpose_v2`; liên quan-theo-alignment (`needed`/`optional`/`not_needed`); `--max_turns` cho đối chứng ngân sách
(bare/next_action với max_actions 20, max_turns 40); báo cáo bảng 2b và 7; preset notebook `e3`
(`notebooks/kaggle_e3_nothink.ipynb`). Kiểm offline: phát lại 420 lượt không lỗi; lời nhắc đúng ý ở task 30/33/35/67/70;
`purpose_v2` không còn liệt kê tool không có.

## 9. Kế hoạch

1. **E3 (bank):** cài phần chưa cài ở mục 8; kiểm offline (`--fake_replay`; phát lại lịch sử E2b ở task 30, 33, 35, 67, 70;
   in tin nhắn `purpose_v2` ở 8 task thua; agent lý tưởng 99.9%, đã kiểm); chạy `next_action`, `goal`, `goal_ex`, `purpose_v2`
   (~2.5 giờ Kaggle).
2. **Kiểm xuyên domain:** online_market (dự đoán `goal` thắng) và hotel (dự đoán `goal` không thắng, `goal_ex` thắng, alignment > next_action);
   chạy cả `none` để đo lại hỗn hợp lỗi khi có Gate.
3. **Model thứ hai:** Gemma-4-E2B (dự đoán: thông tin sửa là chính, goal ít tác dụng).
4. **Benchmark thứ hai:** SOP-Bench hoặc τ² (Response/Absence thật; luật dạng văn bản; τ² có người dùng LLM).
5. **Nếu kịp:** gắn cách sinh phản hồi vào Gate có sẵn (ContrAgent).

## 10. Rủi ro và câu hỏi mở

- Headroom: thinking bật ở bank gần trần → đo domain khác trước khi khẳng định.
- Cỡ mẫu: chênh ~4 task / 33; cần thêm domain/model; decoding tham lam nên đo nhiễu bằng lần chạy lặp, cần phân tích power.
- Người dùng giả cố định; `max_actions` tính lời gọi bị chặn; `goal` cần biết ý định.
- Lỗi liveness ở bank chỉ 5 task → cần healthcare/hotel để đủ số liệu cho RQ2.
- Library (48 task lệch prompt/oracle), hotel (18 task không giải được).
- Nhắc nghĩa vụ có thể kéo model gọi G ở task nên từ chối → theo dõi từ chối đúng.
- Tài liệu liên quan ra hằng tháng; còn 3 bài chưa đọc ("From Constraint-Based Process Modeling to Framed Autonomy",
  "Constraints for Process Framing in AI-Augmented BPM", "Runtime Verification of LLM Agents Under Temporal Input/Output Logic");
  phụ lục AgentLTL chưa đọc hết.

## Phụ lục A. Trích dẫn lý thuyết cần kiểm trước khi viết bài

Nêu theo trí nhớ, cần xác minh năm/tên/nơi đăng:
- Pesic & van der Aalst (2006); Pesic, Schonenberg, van der Aalst (2007) — DECLARE.
- De Giacomo & Vardi (2013) — LTLf.
- Bauer, Leucker, Schallhart (2010) — ngữ nghĩa LTL cho runtime verification (RV-LTL).
- Maggi, Montali, Westergaard, van der Aalst (2011) — giám sát ràng buộc nghiệp vụ bằng LTL / automaton màu; phát hiện xung đột.
- de Leoni, Maggi, van der Aalst (2012) — alignment cho mô hình Declare.
- Burattin, Maggi, Sperduti (2016) — conformance cho MP-Declare.
- Maggi, Di Francescomarino, Dumas, Ghidini (2014) — predictive monitoring, goal là công thức LTL.
- van Zelst và cộng sự (2019) — online conformance, prefix alignment.
- Alpern & Schneider (1985) — safety/liveness.
- Di Ciccio & Montali (2022) — "Declarative Process Specifications" (đã có trong CLAUDE.md, điểm bắt đầu).
