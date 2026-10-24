# agent-orchestration

Skill điều phối đa agent và sub-agent (`Claude Code`, `Codex CLI`, `Antigravity / agy`), tập trung vào chia việc chạy song song hiệu quả theo phần cứng máy, chọn model tự động, chống ảo giác và kết nối trực tiếp với các **skill chuyên sâu (`--skill`)**.

## Điểm cốt lõi
- **Tự động nhận diện model khả dụng (0 token):** Quét trực tiếp các model đang có trên máy (`route.py --list-models`) và chọn model phù hợp nhất theo độ khó tác vụ (hỗ trợ cả chế độ 1 agent `--single-host` hoặc cùng 1 model `--same-model`).
- **Ủy quyền chuyên môn cho các Skill chuyên sâu (`--skill`):** Không ôm đồm quy trình đặc thù ngành; tự động dò tìm các skill chuyên sâu đã cài trên máy (`route.py --list-skills` / `--need <keyword>`) và gắn trực tiếp vào sub-agent qua `--skill <name>`.
- **Điều phối song song theo phần cứng thực tế (`batch` & native sub-agents):** Tự động đo **CPU cores, RAM trống, dung lượng ổ cứng và GPU VRAM** (`probe_hardware()`) để giới hạn số luồng song song an toàn (`recommended_wip`), kết hợp ngữ cảnh sạch (`Zero-Prior Brief`), bảng đen dùng chung (`--context-file`) và khóa vùng ghi tách biệt (`--may-write` / `--worktree`).
- **Luật bằng chứng (`No Proof = No Claim`):** Mọi kết luận và phản biện (`assumptions_challenged`) bắt buộc kèm dẫn chứng kiểm chứng được (`file:line`, `command -> output`, `DOI/arXiv/PMID/URL`).

## Lệnh sử dụng nhanh

```bash
# 1. Xem model khả dụng, skill chuyên sâu trên máy và gợi ý định tuyến (0 token)
python <skill>/scripts/route.py --list-models
python <skill>/scripts/route.py --list-skills
python <skill>/scripts/route.py --task-type research --need arxiv --manager agy --same-model
python <skill>/scripts/route.py --task-type review --builder codex

# 2. Chạy worker đơn lẻ (kèm skill chuyên sâu và file ngữ cảnh) hoặc chạy song song theo batch
python <skill>/scripts/agent_run.py run --agent agy --brief brief.md --mode read \
       --skill literature-search-arxiv --context-file .orch/spec.md
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
