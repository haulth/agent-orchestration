# agent-orchestration

Skill điều phối đa agent và sub-agent (`Claude Code`, `Codex CLI`, `Antigravity / agy`), giúp chia nhỏ tác vụ chạy song song với chi phí token thấp, chống ảo giác và loại bỏ thiên kiến ngữ cảnh.

## Điểm cốt lõi
- **Tự động nhận diện model mới nhất (0 token):** Quét trực tiếp model khả dụng trên máy (`route.py --list-models`) và chọn model phù hợp nhất theo độ khó tác vụ.
- **3 chế độ giao việc (`tight` / `guided` / `exploratory`):** Việc nhỏ giao gọn 4 dòng; việc chuẩn có lăng kính vai trò & tiêu chí nghiệm thu; việc mở cho phép tự do lần theo dấu vết và phản biện giả định sai (`assumptions_challenged`).
- **Luật bằng chứng (`No Proof = No Claim`):** Mọi kết luận và phản biện bắt buộc kèm dẫn chứng kiểm chứng được (`file:line`, `command -> output`, số liệu đo đạc).
- **Phân việc độc lập chạy song song (`parallel` / `batch` — dùng được cả trên 1 agent hoặc cùng 1 model):** Không phân biệt là nghiên cứu, phản biện hay viết code phát triển hệ thống — mọi bài toán lớn đều tách thành các sub-agent chạy **song song** với ngữ cảnh sạch (`Zero-Prior Brief` — không mớm trước giả thuyết), dùng chung tài liệu ngữ cảnh (`--context-file`), và phân vùng `--may-write` tách biệt (hoặc `--worktree`) khi có ghi file.

## Lệnh sử dụng nhanh

```bash
# 1. Xem danh sách model khả dụng thực tế và gợi ý định tuyến (0 token)
python <skill>/scripts/route.py --list-models
python <skill>/scripts/route.py --task-type review --builder codex
python <skill>/scripts/route.py --task-type implement --manager agy --same-model

# 2. Phân việc chạy song song (tự động chia góc nhìn độc lập hoặc chia vùng --may-write chạy song song)
python <skill>/scripts/agent_run.py parallel --brief brief.md --agent agy --task-type design [--execute]
python <skill>/scripts/agent_run.py parallel --brief spec.md --task-type implement \
       --scope core:src/core/ --scope api:src/api/ --agent codex [--worktree] [--execute]

# 3. Chạy 1 worker đơn lẻ hoặc 1 batch tùy chỉnh & chấm kết quả
python <skill>/scripts/agent_run.py run --agent codex --brief brief.md --mode read --context-file .orch/spec.md
python <skill>/scripts/agent_run.py batch plan.json
python <skill>/scripts/agent_run.py verdict <run-dir> accept
```

## Cài đặt
```powershell
.\install\install.ps1   # Windows (đồng bộ vào ~/.claude, ~/.agents, ~/.gemini/config)
```
```bash
./install/install.sh    # macOS / Linux
```
