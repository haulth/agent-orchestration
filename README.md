# agent-orchestration

Skill điều phối đa agent và sub-agent (`Claude Code`, `Codex CLI`, `Antigravity / agy`), giúp chia việc phân tích, phản biện và viết code phát triển hệ thống với chi phí token thấp, chống ảo giác và không bị thiên kiến ngữ cảnh.

## Điểm cốt lõi
- **Tự động nhận diện model mới nhất (0 token):** Quét trực tiếp model khả dụng trên máy (`route.py --list-models`) và chọn model phù hợp nhất theo độ khó tác vụ.
- **3 chế độ giao việc (`tight` / `guided` / `exploratory`):** Việc nhỏ giao gọn 4 dòng; việc chuẩn có lăng kính vai trò & tiêu chí nghiệm thu; việc khó/mở cho phép tự do lần theo dấu vết và phản biện giả định sai (`assumptions_challenged`).
- **Luật bằng chứng (`No Proof = No Claim`):** Mọi kết luận và phản biện bắt buộc kèm dẫn chứng kiểm chứng được (`file:line`, `command -> output`, số liệu đo đạc).
- **Hội đồng chuyên gia đa góc nhìn (`council` — hỗ trợ cả 1 agent / cùng 1 model):** Tách các sub-agent với ngữ cảnh sạch (`Zero-Prior Brief` — không mớm trước giả thuyết) dưới các góc nhìn đối kháng (`Architect`, `Red-Team Falsifier`, `Simplicity Minimalist`, `Runtime Engineer`).
- **Đội ngũ viết code phát triển hệ thống (`dev`):** Khóa hợp đồng giao diện chung (`interface-contract.md`), chia các `Builder` viết code song song/tuần tự trên các phạm vi `--may-write` tách biệt (hoặc nhánh `--worktree`), kèm `Test Builder` độc lập và `Reviewer`.

## Lệnh sử dụng nhanh

```bash
# 1. Xem danh sách model khả dụng thực tế và gợi ý định tuyến (0 token)
python <skill>/scripts/route.py --list-models
python <skill>/scripts/route.py --task-type review --builder codex
python <skill>/scripts/route.py --task-type system-dev --manager agy --same-model

# 2. Phân tích & phản biện đa góc nhìn (chạy được cả trên cùng 1 model)
python <skill>/scripts/agent_run.py council --brief brief.md --agent agy --task-type design [--execute]

# 3. Giao việc viết code phát triển hệ thống đa module (Builders + Tester + Reviewer)
python <skill>/scripts/agent_run.py dev --brief spec.md --module core:src/core/ --module api:src/api/ \
       --test-scope tests/ --agent codex [--worktree] [--execute]

# 4. Chạy 1 worker đơn lẻ (codex | claude | agy) & chấm kết quả
python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --mode read --context-file .orch/spec.md
python <skill>/scripts/agent_run.py verdict <run-dir> accept
```

## Cài đặt
```powershell
.\install\install.ps1   # Windows (đồng bộ vào ~/.claude, ~/.agents, ~/.gemini/config)
```
```bash
./install/install.sh    # macOS / Linux
```
