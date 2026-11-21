# demo-studio 0.4: bản gọn

Plugin này là **cấu hình một đội agent**, không phải một sản phẩm phần mềm. Mỗi agent được chỉ định việc, công cụ và cách làm, cộng thêm vài script chạy sẵn. Thay thế `docs/redesign/demo-studio-redesign.md`; bản đó giữ lại làm tham khảo nghiên cứu.

## Nguyên tắc
- Agent quyết định. Script làm phần cơ khí, có timeout, in JSON, exit code rõ ràng.
- Không pixel gate, không oracle, không hook, không adapter riêng cho từng nền tảng.
- **Mặc định dùng dữ liệu `seeded`**: tài khoản demo hoặc dữ liệu mẫu. `real` chỉ bật khi user chọn ở G1.
- Privacy gồm 2 lớp:
  1. **CSS mask lúc quay (web):** che các selector nhạy cảm.
  2. **OCR verify cuối** trên mọi bản xuất. Phát hiện lộ dữ liệu thì không giao video.
- Desktop/mobile: quay bằng công cụ của nền tảng (`platform-automation`), dữ liệu seeded, cuối cùng vẫn chạy OCR verify.

## 6 agent
| Agent | Việc | Gộp từ |
|---|---|---|
| `demo-director` | Hiểu yêu cầu, hỏi user ở 3 gate, giao việc, giữ `STATE.md`, chạy `setup_tools.py` | director, toolsmith |
| `story` | brief, `demo.yaml`, storyboard, narration (kể cả bản dịch) | strategist, storyboarder, scriptwriter, localizer |
| `app-scout` | Khám phá app, selector, danh sách `sensitive`, chuẩn bị dữ liệu seeded | app-scout |
| `scene-automator` | Viết scene script, quay bằng `capture.py` | scene-automator, capture-operator |
| `editor` | TTS (`vo.py`), `edit.json` (cắt ghép, thời gian, phụ đề, hiệu ứng nhẹ), `render.py` | voice, sync, motion, captions, mix, render, packager |
| `demo-qa` | Chạy `verify.py`, xem video, viết `qa.md` PASS/FAIL, chỉ ra agent phải sửa | demo-qa, privacy-blurrer |

## 5 script (`scripts/`)
| Script | Lệnh |
|---|---|
| `setup_tools.py` | Có sẵn: kiểm tra và cài công cụ theo feature (hỏi user trước) |
| `vo.py` | Có sẵn: TTS theo scene, đo thời lượng |
| `capture.py` | `capture.py --scenes scenes.web.py --scene sNN --url U --out media/ [--mask-selector S ...] [--viewport WxH] [--timeout S]` → `media/sNN.raw.webm`. Playwright Python, chèn CSS mask (`color: transparent; background: #222`, cả `input` value) qua `add_init_script` cho các selector trong `demo.yaml privacy.mask`. Không đo pixel. |
| `render.py` | `render.py --slug S [--aspect 16x9,9x16,1x1]` đọc `edit.json` → `media/final-<aspect>.mp4` + `final.vtt`: cắt ghép, ghép VO, loudnorm 2-pass, phụ đề, một lần chạy ffmpeg cho mỗi aspect |
| `verify.py` | `verify.py --slug S` cho mọi `final-*.mp4`: lấy mẫu frame trong **một lần decode**, OCR một lần, tìm `privacy.patterns` + `seed_values` (bản real) + mẫu email/key mặc định. Kèm đo loudness và thời lượng. Có budget thời gian ép bằng code. Exit 0 pass, 11 lộ, 3 chưa đủ mẫu hoặc hết giờ. |

Mọi lệnh ffmpeg/OCR dùng một helper chung `_run()` (trong `scripts/common.py`): có timeout, `-nostdin`, kill cả process group. Đây là thứ sửa lỗi "treo" gốc.

## Trạng thái của một project (`.demo/<slug>/`)
`STATE.md`, `demo.yaml`, `brief.md`, `storyboard.md`, `narration.md`, `app-map.md`, `scenes.<platform>.*`, `edit.json`, `media/`, `qa.md`. **Bỏ `project.json`**; project cũ chạy lại từ storyboard.

## Luồng
G1 (brief + `demo.yaml`, chọn `seeded`/`real`) → app-scout → story (storyboard + narration) → **G2** → editor (voice) → scene-automator (quay) → editor (edit + render) → demo-qa (verify + xem) → **G3** → giao video.

## Lệnh (5)
`new`, `run` (mọi yêu cầu khác, rỗng thì tiếp tục từ chỗ dừng), `fix`, `review`, `tools`.

## Bỏ
`blur.py`, `checks.py`, `project.py`, `config.py` (validate gộp vào `common.py`), `run_bounded.py`, `web_adapter.py`, `privacy_mask.js`, `privacy_oracle.js`, `demo.py`, adapter Electron/Android, `hooks/`, 12 agent, 6 command, `templates/project.json`.
