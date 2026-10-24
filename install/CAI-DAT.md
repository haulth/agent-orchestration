# Cài đặt skill agent-orchestration (v2)

## Yêu cầu
- Python 3 (chỉ dùng thư viện chuẩn). Cần cho `agent_run.py`, `route.py`, `discover.py`.
- Các CLI bạn muốn dùng làm worker: `codex`, `agy`, `claude`. Không có cái nào thì `route.py` tự bỏ qua vendor đó.
  - `claude` đi kèm ứng dụng Claude desktop, có thể không nằm trong PATH; runner tự tìm ở `%APPDATA%\Claude\claude-code\<phiên bản>\claude.exe`.

## Cài
Windows (PowerShell), từ thư mục skill:
```powershell
.\install\install.ps1 -DryRun    # xem trước
.\install\install.ps1            # cài thật
```
macOS / Linux: `./install/install.sh [--dry-run]`.

Script sẽ:
1. sao lưu bản cũ (nếu có) vào `~/.agent-orchestration-backups/`;
2. chép skill (không kèm `install/`, `tests/`) vào:
   - `~/.claude/skills/agent-orchestration` (Claude Code),
   - `~/.agents/skills/agent-orchestration` (Codex, Windsurf/Devin),
   - `~/.gemini/config/skills/agent-orchestration` (agy);
3. tạo `~/.agent-orchestration/` (thư mục trạng thái dùng chung, vô hại nếu đã có);
4. cảnh báo nếu thiếu Python.

Sau đó **khởi động lại Claude Code, Codex và agy** để chúng nạp lại skill.

## Thư mục trạng thái `~/.agent-orchestration/`
| File | Nội dung |
|---|---|
| `ledger.jsonl` | mỗi lần chạy và mỗi phán quyết của manager (dữ liệu cho tự chủ theo thành tích) |
| `capabilities.json` / `capabilities.md` | ảnh chụp khả năng từng agent / bản đọc nhanh |
| `changes.md` | nhật ký thay đổi (chỉ thêm vào cuối) |
| `candidates.json` | model mới phát hiện, chưa được duyệt |
| `state.json` | lần kiểm tra nhanh gần nhất |

Đổi vị trí bằng biến môi trường `AO_HOME`.

## Cập nhật bảng model
1. Sửa `assets/models.json` (bậc `fast/standard/frontier/frontier_max` cho từng vendor, và bảng `tasks`).
2. Cập nhật bảng phản chiếu trong `references/gates-and-routing.md`.
3. Chạy lại `install.ps1` để đồng bộ sang 3 bản cài.

Model mới do `discover.py` phát hiện nằm ở `candidates.json`; chỉ đưa vào bước 1 sau khi bạn đồng ý hoặc sau một lần chạy thử có đo đạc.

## Kiểm tra nhanh sau khi cài
```powershell
python scripts\route.py --list-models
python scripts\route.py --task-type review --builder codex
python scripts\route.py --task-type design --manager agy --same-model
```
Các lệnh kiểm tra chạy hoàn toàn cục bộ, không tốn token.
