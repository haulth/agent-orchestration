# agent-orchestration

Skill điều phối đa agent và sub-agent (`Claude Code`, `Codex CLI`, `Antigravity / agy`), tập trung vào chia việc chạy song song hiệu quả theo phần cứng máy, chọn model tự động, chia sẻ trực tiếp skill từ agent mẹ sang agent con, và quản lý **Skill Sandbox tạm thời** an toàn.

## Điểm cốt lõi
- **Tự động nhận diện model khả dụng (0 token):** Quét trực tiếp các model đang có trên máy (`route.py --list-models`) và chọn model phù hợp nhất theo độ khó tác vụ (hỗ trợ cả chế độ 1 agent `--single-host` hoặc cùng 1 model `--same-model`).
- **Chia sẻ trực tiếp Skill từ Agent mẹ sang Agent con (`--skill` — có sẵn là dùng ngay, không cài thêm):** Tự động dò các skill chuyên sâu mà Agent mẹ đang có (`route.py --list-skills`) và truyền thẳng đường dẫn `SKILL.md` + quyền đọc thư mục (`--add-dir`) cho Agent con.
- **Ephemeral Skill Sandbox (`skill_sandbox.py`):** Khi thiếu skill chuyên sâu chưa có trên máy, chỉ tìm từ các kho chính hãng/uy tín cao (`anthropics/skills`, `openai/skills`, `vercel-labs/agent-skills`, `huggingface/skills`, hoặc repo đạt chuẩn uy tín), **bắt buộc hỏi ý kiến người dùng trước khi cài (`--approved-by-user`)**, quét bảo mật tĩnh và lưu tạm vào bộ nhớ riêng (`~/.agent-orchestration/sandbox-skills/`) — xóa sạch bất cứ lúc nào (`remove` / `purge`) mà không ảnh hưởng hệ thống.
- **Giải phẫu công việc & Chốt chặn Khóa liên động (`Orchestration Anatomy & Keyhole Interlock` — `anatomy.py` & `batch --audit`):**
  - **Size Gate (`Micro` <=1 | `Figure` 2–4 | `Hero` 5–8 | `Epic` >8):** Định cỡ quy mô ngay từ đầu; nếu vượt quá 8 gói việc (`Epic`), tự động dừng để đề xuất lát cắt `Hero` trước.
  - **Truth Lock & Keyhole Invariants (`truth_contract` + `--invariant` + `truth_hash`):** Khóa chặt các quy chuẩn tiên quyết và thông số ngưỡng của người dùng (`--invariant "PORT=8080" --invariant "MAX_LATENCY_MS<=200" --invariant "must:..." --invariant "forbid:..."`) kèm mã băm `truth_hash` (SHA-256) và khóa quyền ghi `truth-contract.md`.
  - **Chống tự ý đổi ngầm & Lan truyền thay đổi (`check_invariant_drift`, `detect_cross_package_conflicts`, `anatomy.py amend`):** Chặn triệt để tình trạng *"1 ông tự ý đổi thông số, mấy ông khác nín thin dẫn đến xung đột"*. Tự động quét code/output sau mỗi đợt sóng để bắt lỗi lệch ngưỡng (`INVARIANT_DRIFT`, `THRESHOLD_VIOLATION`) hoặc lệch hằng số giữa các gói (`CROSS_PACKAGE_CONFLICT`). Khi cần đổi thông số có bằng chứng (`truth_amendments`), lệnh `anatomy.py amend` (hoặc `batch --auto-amend`) tự động nâng `truth_version`, gắn thông báo `.orch/truth-amendment-vN.md` vào mọi gói việc và đánh dấu các gói đã chạy bằng thông số cũ là `stale_packages` để buộc đồng bộ lại.
  - **Audit to Zero (`anatomy.py audit` / `batch --audit`) & 4x Junction Check (`anatomy.py inspect`):** Kiểm toán tự động **0 lỗi ở 8 hạng mục** trước khi chạy và soi cận cảnh **4x tại các khớp nối** sau khi chạy.
- **Điều phối song song theo phần cứng thực tế (`batch` & native sub-agents):** Tự động đo **CPU cores, RAM trống, dung lượng ổ cứng và GPU VRAM** (`probe_hardware()`) để giới hạn số luồng song song an toàn (`recommended_wip`), kết hợp ngữ cảnh sạch (`Zero-Prior Brief`), bảng đen dùng chung (`--context-file`) và khóa vùng ghi tách biệt (`--may-write` / `--worktree`).
- **Luật bằng chứng (`No Proof = No Claim`):** Mọi kết luận và phản biện (`assumptions_challenged`) bắt buộc kèm dẫn chứng kiểm chứng được (`file:line`, `command -> output`, `DOI/arXiv/PMID/URL`).

## Lệnh sử dụng nhanh

```bash
# 1. Xem model khả dụng, skill có sẵn trên Agent mẹ và gợi ý định tuyến (0 token)
python <skill>/scripts/route.py --list-models
python <skill>/scripts/route.py --list-skills
python <skill>/scripts/route.py --task-type research --need arxiv --manager agy --same-model

# 2. Giải phẫu công việc + Khóa ngưỡng tiên quyết (--invariant) + Audit to Zero + Amend lan truyền & Soi khớp nối 4x
python <skill>/scripts/anatomy.py init --goal "Triển khai & kiểm chứng module X" \
       --invariant "PORT=8080" --invariant "MAX_LATENCY_MS<=200" \
       --pkg "contract:guided::src/types.py::.orch/contract-out.md" \
       --pkg "impl:guided:contract:src/core/::src/core/engine.py" \
       --pkg "verify:exploratory:impl" --out .orch/plan.json
python <skill>/scripts/anatomy.py audit .orch/plan.json
python <skill>/scripts/agent_run.py batch .orch/plan.json [--audit] [--auto-amend]
python <skill>/scripts/anatomy.py amend .orch/plan.json --set "MAX_LATENCY_MS<=250" \
       --reason "Đo thực nghiệm p99" --evidence "bench.py:42 -> 235ms"
python <skill>/scripts/anatomy.py inspect .orch/plan.json

# 3. Chạy worker đơn lẻ (chia sẻ thẳng path skill của Agent mẹ qua --skill)
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode read \
       --skill literature-search-arxiv --context-file .orch/spec.md

# 4. Skill Sandbox tạm thời (chỉ dùng khi máy chưa có skill; BẮT BUỘC hỏi người dùng trước khi cài)
python <skill>/scripts/skill_sandbox.py check <keyword>
python <skill>/scripts/skill_sandbox.py search <query> --min-stars 50
python <skill>/scripts/skill_sandbox.py install <owner/repo> --subpath <path> --approved-by-user
python <skill>/scripts/skill_sandbox.py list
python <skill>/scripts/skill_sandbox.py remove <name>
python <skill>/scripts/skill_sandbox.py purge [--expired]
```

## Cài đặt
```powershell
.\install\install.ps1   # Windows (đồng bộ vào ~/.claude, ~/.agents, ~/.gemini/config)
```
```bash
./install/install.sh    # macOS / Linux
```
