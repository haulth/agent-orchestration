# agent-orchestration (v3: Điều Phối Thích Ứng & Trí Tuệ Tập Thể)

Skill giúp một model đóng vai **nhà điều phối (manager)**, tổ chức nhiều subagent và nhiều họ model phối hợp như một đội ngũ R&D tinh nhuệ: **vừa giữ kỷ luật chi phí token và an toàn phạm vi, vừa giải phóng tối đa trí thông minh, quyền phản biện và khả năng trao đổi trực tiếp giữa các AI.**

Nội dung skill (`SKILL.md`, `references/`, `scripts/`) được viết bằng tiếng Anh để các model đọc chính xác. File này là hướng dẫn tiếng Việt cho bạn.

## Những nâng cấp đột phá ở bản v3

1. **Ba Chế độ Giao việc (`tight` / `guided` / `exploratory`) — Không để thủ tục bóp nghẹt trí thông minh:**
   - **`tight` (Gọn nhẹ, 4 dòng):** Dùng cho tra cứu nhanh, sửa code cơ học, viết unit test nhỏ. Không bắt viết tiểu luận về Role.
   - **`guided` (Chuẩn mực):** Dùng cho xây dựng tính năng, review, tài liệu. Có lăng kính vai trò (`Role`), `Intent`, `Definition of Done`, `Finish line`.
   - **`exploratory` (Thám hiểm mở):** Dùng cho debug lỗi khó, nghiên cứu khoa học, thiết kế kiến trúc. **Không đóng khung bước làm hay giới hạn tầm nhìn**: cho phép agent tự do lần theo dấu vết bằng chứng trên toàn repo và chủ động tìm ra những điều Manager chưa biết để hỏi (*unknown unknowns*).
2. **Quyền Phản biện Giả định (`Premise Challenge Right`) & Vai trò là Lăng kính (Lenses, Not Blinders):**
   - Trong [`roles.md`](references/roles.md), các góc soi là **mức sàn, không phải rào chắn**. Thay thế khái niệm cứng nhắc "Not your job" bằng **"Adjacent owners (phát hiện và báo cáo, không làm trùng)"**.
   - Nếu Worker phát hiện giả định trong đề bài của Manager bị sai (ví dụ: lỗi thực sự nằm ở rò rỉ hạt giống RNG chứ không phải lịch learning rate), Worker ghi thẳng vào trường `assumptions_challenged` trong kết quả và được ghi nhận là một phát hiện thành công.
3. **Bảng Đen Chung (`Shared Blackboard` qua `--context-file`) & Giao tiếp Trực tiếp:**
   - Xóa bỏ nút cổ chai "tam sao thất bản" (Manager tự tóm tắt lại kết quả của Agent A rồi mới đưa cho Agent B). Giờ đây bạn hoặc Manager truyền thẳng `--context-file <đường_dẫn_artifact>` để Agent B đọc trực tiếp phân tích/diff nguyên bản của Agent A.
   - Tận dụng triệt để công cụ gốc của từng nền tảng: `invoke_subagent` với `Workspace: "branch" | "share"` (cô lập nhánh/worktree cho nhiều agent cùng ghi song song) và `send_message` (nhắn tin trực tiếp giữa các agent) trên Antigravity; `isolation: "worktree"` và `SendMessage` trên Claude Code.
4. **Hội ý Kiến tạo & Thực nghiệm (`Constructive & Empirical Huddle`):**
   - Bổ sung **Cổng Thực nghiệm 2 phút (`Empirical Spike Gate`):** Nếu các chuyên gia bất đồng về một sự thật có thể kiểm chứng bằng code/số liệu, cấm cãi nhau bằng chữ — chạy ngay một micro-spike để lấy số liệu thật phân xử.
   - Bổ sung **Hợp đề (`Dialectical Synthesis — Option C`):** Thay vì chỉ "phản bác hoặc đầu hàng" giữa phương án A và B, vòng 2 khuyến khích các chuyên gia tổng hợp ưu điểm để tạo ra Phương án C vượt trội.
5. **Định tuyến theo Họ Model & Điểm mạnh Nhận thức (`Model-Family Routing`):**
   - Phân biệt rõ **công cụ gọi (`codex`, `agy`, `claude`)** và **họ model (`openai`, `google`, `anthropic`)** (vì `agy 1.4.4` chạy được cả `gemini-4-argon-*` lẫn `claude-opus-5-5-*`). Khi cần review độc lập, `route.py` chọn model khác **họ tư duy** với model đã viết code.
6. **Khắc phục triệt để các lỗi kỹ thuật từ nhật ký thực tế (`ledger.jsonl`):**
   - **Chống nổ triệu `violations` trên repo AI/ML:** `agent_run.py` dùng `git status -unormal` kết hợp giới hạn mở rộng thư mục untracked (`MAX_UNTRACKED_EXPAND = 2000`) và chữ ký `stat` siêu nhanh cho file >4MB. Không còn cảnh tiến trình nền sinh dữ liệu làm treo máy hay báo 1,65 triệu file vi phạm.
   - **Tách `--name` và tự động chuẩn hóa `--task-type` + `--tier`:** Đặt tên thư mục chạy thoải mái bằng `--name review-p1-model` (hoặc kể cả truyền vào `--task-type`), hệ thống tự động quy về loại chuẩn (`review`, `implement`, `explore`, `docs`...) và tự suy luận `tier` từ tên model để sổ cái `ledger.jsonl` luôn học chính xác.
   - **Cập nhật đường dẫn `Claude Code 2.1.308` & `agy 1.4.4`:** Tự động tìm `claude.exe` trong `%LOCALAPPDATA%\Claude-Data\...` và cập nhật bảng model `gemini-4-argon-{low,medium,high}`, `claude-opus-5-5-high`.

## Dùng các script

```bash
# 0) Xem toàn bộ model thực tế đang khả dụng trên máy (0 token, không bao giờ lỗi thời)
python <skill>/scripts/route.py --list-models

# 1) Hỏi nên dùng model nào và chế độ brief nào (0 token)
python <skill>/scripts/route.py --task-type review --risk med --builder codex
python <skill>/scripts/route.py --task-type explore --ambiguity high      # gợi ý brief_mode: exploratory
python <skill>/scripts/route.py --task-type design --manager agy --same-model  # chế độ 1 agent / cùng 1 model

# 2) Sinh Hội đồng Chuyên gia Đa Góc nhìn trên CÙNG 1 Model (Zero-Prior Briefs + Orthogonal Lenses)
python <skill>/scripts/agent_run.py council --brief brief.md --agent agy --model gemini-4-argon-high --task-type design

# 3) Chạy worker (codex | agy | claude), kèm tên gợi nhớ (--name) và Bảng đen chung (--context-file)
python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --name review-p1-core \
       --task-type review --mode read --context-file .orch/design-spec.md

#    Chạy worker có ghi file, kèm phạm vi được ghi
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode write --may-write src/foo/

# 4) Chấm kết quả và xem thống kê (tự động chuẩn hóa cả lịch sử cũ trong ledger.jsonl)
python <skill>/scripts/agent_run.py verdict <run-dir> accept --note "Phát hiện đúng lỗi rò rỉ RNG"
python <skill>/scripts/agent_run.py stats

# 5) Cập nhật hiểu biết về agent (0 token)
python <skill>/scripts/discover.py --quick
python <skill>/scripts/discover.py
```

## Cài đặt
```powershell
.\install\install.ps1            # Windows: đồng bộ vào ~/.claude, ~/.agents, ~/.gemini/config
```
```bash
./install/install.sh             # macOS / Linux
```
