# demo-studio v0.3: thiết kế lại và kế hoạch migrate

> Người viết: lead architect, chủ quản plugin `demo-studio`. Tài liệu tổng hợp từ 6 báo cáo chuyên gia độc lập (`capture-redaction`, `media-perf`, `agent-architecture`, `reliability-qa`, `end-user-product`, `contrarian`) và đã qua một vòng red-team (xem Phụ lục A). Mỗi báo cáo có thí nghiệm riêng trong `scratchpad/exp/<id>/`.
>
> Quy ước trích dẫn:
> - `[id/Rx]` là khuyến nghị của một chuyên gia.
> - `[exp: …]` là thí nghiệm chạy cục bộ trong container 4 vCPU. Máy dùng chung nên số tuyệt đối có nhiễu, còn tỉ lệ thì ổn định.
> - `path:line` là vị trí trong repo.
> - **(suy luận)** đánh dấu nhận định chưa được đo trực tiếp. **(chưa test)** đánh dấu cơ chế đề xuất chưa có thí nghiệm.
> - **web-snippet** là nguồn chỉ đọc được qua đoạn trích kết quả tìm kiếm, vì host bị chặn trong session.
> - `[RT-n]` trỏ tới issue red-team số n trong Phụ lục A.

---

## 1. Tóm tắt quyết định

1. **Che dữ liệu nhạy cảm ngay lúc quay là mặc định cho web.** Script `scripts/privacy_mask.js` được inject qua `context.addInitScript`. Nó **không sửa DOM của app** [RT-2]. Cơ chế:
   - text node: CSS Custom Highlight API (`::highlight(ds-mask)`) trên các `Range` khớp selector hoặc regex; dự phòng bằng overlay div định vị theo `Range.getClientRects()` trong một shadow root cấp cao nhất;
   - `<input>`/`<textarea>`: `-webkit-text-fill-color:transparent` cho phần tử khớp selector, và listener `input` áp regex lên `.value` [RT-1];
   - thuộc tính hiển thị (placeholder, title, aria-label dùng cho tooltip), SVG `<text>` (`fill`), `::selection`, autofill: có rule riêng (xem §6.2).
   - Khi đó blur hậu kỳ chỉ còn là đường ngoại lệ.
   - Bằng chứng: mask có mặt ở 230/230 frame, toast chèn muộn được che 211/211 frame, không lệch vị trí, overhead thời gian quay ≈ 0 [exp: capture-redaction E1] [exp: contrarian rec3.js: 0/149 frame lộ]. Các thí nghiệm này **chỉ phủ text node tĩnh và một toast**; input, SVG, tooltip và cơ chế Highlight/overlay là **(chưa test)** và phải có test Tier 1 ở P0 trước khi bật mặc định.
   - `recordVideo` của Playwright không có option mask; `mask` chỉ có ở `screenshot` (https://raw.githubusercontent.com/microsoft/playwright/main/docs/src/api/params.md; `playwright-core/types/types.d.ts:11549`).
2. **Mặc định dùng mask đục (opaque), không dùng blur. Bỏ "switch to pixelate".**
   - OCR không đọc được ở CSS blur r=2 với chữ 22px, nhưng mắt người vẫn đọc được 14px r2–3 và 22px r2–4 [exp: capture-redaction E3].
   - Blur r=2 làm lộ email trong 5 frame [exp: E2].
   - Văn bản bị pixelate có thể khôi phục (Unredacter, web-snippet).
   - Nếu buộc phải dùng blur cho mục ít nhạy cảm: r ≥ 0.35 × font-size.
   - Thay `skills/media-specs/SKILL.md:76`.
3. **Viết `scripts/blur.py` deterministic (`plan|graph|preview|verify`). Agent không được tự viết code OpenCV/OCR nữa** [media-perf/MP-1] [contrarian/A2].
   - Hiện `scripts/` chỉ có `config.py`, `project.py`, `setup_tools.py`, `vo.py`. Agent `privacy-blurrer` (haiku) đang tự ứng biến code ở mỗi lần chạy (`agents/privacy-blurrer.md:14-23`).
4. **Mọi subprocess nặng chạy qua một runner có giới hạn: `scripts/run_bounded.py`.** Runner có wall clock, stall watchdog dựa trên **giao thức heartbeat** (ffmpeg: `-progress pipe:1`; worker khác: một dòng JSON progress) [RT-14], kill cả process group (TERM → poll group → KILL), và luôn thêm `-nostdin` cho ffmpeg.
   - `subprocess.run(timeout=)` và `timeout -k` đều để lại ffmpeg mồ côi (ppid 1) [exp: reliability-qa E1/E2].
   - Thiếu `-nostdin` trong vòng lặp shell làm mất 47/108 frame [exp: reliability-qa E3] [exp: agent-architecture: 62/108].
   - Repo có 0/29 snippet ffmpeg dùng `-nostdin`.
5. **Chỉ verify một lần, trên mọi bản render được giao, bằng `blur.py verify`** [RT-5]. Mỗi output giải mã tuần tự một lần, gộp nhiều ROI vào một montage cho mỗi lần gọi OCR, đặt `Det.limit_type=max`, bắt buộc có positive control. Với `real-redacted` và non-web, thêm một pass OCR regex full-frame thưa (stride thô) có budget, để bắt PII không có marker.
   - Một lần decode nhanh hơn 6.8–10 lần so với chạy một `ffmpeg -ss` cho mỗi sample [exp: contrarian, agent-architecture, reliability-qa E4, media-perf a].
   - Với `limit_type=max`, ROI 700x120 giảm từ 3334 ms xuống 316 ms [exp: media-perf b3].
   - Xoá các pass OCR trùng ở `privacy-blurrer.md:20`, `render-engineer.md:24` và `demo-qa`.
6. **Vùng chuyển động lấy vị trí chính xác theo từng frame, không nội suy keyframe qua chỗ nhảy.** Thứ tự ưu tiên: mask lúc quay > bbox DOM log theo frame > re-detect > CSRT (có re-detect, fail-closed).
   - Nội suy (lerp) 2 s lộ email và số thẻ ở 3/41 sample; vị trí chính xác theo frame lộ 0/41 [exp: media-perf c].
   - Đây là nguyên nhân của QA M-1.
7. **Gộp các vùng tĩnh lặp lại thành một vùng cho mỗi clip, khi lập plan mới** (không gộp lúc migrate dữ liệu cũ, xem §8) [RT-10]. b1–b10 có bbox giống hệt `[968,3,284,58]` (`example/.demo/ai-video-trends-v2/project.json#blur`). Đặt `enable=` lên cả filter blur, không chỉ lên overlay: 17 vùng giảm từ 13.4 s xuống 7.6 s [exp: media-perf b1].
8. **Chỉ một script được quyết định pass/fail: `scripts/checks.py`.** Ownership được ép **trong `project.py`**, không chỉ ở hook: `project.py set checks` bị từ chối trừ khi được gọi từ code path của `checks.py` [RT-11].
   - Trong example, loudness lệch 0.7 LU so với ngưỡng 0.5 nhưng vẫn được ghi pass. Blur có 3/17 vùng không kiểm tra được mà vẫn pass (`project.json#checks.results`) [reliability-qa/RQ-4].
   - Positive control fail thì kết quả là `INCONCLUSIVE`, không phải pass.
9. **Thêm chính sách dữ liệu `privacy.data_mode`: `seeded` / `real-redacted` / `real-visible`.**
   - Agent vẫn **không bao giờ** bịa hay thay dữ liệu.
   - `seeded` **chỉ** hợp lệ khi có câu trả lời của user được ghi lại ở G1. Không bao giờ auto-approve. Bằng chứng do `app-map` trích chỉ được dùng để điền sẵn câu hỏi G1. Không có câu trả lời, hoặc đang ở auto mode, thì ép `real-redacted` [RT-4].
   - Example dùng dữ liệu hư cấu ("All data is fictional", `app-map.md:6`) nhưng vẫn tốn 17 vùng blur và 108 sample OCR [capture-redaction/CR-6] [contrarian/C2].
10. **Giảm roster từ 18 xuống director + 6 agent phán đoán. Phần cơ khí chuyển thành script, `demo.py` là state machine.** Làm theo kiểu strangler, ở P2. Mọi `commands/*.md` được map sang stage của `demo.py` trước khi xoá agent nào [RT-9].
    - Anthropic khuyên "simplest solution possible" (https://www.anthropic.com/engineering/building-effective-agents).
    - Multi-agent tốn khoảng 15x token (https://www.anthropic.com/engineering/multi-agent-research-system).
    - Example có 52 lần ghi state có version trong một lần chạy [agent-architecture/A1,A2] [contrarian/A1].
11. **Ép rule bằng hook và bằng code, không bằng văn xuôi.** Thêm `hooks/hooks.json` với SubagentStop (kiểm DoD) và PreToolUse. Hook **chỉ tác động lên agent của demo-studio** (lọc theo `agent_type`), các agent khác exit 0 [RT-11]. Đặt `maxTurns` cho mọi agent (https://code.claude.com/docs/en/hooks, https://code.claude.com/docs/en/sub-agents) [agent-architecture/A5] [reliability-qa/RQ-7].
12. **Gate cho người dùng: G1 tối đa 2 vòng AskUserQuestion; G2 có video nháp xem được.** Phần encode của một nháp 15 s mất khoảng 20 s [exp: end-user-product], nhưng thời gian G1 → nháp còn gồm thời gian agent viết scene, **chưa đo** [RT-7]. Trong example, vấn đề "quá nhanh" và "bỏ sót nội dung" chỉ lộ ra sau khi render đầy đủ (`example/.demo/STATE.md`) [end-user-product/EU-1,EU-2].
13. **Dữ liệu nhạy cảm không được rò qua artefact phụ** [RT-6]: không lưu hash trần của giá trị (dùng HMAC với khoá riêng của project, hoặc chỉ lưu độ dài match); crop raw chỉ nằm trong thư mục tạm bị xoá sau check; G3 chỉ hiện crop đã che; `runs.jsonl` che literal của regex và seed; có chính sách lưu giữ raw clip.

---

## 2. Chẩn đoán hiện trạng (xếp theo mức nghiêm trọng)

| # | Vấn đề | Mức | Bằng chứng |
|---|---|---|---|
| D1 | **Không có timeout nào được ép bằng code.** "Budget 5 min of OCR" chỉ là văn xuôi. Một lệnh ffmpeg/OCR bị treo sẽ chặn cả pipeline. | critical | `agents/privacy-blurrer.md:20`; `setup_tools.py:1058` gọi `subprocess.run` không có timeout; chỉ `run_capture` có `timeout=60` (`setup_tools.py:506`). [exp: media-perf d] quét OCR không giới hạn bị kill ở 300 s (exit 143), tái hiện đúng hiện tượng "treo". |
| D2 | **Bước cơ khí giao cho LLM mà không có script đứng sau.** Blur, render, mix, captions và checks bị viết lại từ văn xuôi ở mỗi lần chạy. | critical | `scripts/` chỉ có 4 file. `#checks.outputs.16x9.renderer = "opencv"` (haiku tự dựng renderer). `#checks.results.loudness.detail` ghi "the chain does not reproduce". 8 agent haiku, 5 trong số đó phải viết code media. |
| D3 | **Redaction hoàn toàn hậu kỳ, nội suy vị trí từ timestamp marker.** Blur nhảy sang nội dung khác (M-1), và có nguy cơ lộ PII khi nội dung cuộn. | critical | `privacy-blurrer.md:19` ("use the marker timestamps; add intermediate boxes"); `qa.md` M-1; [exp: media-perf c] lerp lộ 3/41. |
| D4 | **Verify chạy theo từng sample, một process cho mỗi sample, và chạy 2–3 lần.** | major | `media-specs/SKILL.md:39,52-53`; `render-engineer.md:24`; `demo-qa.md` step 3. 108 sample: per-process mất 16.7–51 s, single pass mất 2.5–6.8 s (4 thí nghiệm độc lập). |
| D5 | **Cấu hình OCR làm crop nhỏ chậm hơn cả full frame.** Detector của RapidOCR upscale ảnh lên khoảng 736 px ở cạnh ngắn. | major | [exp: media-perf b3] mặc định: 700x120 mất 3334 ms, full frame 1259 ms. Điều này giải thích con số 1.8 s/crop 400x80 [exp: agent-architecture] và 1.18–2.39 s/frame [exp: capture-redaction E2]. Riêng [exp: contrarian] (rapidocr-onnxruntime bản khác) đo được 0.44–0.49 s/frame. |
| D6 | **"OCR không đọc được" bị coi là "không đọc được".** Fallback pixelate có thể đảo ngược. | major | `media-specs:39,76`; [exp: capture-redaction E3]. |
| D7 | **Rule pass/fail do LLM áp dụng nên bị bẻ cong.** | major | Loudness lệch 0.7 LU > 0.5 vẫn pass. Blur có b15–b17 không kiểm tra được vẫn pass (`project.json#checks.results`; `render-engineer.md:20`). |
| D8 | **Vùng trùng lặp:** 10/17 vùng là cùng một email trên header; b15–b17 là cùng một dải API key cuộn nằm dưới header sticky. Graph đặt `enable=` chỉ trên overlay nên phần blur vẫn chạy ở mọi frame. | major | `project.json#blur` (source b15–b17: "API key (behind header strip)"); `media-specs:72`; [exp: media-perf b1]. |
| D9 | **Không có khái niệm dữ liệu seed.** Dữ liệu hư cấu vẫn đi đường đắt nhất. | major | `example/data.js:69`; `demo.yaml:61-63` (`real_data:false`); `app-map.md:6`. |
| D10 | **Staleness không tính được.** `_meta.keys` chỉ lưu version/owner/updated, không lưu fingerprint đầu vào, nên có nhiều vòng chạy lại. | major | `project.py:296-305`; voice v9, captions v7, motion v8, checks v10 (`STATE.md`). Thời gian từ voice v9 03:51Z đến delivery 06:11Z là khoảng 2h20m. |
| D11 | **Người dùng chỉ thấy hình động ở G3.** Câu hỏi cài đặt rải theo 12 stage. G1/G2 bị auto-approve. | major | `setup_tools.py:345-361`; `demo-director.md:27,68-69`; `STATE.md` ("G1 approved (auto) · G2 approved (auto)"). |
| D12 | **Freeze gate gần như mù.** Gate fail duy nhất trong example là lỗi sổ sách. Lỗi thật (M-2, 4.2 s im lặng) chỉ người review phát hiện. | major | Theo `checks.allow.freeze`, allow phủ 73.9% video, vượt ngưỡng 30% mà `media-specs:44` tự thừa nhận là mù. G-1 là sai lệch 74280 so với 74480. |
| D13 | **Văn xuôi phình to và trùng lặp. Lý do kiến trúc đã lỗi thời.** "Subagent cannot spawn" sai với docs hiện tại. Plugin không có hook nào. | major | `demo-director.md` 2387 từ + `run-kits` 2623 từ, khoảng 6.5–7k token. `run-kits/SKILL.md:8`. Docs: "a subagent can spawn subagents… up to three layers" (https://code.claude.com/docs/en/sub-agents). |
| D14 | **Không có CI, không có test media.** | major | Repo không có `.github/`; `scripts/tests/` chỉ có 4 test cho stdlib. |
| D15 | **Ngưỡng CPS 17 sinh finding nhiễu cho tiếng Anh.** | minor | `media-specs:24`; M-4 (17.8, 18.8 cps). Ngưỡng 20 cps cho tiếng Anh còn tranh cãi (xem §3). |

**Kết luận chẩn đoán (fact + suy luận).** Bước blur chậm và treo không phải lỗi tuning. Đó là hệ quả trực tiếp của ba lựa chọn thiết kế:
1. Bí mật đã bị ghi vào clip rồi mới sửa bằng pixel.
2. Một model nhỏ tự viết code đo lường, mỗi sample một tool call.
3. Không có cơ chế nào ép giới hạn thời gian.

Cả 6 chuyên gia độc lập đều đi đến cùng kết luận này.

---

## 3. Bảng ý kiến đa chiều (các điểm bất đồng và quyết định)

| # | Chủ đề | Các phương án | Ai ủng hộ | Quyết định | Lý do |
|---|---|---|---|---|---|
| X1 | **Kiểu mask lúc quay** | (a) CSS `filter: blur(8–9px)`; (b) mask đục, không vẽ glyph; (c) bullets cùng độ dài | (a): end-user EU-3, contrarian C1, reliability RQ-10, media-perf MP-6. (b)/(c): capture-redaction CR-2 | **(b) là mặc định.** (a) chỉ dùng khi `style: blur` và r ≥ 0.35×font-size, cho mục `sensitivity: low`. | E3 là thí nghiệm duy nhất đo khả năng đọc bằng mắt người. Blur 8px có 0 hit OCR [E2, contrarian], nhưng "0 OCR" không chứng minh mắt người không đọc được. Mask đục tốn chi phí như nhau (wall 9.2 so với 9.3 s) và không để lại glyph nào cho mắt hoặc máy đọc, **với các bề mặt mà nó phủ tới**. Nó không tự động phủ input, thuộc tính, SVG, tooltip, ảnh nền chứa chữ; các bề mặt này cần rule riêng (§6.2) và test riêng [RT-1]. Rủi ro thẩm mỹ được giải bằng một "frosted pill" không chứa glyph, có viền sentinel 1 px để kiểm bằng pixel (§6.4). |
| X2 | **OCR là gate hay chỉ tư vấn?** | (a) OCR là release gate (media-perf, reliability); (b) OCR chỉ tư vấn; gate là DOM assertion + hình học mask (capture-redaction CR-3) | — | **Bất đối xứng.** Có hit OCR thì **chặn**. Không có hit thì ghi `not-machine-readable` và **không đủ** để pass. Gate chính cho vùng che lúc quay là: bằng chứng DOM theo từng step (rect lấy mẫu qua rAF + trạng thái highlight/computed style, có timestamp) + kiểm pixel rằng mỗi rect đã log đúng màu pill/sentinel ở frame tương ứng. Gate cho vùng blur hậu kỳ là: OCR=0 + positive control + contact sheet (đã che) cho người duyệt ở G3. | OCR gần như không báo nhầm (regex riêng cho từng giá trị) nhưng bỏ sót nhiều [E3]. Vì vậy hit là bằng chứng mạnh, còn no-hit là bằng chứng yếu. Kiểm pixel thuần bằng màu không khả thi với pill trung tính, nên gate dựa vào log DOM và dùng pixel để đối chiếu [RT-3]. |
| X3 | **Verify ở đâu, phạm vi nào?** | Blurrer tự kiểm (nhận phản hồi sớm) hay chỉ ở bản cuối; chỉ ROI hay thêm full-frame | Tất cả đồng ý verify bản cuối. Một số muốn phản hồi sớm. CR-3 đề xuất full-frame thưa. | **Verify một lần trên mỗi output được giao** (16x9, 9x16, 1x1). Upstream chỉ chạy `preview` (contact sheet + positive control, khoảng 2 s). Với `real-redacted` và non-web, thêm pass OCR regex full-frame thưa có budget [RT-5]. | Scale, reframe và caption band làm dịch vị trí che, nên chỉ bản cuối mới là bằng chứng có giá trị [MP-4, RQ-4]. Mỗi output có mapping riêng (zoom, safe area, caption band) và M-1 chính là lỗi mapping, nên không được giả định output phụ an toàn. Pass full-frame thay thế vai trò "bắt PII không có marker" của `privacy-blurrer` bước 4 mà redesign bỏ đi. |
| X4 | **Luật "no fake data"** | (a) giữ nguyên nghiêm ngặt; (b) hiểu là "cấm thay thế, cho phép che" (RQ-10, MP-6, EU-3); (c) thêm tầng seed (CR-6, C2) | — | **(b) + (c) có kiểm soát.** Agent vẫn bị cấm bịa hoặc thay dữ liệu và cấm sửa số liệu sản phẩm. `data_mode: seeded` **chỉ** hợp lệ khi `demo.yaml` có `privacy.seed_confirmation` do câu trả lời của user tại G1 ghi ra (gồm thời điểm và danh sách giá trị). Bằng chứng trong `app-map` (ví dụ `app-map.md:6`) chỉ dùng để điền sẵn câu hỏi. Gate này **không bao giờ** được auto-approve; auto mode hoặc không có câu trả lời thì ép `real-redacted`. `config.py validate` từ chối `seeded` nếu thiếu `seed_confirmation` [RT-4]. | Luật gốc trong repo nằm ở `app-scout.md:29` và `privacy-blurrer.md:3,29` ("does not create fake data, replace content"), tức là cấm *agent tạo* dữ liệu giả. Dùng seed account của chính app không vi phạm luật này. Plugin cũng đã yêu cầu seed account cho mobile/desktop (`platform-automation/references/mobile.md:38`, `desktop.md:75`). Example cho thấy G1 từng bị auto-approve (`STATE.md`), nên để agent tự kết luận "seed" là tắt bảo vệ bằng phán đoán LLM. **Đây vẫn là quyết định sản phẩm, cần chủ repo xác nhận (xem §9).** |
| X5 | **Số agent** | 18 (giữ "đội"); director + 6 (A1); khoảng 5 (contrarian) | — | **Director + 6 ở cuối P2.** Giữ tên các vai "crew" làm nhãn trong progress và `STATE.md`. | Bản 5 agent của contrarian gộp app-scout vào planner, làm mất context cô lập cho output khám phá dài dòng. Docs khuyên dùng subagent khi "task produces verbose output" (https://code.claude.com/docs/en/sub-agents). Định vị sản phẩm "đội agent đi demo" vẫn giữ được ở tầng trình bày (**suy luận**). |
| X6 | **Tracking vùng cuộn** | OpenCV CSRT; vị trí từ DOM lúc quay; re-detect | — | **Mask lúc quay (web) > bbox DOM/accessibility log theo frame > re-detect > CSRT có re-detect, fail-closed** (mở rộng vùng che ra toàn bộ panel cuộn). | [exp: media-perf c]: vị trí chính xác 0/41 lộ. Tracker drift (pyimagesearch, sighthound: web-snippet). Độ khớp giữa `boundingBox` và frame `recordVideo` **chưa được đo** (R4). |
| X7 | **Độ mạnh blur hậu kỳ** | lr25:lp3 "cho chắc"; quy tắc theo chiều cao chữ | spec hiện tại; MP-5 | **Theo chiều cao chữ:** boxblur `lr ≥ ceil(h/4)`, `lp=1`; pixelize ≥ `ceil(h/3)` chỉ cho vùng không phải secret; vùng secret dùng `drawbox` đục (`t=fill`). | lr20:lp3 chậm hơn pixelize khoảng 4x mà không an toàn hơn [exp: b2]. Với secret, xem X1: dùng mask đục. |
| X8 | **Ngưỡng CPS cho caption** | 17 cứng; 17 mềm, chặn > 20 | RQ-6 (17, nguồn tiếng Anh chưa xác nhận); EU-4 (20, qua Szarkowska, web-snippet) | **Cảnh báo ở > 17, chỉ chặn ở > 20** (tiếng Anh). Ngôn ngữ khác, kể cả `vi`, giữ 17 mềm cho tới khi có nguồn riêng. Ghi rõ trong spec là hai nguồn mâu thuẫn. | Cả hai nguồn đều là web-snippet. BBC R&D (web-snippet) cho thấy tốc độ ít ảnh hưởng đến khả năng hiểu, nên quyết định theo hướng ít chặn. |
| X9 | **Freeze gate** | giữ làm gate; dẫn xuất allow + kiểm tra dead-air | spec; RQ-5 | **Allow được dẫn xuất bằng script** (±250 ms) từ holds và khoảng trống VO. Nếu allow > 30% thì freeze chỉ để thông tin. Thêm gate `dead-air`. | G-1 là false positive thuần sổ sách. M-2 là lỗi thật mà gate không thấy. |
| X10 | **SLO** | bội số của độ dài L (RQ-2) hay con số tuyệt đối (EU-6) | — | **Code dùng bội số L** (hard kill), **sản phẩm báo cáo bằng con số tuyệt đối** (mục tiêu). Cả hai tinh chỉnh lại từ `runs.jsonl` sau khoảng 5 lần chạy thật. | Số liệu hiện tại chỉ đến từ benchmark tổng hợp trên một máy dùng chung, và chưa tính thời gian agent [RT-7]. |
| X11 | **Mua hay tự xây** | adopt playwright-recast/Remotion; mua công cụ hẹp | contrarian B1 | **Không adopt framework làm lõi.** Remotion chỉ giữ làm engine motion tuỳ chọn và phải cảnh báo licence. P2 cân nhắc `ffmpeg-normalize` (MIT) và `stable-ts` (MIT). | Licence Remotion yêu cầu Company License khi tổ chức > 3 nhân viên (`remotion@4.0.545 LICENSE.md:18-21`). playwright-recast còn pre-1.0 và chỉ có một tác giả. |
| X12 | **Video nháp ở G2** | chỉ bảng storyboard (hiện tại); nháp không có motion | EU-2 | **Thêm nháp ở P1,** gắn nhãn "DRAFT". Clip raw của nháp được tái dùng ở S4 khi fingerprint không đổi [RT-7]. | Hai vòng làm lại lớn nhất trong example là vấn đề gu, đúng loại mà nháp bắt được. |
| X13 | **Phạm vi platform v0.3** | chỉ web; giữ cả 4 platform | A-arch hỏi mở | **Giữ adapter 4 platform.** Mask lúc quay chỉ áp dụng cho web ở P0. Non-web đi đường `blur.py` hậu kỳ với bbox lấy từ accessibility tree khi có. | Không có bằng chứng về tỉ lệ dùng thực tế; xoá platform là quyết định không đảo ngược được. |
| X14 | **Cơ chế mask trên DOM** | (a) bọc text khớp trong `span.ds-mask`; (b) CSS Custom Highlight API; (c) overlay div trong shadow root | draft đầu: (a); red-team: (b)/(c) | **(b) là chính, (c) dự phòng** khi trình duyệt không hỗ trợ Highlight hoặc với vùng cần che cả hộp. Không dùng (a). | Bọc text node làm thay đổi DOM do framework quản lý; React/Vue/Svelte có thể lỗi reconciliation (`removeChild`/`insertBefore`) và chỉ hỏng khi bật mask, đúng trên app thật cần mask nhất [RT-2]. (b)/(c) **(chưa test)**: cần fixture React ở Tier 1. |

---

## 4. Kiến trúc đích

### 4.1 Roster agent (trạng thái cuối P2)

| Agent hiện tại (model) | Đích | Model đích | Ghi chú |
|---|---|---|---|
| demo-director (opus) | **demo-director** (main session) | inherit | Gate, user, chạy `demo.py next`. Hấp thụ toolsmith và phần copy của packager. Prompt ≤ 1200 từ. |
| demo-strategist, storyboarder, scriptwriter (inherit/opus/opus) | **story** (gộp) | opus | Brief, độ dài scene và word budget dùng chung context giữa G1 và G2. |
| app-scout (inherit) | **app-scout** (giữ) | sonnet | Output dài dòng nên cần context cô lập. Thêm: xuất `SENSITIVE` selectors và *ứng viên* `seed_values` kèm nguồn (chỉ để điền sẵn câu hỏi G1). |
| localizer (inherit) | **localizer** (giữ, tuỳ chọn) | sonnet | Chỉ chạy khi đổi ngôn ngữ. Output của localizer làm nháp G2 stale và phải dựng lại nháp. |
| scene-automator + capture-operator (inherit/haiku) | **scene-automator** (gộp) | sonnet | Viết scene **ở S2b, trước nháp** [RT-7], gọi `capture.py` (quay + mask + marker + metrics). Bỏ vòng ping-pong giữa automator và operator. |
| motion-designer, sync-editor (inherit) | **editor** (gộp, tuỳ chọn) | sonnet | Chỉ ghi override lên plan mặc định của `timeline.py`/`motion.py`. |
| demo-qa (inherit) | **demo-qa** (giữ) | sonnet; opus tuỳ chọn ở G3 | Đọc `#checks` và contact sheet. Không chạy OCR lại. |
| privacy-blurrer (haiku) | **`blur.py`** | — | P0: agent thành thin caller. P2: xoá agent. |
| voice-producer (haiku) | **`vo.py synth`** | — | `vo.py` đã có sẵn. |
| caption-writer (haiku) | **`captions.py`** | — | |
| sound-mixer (haiku) | **`mix.py`** | — | Loudnorm 2-pass. |
| render-engineer (haiku) | **`render.py` + `checks.py`** | — | |
| packager (haiku) | **`package.py`** | — | Phần viết copy chuyển cho director. |
| toolsmith (haiku) | director gọi thẳng `setup_tools.py` | — | |

Kết quả: **7 LLM agent, không có haiku nào viết code media** [A1, A7]. Các mục được đánh dấu "(gộp)" là **suy luận kiến trúc**. Chưa có đo đạc chất lượng trước và sau khi gộp, nên P2 phải đo (xem §7).

### 4.2 Script deterministic (CLI spec)

Quy ước chung cho mọi script:
- Chỉ dùng stdlib. Dependency nặng (PyAV, numpy, cv2, rapidocr) được import lazy.
- Input và output là JSON. Có `--dry-run`.
- **Heartbeat:** in progress lên stderr dạng JSON, tối thiểu một dòng mỗi 2 s. Đây là giao thức mà `run_bounded` dùng để phát hiện stall cho mọi worker, không chỉ ffmpeg [RT-14].
- Kết quả là **một dòng JSON** trên stdout: `{"status", "elapsed_s", …, "failures":[{"id","owner","class"}]}`.
- Ghi một dòng vào `.demo/<slug>/runs.jsonl` cho mỗi lần chạy. Literal của `privacy.regexes` và `seed_values` trong argv được thay bằng `<redacted:N>` trước khi ghi [RT-6].
- Một handler cấp cao nhất bắt mọi exception không lường trước và trả exit 70, `class: "bug"`, thay vì để Python trả 1 [RT-12].

**Exit code thống nhất** [RT-12]:

| Code | Ý nghĩa | Route |
|---|---|---|
| 0 | pass/ok | — |
| 2 | input hoặc schema sai | owner của input |
| 3 | vượt budget, verdict `incomplete` (đã ghi coverage một phần) | block, hỏi user |
| 4 | thiếu tool (in feature cho `setup_tools --plan`) | director, G1 |
| 10 | finding (lỗi chất lượng) | owner trong `failures[]` |
| 11 | leak (lộ dữ liệu) | owner + block delivery |
| 70 | exception không lường trước (`bug`) hoặc lỗi môi trường | không route cho agent sửa nội dung; retry env ≤ 2 rồi báo lỗi plugin |
| 124 | wall timeout (chỉ `run_bounded`) | retry theo chính sách |
| 125 | stall (chỉ `run_bounded`) | retry theo chính sách |

Exit 1 không được dùng làm tín hiệu, vì nó trùng với exit của Python khi crash và của nhiều tool. `run_bounded` **không** chuyển tiếp exit code của tool bị bọc: nó trả 0 nếu tool chạy xong và ghi `{"tool_rc": N}` trong JSON; chỉ 124/125 là exit của chính nó.

| Script | Lệnh | Timeout mặc định | Ghi chú |
|---|---|---|---|
| `run_bounded.py` | `--wall S --stall S --label L [--heartbeat ffmpeg|jsonl|none] -- cmd…` | do caller đặt | `start_new_session=True`, `stdin=DEVNULL`. Với ffmpeg tự thêm `-nostdin -progress pipe:1` (tách khỏi log stderr, như prototype của RQ). `jsonl`: stall nghĩa là không có dòng heartbeat trong N s. `none`: chỉ wall clock, và phải ghi rõ trong JSON kết quả. Khi hết giờ: TERM gửi cho group → poll `killpg(pid,0)` trong 2 s → KILL group. **Không** chỉ `wait()` leader (bản đầu của reliability-qa từng để lại ffmpeg sống). |
| `privacy_mask.js` (+ helper trong web adapter) | được inject qua `addInitScript` | — | Đọc `selectors`, `regexes`, `mask_style`. Không sửa DOM của app (X14). Che: text node (Highlight/overlay), input/textarea, thuộc tính, SVG, `::selection`. MutationObserver chờ `<head>` rồi mới append style (append vào `documentElement` quá sớm thì style bị drop [exp: contrarian rec2.js]). Mỗi `requestAnimationFrame` lấy mẫu rect của mọi vùng đang che và ghi log có timestamp `{t, kind:"masked", selector, count, rects, state}`. |
| `capture.py` | `--slug S --scene ID [--all] [--reuse-draft]` | 3× độ dài scene + 30 s, retry env ≤ 2 | Trước khi quay: assert trạng thái che (computed style hoặc highlight đã đăng ký) cho mọi selector SENSITIVE, **fail-closed** nếu thiếu. Sau khi quay: ffprobe, đối chiếu log rect với frame (§6.4), ghi `#events` (kèm `masked:true`, `unmaskable[]`). `--reuse-draft`: dùng lại raw clip của nháp nếu fingerprint (scene script, app build, mask config) không đổi. Recorder chạy qua `run_bounded --heartbeat jsonl` (adapter in heartbeat mỗi step). |
| `blur.py plan` | `--slug S` | 30 s | Gộp vùng có bbox giống nhau và thời gian liền kề. Phân loại `static | moving(track) | cover | needs-input`. Exit 2 nếu có keyframe nhảy > `pad` mà không được tách. Áp quy tắc độ mạnh theo chiều cao chữ. Clip không có bằng chứng `masked:true` thì **giữ mọi vùng hiện có** [RT-10]. |
| `blur.py graph` | `--slug S --space final|source --aspect A` | 10 s | In fragment `filter_complex`: `enable=` đặt trên **cả** blur và overlay; vùng chuyển động dùng `sendcmd` theo frame; vùng cover dùng `drawbox t=fill`; cấm encode từng vùng riêng. |
| `blur.py preview` | `--slug S` | 30 s | Decode một lần, chạy positive control OCR cho từng vùng. Crop raw chỉ ghi vào thư mục tạm (`tempfile.mkdtemp`) và bị xoá sau khi chạy. Contact sheet lưu lại **chỉ chứa frame đã che** [RT-6]. |
| `blur.py verify` | `--video F --slug S --aspect A [--budget-s 300] [--fullframe-stride-s 2]` | budget 120 s (seeded/không vùng) / 300 s (real), cho mỗi output | Một decode PyAV cho mỗi output. Sample ROI mỗi 0.5 s, cộng first/last, cộng mọi frame trong đoạn chuyển động. Gộp ROI thành montage. Với `real-redacted`/non-web: thêm full-frame regex OCR mỗi `stride` giây, chia chung budget. RapidOCR chạy trong worker subprocess với `Det.limit_type=max, limit_side_len=960`, model chọn theo `language` (R7), worker in heartbeat jsonl. Hit chỉ ghi `region, t_ms, match_len` và tuỳ chọn `hmac` (khoá ngẫu nhiên theo project, lưu ở `.demo/<slug>/.secret/key`, ngoài `project.json`, trong `.gitignore`) [RT-6]. |
| `checks.py` | `--slug S [--only …] --json`; `checks.py dod <stage>` | 0.3×L + 60 s | Một pass ffmpeg kết hợp ebur128 + blackdetect + freezedetect + silencedetect (8.1 s so với 22 s chạy riêng [exp: RQ E5]). Gồm lint VTT, drift, loudness so với cả target và `#mix.preview`, dead-air, allow dẫn xuất. Là **nơi duy nhất** ghi `#checks`, qua code path riêng của `project.py` (§4.3). |
| `timeline.py`, `captions.py`, `mix.py`, `render.py`, `package.py` | `--slug S [--scenes s03,…]` | timeline 30 s; mix 0.5×L; render 3×L (mỗi tỉ lệ thêm 2×L), stall 30 s | P1/P2. `--scenes` cho phép render lại một phần rồi re-concat (§5, revoice/rerecord). `package.py` loại `media/preview/`, `.secret/` và raw clip khỏi delivery. |
| `demo.py` | `status --json`, `next --json`, `run <stage> [--scenes …]`, `fail <stage> --finding ID`, `accept <check> <span>`, `brief <stage>`, `migrate` | — | State machine. Bảng `STAGES` chứa kind, inputs, outputs, owner, `timeout_s`, `max_attempts`, `tool_feature`. Mở rộng từ `project.py:37-63` (`OWNERS`, `DOWNSTREAM`, `RUN_ORDER`). |

### 4.3 Hook và ép ownership (`hooks/hooks.json`; plugin agent bỏ qua field `hooks` trong frontmatter)

Hook trong `hooks.json` có phạm vi cả session, nên chạy cho mọi subagent và tool call, kể cả của plugin khác [RT-11]. Vì vậy:

- **Mọi hook đọc `agent_type` từ input và exit 0 ngay nếu không phải agent của demo-studio.** PreToolUse cho main session chỉ áp dụng khi đường dẫn đích nằm dưới `.demo/`.
- **SubagentStop** chạy `demo.py verify-handoff && checks.py dod <agent>`, timeout 30 s. Fail thì exit 2 (chặn dừng, trả lý do cho agent). Bộ đếm chặn lưu ở `.demo/<slug>/hook-state.json` theo `(agent, stage)`; nếu input có `stop_hook_active=true` hoặc bộ đếm ≥ 2 thì cho dừng và đánh dấu stage `blocked` (tránh lặp vô hạn).
- **PreToolUse(Write|Edit)** từ chối ghi trực tiếp `.demo/*/project.json`.
- **PreToolUse(Bash)** (P2, tuỳ chọn) từ chối lệnh `ffmpeg|rapidocr` không chạy qua `run_bounded`, và từ chối vòng lặp `-ss`.
- **Ownership trong code:** `project.py set` kiểm `OWNERS`. Key `checks` chỉ ghi được qua hàm `project.write_checks()` mà `checks.py` và `blur.py verify` import trực tiếp; lệnh CLI `project.py set checks …` luôn bị từ chối. Như vậy đường Bash (`project.py set checks`) mà hook Write/Edit không bắt được cũng bị chặn.
- Mọi agent có `maxTurns` (scene-automator 40, các agent khác 25). Agent lá không có `Agent` trong `tools`.

### 4.4 Skill

- `media-specs` trở thành **đặc tả mà script hiện thực**. Bỏ snippet theo từng sample. Mọi snippet ffmpeg đều có `-nostdin` và chạy qua `run_bounded`.
- `run-kits` thu gọn thành tài liệu tham khảo, chỉ nạp khi cần. Xoá rule "subagent cannot spawn" (`run-kits/SKILL.md:8`, `demo-director.md:13`).
- Thêm mục "Privacy" vào `platform-automation`: masking cho web (gồm input, tooltip, SVG), demo mode trên OS (`simctl status_bar`, adb DND), và cảnh báo **không** dùng `FLAG_SECURE` vì nó làm đen cả cửa sổ (Sauce Labs, web-snippet).

### 4.5 State và contract trong `project.json` (schema 2)

```jsonc
{
  "_meta": { "schema": 2,
    "keys": { "<k>": { "version": 3, "owner": "...", "updated": "...",
                       "inputs": { "events": 2,
                                   "file:raw/s01.webm": {"size":..., "mtime_ns":..., "ino":...} },
                       "attempts": { "<finding-id>": 1 } } } },
  "events": { "clips": { "<sid>": { "masked": true,
                                    "mask_log": "events/s01.mask.jsonl",
                                    "selectors": [{"selector","count","style"}],
                                    "unmaskable": [{"reason":"canvas|iframe|image|native|bg-image","bbox","t"}],
                                    "tracks": { "<elem>": [[t_ms,x,y,w,h], ...] } } } },
  "blur":   { "regions": [{ "id","bbox","spans":[[t0,t1],...],"mode":"static|track|cover",
                            "style":"opaque|boxblur|pixelize","text_h","source":"capture-mask|events|manual|legacy" }] },
  "checks": { "blur": { "<aspect>": { "verdict":"pass|leak|inconclusive|incomplete","sampled","total","seconds",
                          "fullframe": {"sampled","stride_s"},
                          "positive_control":{"<region>":true},
                          "hits":[{"region","t_ms","match_len"}] } },
              "privacy_capture": { "selectors_matched", "frames_unmasked": 0, "rects_checked": 0 } }
}
```

**Fingerprint file** [RT-17]: lưu `(size, mtime_ns, inode)`. Chỉ khi bộ ba này đổi mới tính sha256 và cache vào `.demo/<slug>/cache/hashes.json`. Một lần `set` bình thường không phải hash lại hàng trăm MB.

`demo.yaml` thêm `privacy.data_mode`, `privacy.seed_confirmation` (do G1 ghi), `privacy.selectors`, `privacy.regexes`, `privacy.seed_values`, `privacy.mask_style`, `privacy.raw_retention` (`delete-after-delivery` mặc định cho `real-*`).

---

## 5. Luồng chuẩn

Ký hiệu: L là độ dài video cuối (giây). Budget là **hard kill trong code**. Mục tiêu sản phẩm áp dụng cho web demo ≤ 90 s với toolkit đã cài sẵn (warm), và là **chưa đo** cho tới khi có baseline P0.

| Stage | Kind | Input → Output | Budget / SLO | Definition of Done (máy kiểm) | Khi fail hoặc timeout |
|---|---|---|---|---|---|
| S0 Setup | script | `setup_tools --plan` cho **mọi** stage | — | Một kế hoạch cài đặt gộp | Thiếu tool → exit 4 → hỏi ở G1 vòng 2, không hỏi giữa chừng |
| S1 Plan | agent `story` (+ `app-scout`) | brief, app → `brief.md`, `app-map.md` (SENSITIVE, ứng viên seed kèm nguồn) | app-scout `maxTurns` 25 | Brief có audience, 1 message, 1 CTA, channel preset | needs-input chỉ dùng cho nội dung |
| **G1** | gate (≤ 2 vòng AskUserQuestion) | — | — | **Vòng 1:** gói brief/preset/độ dài/format, mặc định theo preset, kèm mẫu giọng **dựng sẵn trong plugin** cho từng voice (không cần TTS đã cài). **Vòng 2:** `data_mode` (chỉ hiện lựa chọn `seeded` khi app-scout có ứng viên kèm nguồn) + duyệt kế hoạch cài đặt. Câu trả lời `seeded` được ghi vào `privacy.seed_confirmation`. Không auto-approve phần `data_mode` [RT-4, RT-8]. | Không trả lời hoặc auto mode → `real-redacted` |
| S2a Script | `story` (+ `localizer`) | → `storyboard.md`, `narration.md` | — | Word budget khớp `length_s` ±10% | — |
| S2b Scenes | `scene-automator` | storyboard, app-map → scene scripts | `maxTurns` 40 | Mọi scene chạy được ở `--dry-run` | Route về scene-automator |
| S3 Draft | script | TTS + `capture.py --all` (có mask) + caption burn + encode veryfast + contact sheet 1 fps | mục tiêu (chưa đo) ≤ 10 phút từ G1, gồm cả S2 | Nháp phát được; `checks.privacy_capture.frames_unmasked = 0` | Capture fail thì retry env ≤ 2, sau đó route về scene-automator |
| **G2** | gate | — | — | User duyệt **video nháp** + script. Lexicon đã nằm trong audio nháp. | Phản hồi kiểu "quá nhanh" hay "thiếu nội dung" quay về S2a; đổi ngôn ngữ thì localizer chạy và nháp dựng lại |
| S4 Capture final | `capture.py --reuse-draft` | → `raw/*.webm`, `#events` | 3×scene + 30 s, chỉ cho scene stale | Mọi clip probe được; marker ≥ số mark; mọi rect đã log khớp frame (§6.4) | Exit ≠ 0 thì route theo bảng exit code |
| S5 Privacy fallback | script `blur.py plan|preview` (chỉ khi có `unmaskable`, clip `masked:false`, hoặc non-web) | → `#blur` | plan 30 s + preview 30 s | Schema hợp lệ; mỗi vùng có positive control và contact sheet (đã che) | `needs-input` gửi cho director |
| S6 Timeline/motion/captions/mix | script (+ override từ `editor`) | → `#timeline`, `#motion`, `#captions`, `#mix` | timeline 30 s; mix 0.5×L | Allow spans được dẫn xuất; VTT lint pass | — |
| S7 Render | script `render.py` (nhúng `blur.py graph` theo từng aspect) | → `final-*.mp4` | 3×L + 2×L cho mỗi tỉ lệ thêm, stall 30 s | Thời lượng khớp `#timeline` ±40 ms | Exit 124/125 thì retry 1 lần, sau đó hỏi user |
| S8 Checks | script `checks.py` + `blur.py verify` cho **mỗi** output | → `#checks` | 0.3×L + 60 s; verify ≤ 120 s (seeded) / 300 s (real) mỗi output | Tất cả check blocking pass. Không vùng nào `inconclusive` mà chưa được người xác nhận. | Exit 3 nghĩa là incomplete: **block**, không pass âm thầm. Exit 11: block delivery |
| S9 QA | agent `demo-qa` | contact sheet + `#checks` → `qa.md` | `maxTurns` 25 | Finding có owner và mức (blocking/advisory) | — |
| **G3** | gate | — | — | File final, contact sheet đã che, "Blocking: none / Optional: N" bằng ngôn ngữ thường. Không hiện bảng JSON, không hiện crop raw. | — |
| S10 Package | script | → `delivery` | 60 s | Có đủ file cho mọi kênh trong preset; không chứa `media/preview/`, `.secret/`, raw | Xoá raw theo `privacy.raw_retention` |

**Luồng sửa theo scene** (`/revoice`, `/rerecord`) [RT-9]: `demo.py run voice --scenes s03` hoặc `demo.py run capture --scenes s03` → `render.py --scenes s03` render lại đoạn đó và re-concat → `checks.py` + `blur.py verify` trên output mới → contact sheet so sánh trước/sau cho scene đó. Mục tiêu revoice ≤ 5 phút và rerecord ≤ 10 phút chỉ có hiệu lực khi cơ chế `--scenes` đã có (P2); trước đó là chạy lại toàn bộ downstream.

**Mục tiêu sản phẩm (chưa đo, chốt sau baseline P0 có tính thời gian agent):**
- Từ G1 đến nháp: ≤ 10 phút.
- Từ G2 đến bản final: ≤ 20 phút.
- Toàn bộ hậu kỳ sau capture: ≤ 10×L.
- Revoice một scene: ≤ 5 phút. Rerecord một scene: ≤ 10 phút (từ P2).
- Sửa chỉ caption hoặc motion: ≤ 3 phút, không OCR lại phần không đổi.

Neo số đo: encode nháp 15 s mất khoảng 20 s [exp: end-user-product]; pass checks kết hợp mất 0.08×L [exp: RQ E5]. Thời gian agent viết scene (S2b) **chưa có số đo** và nhiều khả năng chiếm phần lớn (**suy luận**) [RT-7].

**Chính sách vòng sửa (fix loop)** [RQ-8]:
- Mỗi lỗi được phân loại vào một trong năm nhóm:
  - `env`: retry ≤ 2, cùng input.
  - `deterministic`: không retry, route theo owner.
  - `bookkeeping`: script tự sửa, ví dụ `demo.py accept freeze 74280-74480`.
  - `judgement`: chuyển cho người ở gate.
  - `bug` (exit 70): không route cho agent nội dung; báo lỗi plugin kèm log.
- Tối đa 2 vòng tự động cho mỗi finding ID, đếm bằng `_meta.keys.*.attempts`. Đến lần 3 thì `demo.py next` trả về `ask-user`.
- Chỉ chạy lại các stage stale theo fingerprint. Thay đổi allow hoặc ngưỡng **không bao giờ** kích hoạt render lại.
- Finding loại advisory không chặn delivery.

---

## 6. Thiết kế lại bước privacy/blur (chi tiết)

### 6.1 Tầng 0: chính sách dữ liệu (G1)

`privacy.data_mode`:
- **`seeded`**: app tự seed dữ liệu, hoặc user cung cấp dữ liệu seed. Điều kiện **bắt buộc**: `privacy.seed_confirmation = {answered_at, by:"user", values:[…]}` do câu trả lời G1 vòng 2 ghi ra. Nguồn trích (ví dụ `app-map.md:6`, `example/data.js:69`) chỉ hiện trong câu hỏi để user cân nhắc. Bỏ qua mask và OCR cho đúng các giá trị đã xác nhận. Mask vẫn bật cho mọi regex không khớp `seed_values`, đóng vai lưới an toàn. `config.py validate` từ chối `seeded` khi thiếu `seed_confirmation`; chạy ở auto mode thì `demo.py` ép `real-redacted` [RT-4].
- **`real-redacted`** (mặc định khi không có xác nhận): mask đục lúc quay, cộng blur hậu kỳ cho các mục unmaskable, cộng verify trên mọi output, cộng pass full-frame thưa.
- **`real-visible`**: chỉ dùng khi có đồng ý tường minh của user, ghi vào `demo.yaml`; cũng không auto-approve.
- Luôn cấm: agent bịa hoặc thay dữ liệu, sửa số liệu hay kết quả sản phẩm, gõ secret thật trong automation.

### 6.2 Tầng 1: che lúc quay (web)

1. `app-scout` xuất `SENSITIVE` selectors. Mặc định luôn có `[data-sensitive]`; example đánh dấu ở `index.html:16,44`.
2. `capture.py` inject `privacy_mask.js` qua `context.addInitScript` **trước mọi lần load trang**. Script **không chèn hay bọc node nào vào cây DOM của app** (X14). Các bề mặt và cách che:

   | Bề mặt | Cách che | Trạng thái |
   |---|---|---|
   | Text node khớp selector hoặc regex | `CSS.highlights.set("ds-mask", new Highlight(...ranges))` + `::highlight(ds-mask){color:transparent;background-color:<pill>;text-shadow:none}`. Dự phòng: overlay div định vị từ `Range.getClientRects()` trong shadow root gắn vào `documentElement`, cập nhật mỗi rAF. | E1/E2 đã đo với text tĩnh + toast (bằng CSS); Highlight/overlay **(chưa test)** |
   | `<input>`, `<textarea>`, `contenteditable` khớp selector | `-webkit-text-fill-color:transparent; caret-color:transparent` + nền pill | **(chưa test)** |
   | Giá trị gõ vào input không có selector | listener `input`/`change` (capture phase) áp regex lên `.value`; khớp thì gắn class qua `adoptedStyleSheets` (không sửa thuộc tính của app) hoặc overlay hộp phần tử | **(chưa test)** |
   | `placeholder` | `::placeholder{color:transparent}` cho phần tử khớp | **(chưa test)** |
   | Tooltip gốc từ `title`, autofill dropdown | không che được bằng CSS: tắt autofill trong context Playwright, đưa chuột ra khỏi phần tử có `title` khớp regex; nếu không tránh được thì ghi `unmaskable` | **(chưa test)** |
   | SVG `<text>` | `fill:transparent` cho phần tử khớp; text khớp regex dùng overlay hộp | **(chưa test)** |
   | `::selection` | `::selection{color:transparent}` trên vùng che | **(chưa test)** |
   | Ảnh nền hoặc `<img>` chứa chữ, canvas/WebGL, cross-origin iframe, closed shadow DOM | cover box toàn hộp phần tử bằng overlay nếu biết box; không biết thì `unmaskable[]` cho tầng 2 | — |

3. **Assertion fail-closed** trước khi quay: với mọi selector, trạng thái che (computed style hoặc highlight đã đăng ký và có range) phải đúng. Nếu sai thì exit 11 và không quay. Lý do: các kiểu inject ngây thơ hỏng mà không báo lỗi:
   - inject ở DOMContentLoaded làm lộ 1.5 s đầu (6/25 frame);
   - append vào `documentElement` quá sớm thì style bị drop và lộ suốt clip [exp: contrarian rec.js, rec2.js].
4. Mỗi rAF log `rects` và `state` của các vùng đã che (`events/<sid>.mask.jsonl`). Dữ liệu này là input cho gate (§6.4) và là nguồn track nếu sau này cần.

**Số đo đã có** [exp: capture-redaction E1/E2, contrarian]:

| Chỉ số | Kết quả |
|---|---|
| Email sticky | che 230/230 frame, kích thước không đổi |
| Toast chèn muộn | che 211/211 frame, kể cả frame đầu tiên |
| API key cuộn | clip đúng ở mép viewport |
| Lộ dữ liệu | OCR 0/149 frame (contrarian); 0 match cho solid/blur4/blur8 (capture-redaction) |
| Wall time quay | 9.2–9.8 s, như nhau ở mọi biến thể, nên overhead nằm trong nhiễu |
| Đối chứng không mask | email đọc được ở 23/24 và 24/25 frame |

Giới hạn: các số đo trên chỉ phủ text node trên trang tĩnh. Input, SVG, tooltip, Highlight API và app có framework re-render phải pass Tier 1 (§7.2) trước khi P0 bật `privacy_mask.js` làm mặc định [RT-1, RT-2].

Hệ quả cho example (**suy luận** từ dữ liệu): b1–b14 là email header và API key trong DOM, nên khi quay lại với mask, số vùng blur hậu kỳ giảm từ 17 xuống 0. b15–b17 là phần dải API key cuộn nằm dưới header sticky; chúng **chỉ** được bỏ khi có bằng chứng mask lúc quay cho phần tử đó (`masked:true` + log rect). Lý do "không đọc được ở độ phân giải gốc" không được dùng, vì motion zoom có thể làm chúng đọc được [RT-15].

### 6.3 Tầng 2: blur hậu kỳ (fallback: desktop, mobile, unmaskable, clip cũ)

Thứ tự nguồn dữ liệu cho non-web:
1. Privacy/demo mode của app, hoặc seed account (vẫn cần xác nhận G1).
2. Demo mode của OS (`simctl status_bar override`, adb DND).
3. bbox tĩnh lấy từ accessibility tree (Appium/UIA).
4. OpenCV tracking (CSRT có re-detect mỗi N frame; mất track thì mở rộng vùng che ra toàn bộ panel).

`blur.py plan`:
- Gộp vùng trùng (b1–b10 trở thành 1 vùng nhiều span) khi lập plan mới.
- Tách segment ở mọi chỗ nhảy > `pad`. Keyframe nhảy mà không tách thì exit 2.
- Dải mỏng như b15–b17 được giữ dưới dạng vùng `cover` (`drawbox t=fill`), chi phí gần bằng 0 [RT-15].
- Clip `masked:false` (gồm mọi clip cũ) giữ toàn bộ vùng hiện có.

`blur.py graph`:
- `crop,boxblur=lr=ceil(h/4):lp=1:enable='…'` với `enable` trên **cả** blur và overlay.
- Secret và vùng cover dùng `drawbox=…:t=fill`.
- Vùng chuyển động dùng `sendcmd` theo frame (khoảng 270 fps trong graph, nhanh hơn vòng OpenCV ngoài ở 168 fps [exp: media-perf c]).

**Số đo graph** [exp: media-perf b1/b2]:

| Cấu hình | Thời gian |
|---|---|
| 17 vùng, `enable=` chỉ trên overlay | 13.4 s |
| 17 vùng, `enable=` trên cả blur | 7.6 s |
| Mỗi vùng một pass encode riêng | khoảng 155 s |
| boxblur lr20:lp3 | 10.5 s |
| pixelize16 | 2.8 s |

Ngưỡng an toàn với OCR, đo trên chữ 24 px: boxblur lr6 an toàn, lr3 lộ; pixelize 8 an toàn, 4 lộ. Lưu ý giới hạn của các ngưỡng này: chúng chỉ chứng minh "không đọc được bằng máy" (xem X1/X2).

### 6.4 Tầng 3: một lần verify cho mỗi output

**Vùng che lúc quay (gate `privacy_capture`)** [RT-3]:
- Bằng chứng chính là log DOM: mọi phần tử SENSITIVE nằm trong viewport ở thời điểm t phải có entry `state=masked` với rect trong log rAF gần t (sai lệch ≤ 1 frame, xem R4).
- Đối chiếu pixel: với mỗi rect đã log, lấy frame tương ứng trong raw clip và kiểm (a) vùng trong rect gần đồng màu pill (độ lệch chuẩn thấp, không có cạnh glyph) và (b) viền sentinel 1 px có mặt. Pill mặc định vẽ viền sentinel màu cố định để có tín hiệu kiểm được; với `mask_style: blur` thì chỉ kiểm (b).
- `frames_unmasked` = số frame có phần tử SENSITIVE trong viewport mà thiếu entry log hoặc fail đối chiếu pixel.
- Chi phí: single decode 230 frame mất 1.8–3.4 s, cộng phân tích pixel trên rect (**suy luận**: vài giây).

**Vùng blur hậu kỳ, hoặc `real-redacted`, hoặc non-web.** `blur.py verify` chạy trên **mỗi** output được giao (`final-16x9`, `final-9x16`, `final-1x1`), mỗi output có mapping riêng [RT-5].
- Decode tuần tự một lần cho mỗi output.
- Gộp ROI thành montage. Montage 12 ROI mất 599 ms cho một lần gọi.
- `Det.limit_type=max`.
- Với `real-redacted`/non-web: thêm full-frame regex OCR mỗi `stride` giây (mặc định 2 s), để bắt PII không có marker (vai trò của `privacy-blurrer` bước 4 cũ). Pass này dùng chung budget; hết budget thì exit 3.
- OCR chạy trong worker subprocess, in heartbeat jsonl, bị kill khi stall.
- Bắt buộc positive control. Positive control fail thì verdict là `inconclusive`.
- Hit OCR thì exit 11. Không có hit thì ghi "not-machine-readable"; contact sheet đã che đi kèm cho người duyệt.
- Kết quả được ghi vào `#checks.blur.<aspect>`. `privacy-blurrer` không chạy sweep; `demo-qa` không chạy OCR lại.

**Ngân sách verify ước tính cho example** (**suy luận** từ số đo):

| Hạng mục | Ước tính |
|---|---|
| Số sample ROI | 108 → khoảng 25–40 sau khi gộp vùng; về 0 nếu mask lúc quay |
| Full-frame thưa (real-redacted, 80 s, stride 2 s) | khoảng 40 frame × 0.44–1.26 s ≈ 18–50 s |
| Decode | ≤ 5 s mỗi output |
| OCR ROI | khoảng 40 sample × 0.3–0.6 s ≈ 12–25 s, ít hơn khi gộp montage |
| Tổng mỗi output | ≤ 60 s cho seeded/ROI-only; ≤ 120 s khi có full-frame; so với hiện tại 3 pass × khoảng 3.3 phút [exp: agent-architecture: 108 crop = 194.6 s với cấu hình mặc định] |

Budget cứng: 120 s cho seeded, 300 s cho real, mỗi output. Vượt budget thì exit 3 và **block**.

### 6.5 Vệ sinh dữ liệu nhạy cảm trong artefact [RT-6]

| Artefact | Rủi ro | Xử lý |
|---|---|---|
| `#checks.blur.hits` | hash trần của email/key ngắn có thể brute-force | chỉ lưu `region, t_ms, match_len`; nếu cần so trùng thì HMAC với khoá ngẫu nhiên theo project ở `.demo/<slug>/.secret/key` (ngoài `project.json`) |
| Crop positive control, contact sheet raw | chứa plaintext | ghi vào thư mục tạm, xoá sau khi chạy; chỉ lưu contact sheet đã che; G3 chỉ hiện bản đã che |
| `runs.jsonl` | argv chứa regex hoặc seed literal | thay bằng `<redacted:N>` trước khi ghi |
| Raw clip (`real-*`, non-web) | giữ secret vô thời hạn | `privacy.raw_retention: delete-after-delivery` mặc định; `keep` phải chọn tường minh |
| Git / delivery | commit nhầm | template `.gitignore` cho `.demo/*/media/preview/`, `.demo/*/.secret/`, `.demo/*/raw/`; `package.py` loại các thư mục này |

### 6.6 So sánh tổng

| | Hiện tại (example) | Đích, web `seeded` | Đích, web `real-redacted` | Đích, non-web |
|---|---|---|---|---|
| Vùng blur hậu kỳ | 17 | 0 | 0 (+ unmaskable) | sau gộp, ví dụ ≤ 6 (+ cover rẻ) |
| Số lần OCR | 2–3 pass, 108 sample mỗi pass | 0 | 1 pass bounded mỗi output, có full-frame thưa | 1 pass bounded mỗi output, có full-frame thưa |
| Drift kiểu M-1 | có | không xảy ra với phần tử được che (mask đi theo DOM) | như bên trái | vị trí theo frame, fail-closed |
| Treo | có thể | timeout cứng | timeout cứng | timeout cứng |

---

## 7. Tiêu chí chấp nhận và chiến lược test

### 7.1 Tiêu chí đo được

**Privacy**
1. Web: 100% selector SENSITIVE và regex hit được che trong mọi frame mà phần tử nằm trong viewport (`frames_unmasked = 0` theo §6.4), kể cả phần tử thêm sau khi load, giá trị gõ vào input, placeholder và SVG text. Có assertion trạng thái che trước khi quay.
2. Privacy làm capture wall time tăng ≤ 5%. Phần tử DOM-maskable có 0 vùng blur hậu kỳ. Bật mask không làm hỏng app framework (fixture React re-render pass, không có lỗi console mới).
3. Style mặc định là đục. Nếu dùng blur thì r ≥ 0.35×font. Không pixelate secret.
4. Vùng tĩnh hoặc sticky chỉ xuất hiện một lần mỗi clip trong `#blur` mới lập. Example: số nhánh graph giảm từ 17 xuống ≤ 6 (đường non-web, chưa tính vùng cover).
5. Vùng chuyển động: 0 hit OCR khi sample **mọi** frame của span. `plan` exit 2 với keyframe nhảy.
6. `seeded` không có `seed_confirmation` bị `config.py validate` từ chối; auto mode luôn ra `real-redacted`.
7. Không artefact nào lưu lại (`project.json`, `runs.jsonl`, `media/preview`, delivery) chứa plaintext hay hash trần của giá trị nhạy cảm (test grep trên example với giá trị đã biết).
8. Verify chạy trên mọi output được giao; `#checks.blur` có entry cho từng aspect.

**Hiệu năng và độ tin cậy**

9. `blur.py verify`: mỗi output chỉ decode một lần (≤ 2 process ffmpeg). Trên final 80 s 1080p 17 vùng, ROI-only chạy ≤ 60 s wall trên 4 vCPU. Không bao giờ vượt `--budget-s` + 10 s.
10. Mọi stage script, khi gặp input FIFO treo hoặc worker không gửi heartbeat (ffmpeg, OCR worker, recorder), trả về 124/125 (hoặc 3) trong khoảng `timeout_s` + 5 s, **0 process còn sót** trong group (kiểm bằng `ps`).
11. 100% lệnh ffmpeg/ffprobe/OCR/recorder trong `agents/*.md` và `skills/**` chạy qua `run_bounded` và có `-nostdin`. CI lint báo 0 vi phạm.
12. Chạy lại một stage với input không đổi là no-op (cache hit, < 2 s, không tăng version, không hash lại file lớn). Thay đổi chỉ `#motion.allow` thì chỉ chạy lại checks.
13. Fix loop: lần thứ 3 trên cùng finding ID làm `demo.py next` trả về `ask-user` (có test). Exception không lường trước trả 70, không bị route như finding.

**Đúng đắn của checks**

14. `#checks` chỉ do `checks.py`/`blur.py verify` ghi: `project.py set checks` từ CLI bị từ chối, Write/Edit trực tiếp bị hook chặn. Không check nào pass khi positive control fail, hoặc khi loudness lệch `#mix.preview` > 0.5 LU.
15. Allow freeze được dẫn xuất. Dead-air phải bắt được M-2 (88.05–92.22 s) và không báo G-1.
16. Hook không chặn agent hay tool call nào ngoài demo-studio (test với một agent giả có `agent_type` khác).

**Sản phẩm**

17. Lần chạy `/new` đầu tiên: G1 ≤ 2 vòng AskUserQuestion, tổng ≤ 3 gate; 0 câu hỏi về tool sau G1 (đếm số lần gọi AskUserQuestion).
18. G2 có video nháp. Thời gian G1 → nháp và G2 → final được đo và ghi vào `runs.jsonl`; mục tiêu ≤ 10 / ≤ 20 phút (web ≤ 90 s, warm) chốt sau baseline.
19. G3 không bao giờ FAIL vì sổ sách vô hình với người xem.
20. Mọi `commands/*.md` (cut, fix, new, rerecord, review, revoice, run, script, shoot, tools) pass dry-run trên example ở mỗi phase, và không còn tham chiếu tới agent đã xoá.

**Kiến trúc (cuối P2)**

21. ≤ 7 LLM agent; không agent nào chỉ toàn bước CLI hoặc công thức. Prompt của director ≤ 1200 từ. Mỗi kết quả stage đưa vào context ≤ 200 từ.
22. Một lần chạy sạch trên example có < 15 lần ghi state (hiện là 52).

### 7.2 Chiến lược test (hồi quy trên `example/`)

- **Tier 0** (mỗi PR, < 1 phút): unit test hiện có; lint schema snippet `project.json`; lint "no bare ffmpeg / có `-nostdin`"; lint tham chiếu agent trong `commands/*.md`; `config.py validate` từ chối `seeded` thiếu xác nhận.
- **Tier 1** (mỗi PR, < 5 phút):
  - test treo cho `run_bounded`: FIFO → 125, không process nào sót, khoảng 6 s [exp: RQ E6]; thêm OCR worker giả và recorder giả không gửi heartbeat;
  - exit code: script ném exception giả → 70; `run_bounded` bọc tool trả rc 1 → exit 0 với `tool_rc:1`;
  - `checks.py` trên clip `testsrc2` + sine có span black/freeze/silence đã biết;
  - `blur.py`: graph parse được (`-f null`), positive control hit, sau blur 0 hit, keyframe nhảy bị tách, child giả bị kẹt trả exit 3, verify chạy đủ mọi aspect, không file nào dưới `.demo/` chứa plaintext seed;
  - `privacy_mask.js`, quay 10 s trên `example/index.html` (dùng chính trang mẫu, không dữ liệu giả mới): đối chứng không mask phải có hit, có mask thì `frames_unmasked=0`; toast chèn muộn được che; **gõ một giá trị khớp regex vào input** (giá trị lấy từ `example/data.js`) và assert `frames_unmasked=0`; placeholder và SVG text được che;
  - fixture React tối thiểu (một list re-render một giá trị bị che mỗi 200 ms, đặt trong `scripts/tests/fixtures/`, dữ liệu lấy từ example): không lỗi reconciliation, vẫn che ở mọi frame;
  - hook: agent `agent_type` lạ → exit 0; bộ đếm SubagentStop cho dừng sau 2 lần.
- **Tier 1-vi** (P0, mỗi PR) [RT-16]: `language: vi` chọn model OCR latin/vi; positive control trên mẫu có dấu (ví dụ "Nguyễn") phải hit; regex email phủ local part không phải ASCII; caption `vi` dùng ngưỡng 17 mềm.
- **Tier 2** (nightly hoặc thủ công): e2e 2 scene trên example với TTS cache hoặc stub. Golden lưu dưới dạng metric text, không lưu byte video (theo cách FATE của FFmpeg, web-snippet). Dung sai: duration ±0.1 s, LUFS ±0.5, SSIM ≥ 0.95 trên 5 keyframe, OCR hits 0, M-1 không tái hiện, tổng wall time trong SLO. Thêm test migrate: chạy `/cut` trên bản schema 1 của example và assert 0 leak OCR trên mọi output [RT-10].
- **CI:** chưa có `.github/` nên phải tạo mới; GitHub Actions ubuntu với ffmpeg qua apt và Chromium của Playwright.
- **Đo trước và sau** từ `runs.jsonl` và transcript: thời gian từng stage (gồm thời gian agent), số tool call, token. Đây là cách kiểm các khẳng định đang được đánh dấu "suy luận" trong tài liệu này.

---

## 8. Kế hoạch migrate theo phase

### P0: chữa nỗi đau chính (blur chậm/treo) mà không đổi roster

- **Bước đầu tiên:** đo baseline trên example (thời gian từng stage gồm agent, số tool call, token) để có mốc cho R12 và mục tiêu P2.
- **Phạm vi:** `run_bounded.py` (heartbeat, exit code); `privacy_mask.js` + `capture.py` (inject, assertion, log rect, đối chiếu pixel); `blur.py plan|graph|preview|verify` (mọi aspect, full-frame thưa); một tập checks tối thiểu (blur verdict, positive control → inconclusive, loudness so với preview); `data_mode` + `seed_confirmation` + validate; ownership `#checks` trong `project.py`; fingerprint `inputs` trong `project.py set`; vệ sinh artefact (§6.5); test Tier 1-vi.
- **File chạm tới:**
  - `scripts/run_bounded.py`, `scripts/blur.py`, `scripts/privacy_mask.js`, `scripts/capture.py` (hoặc phần tương đương trong web adapter), `scripts/project.py` (schema 2, `migrate`, `write_checks`, fingerprint), `scripts/config.py` (validate `seeded`).
  - `scripts/tests/test_run_bounded.py`, `test_blur.py`, `test_privacy_mask.js`, `test_project_migrate.py`, `scripts/tests/fixtures/react-list/`.
  - `agents/privacy-blurrer.md`: thành thin caller, cấm code tự viết.
  - `agents/capture-operator.md`, `agents/scene-automator.md`: gọi `capture.py`.
  - `agents/render-engineer.md`: nhúng `blur.py graph`, gọi `verify` cho mọi aspect, bỏ OCR riêng.
  - `agents/demo-qa.md`: bỏ OCR.
  - `agents/demo-director.md`: G1 vòng 2 hỏi `data_mode`, không auto-approve.
  - `skills/media-specs/SKILL.md`: bỏ snippet `-ss` theo sample, bỏ pixelate, thêm `-nostdin`, thêm quy tắc độ mạnh.
  - `skills/platform-automation/references/web.md`: masking.
  - `templates/demo.yaml`: privacy block; `templates/gitignore`: các thư mục ở §6.5.
- **Exit criteria:** tiêu chí 1–11 và 14 (phần blur/loudness) pass trên example. Verify ROI-only trên example ≤ 60 s mỗi output. Không còn snippet `-ss` theo sample. Tier 1 và Tier 1-vi xanh.
- **Rollback** [RT-13]: rollback bằng plugin version hoặc git tag; `0.2.0` vẫn cài được. Không giữ bản sao agent trong cây (`agents/legacy/`), vì loader có thể nạp trùng `name:`. Không duy trì công tắc `privacy.engine: v2|legacy`. Riêng `privacy_mask.js` có cờ `privacy.capture_mask: false` để rơi về đường `blur.py` hậu kỳ (cùng một pipeline, không phải pipeline thứ hai). Cờ này được xem lại sau khi P0 chạy ổn định một minor version.

### P1: checks một nguồn, hook, trải nghiệm gate

- **Phạm vi:**
  - `checks.py` đầy đủ: combined pass, VTT lint, dead-air, allow dẫn xuất, `dod`.
  - `hooks/hooks.json` (SubagentStop có lọc `agent_type` và bộ đếm, PreToolUse Write/Edit); `maxTurns` cho mọi agent.
  - `demo.py status|accept`.
  - Cache key và `runs.jsonl`.
  - G1 hai vòng có kế hoạch cài đặt gộp và mẫu giọng dựng sẵn; S2b scene authoring trước nháp; G2 có video nháp; S4 tái dùng raw nháp; G3 dùng bản tóm tắt bằng ngôn ngữ thường.
  - Channel presets.
  - CI Tier 0–1.
- **File chạm tới:** `scripts/checks.py`, `scripts/demo.py`, `scripts/capture.py` (`--reuse-draft`), `hooks/hooks.json`, `hooks/demo_hook.py`, `commands/new.md`, `commands/run.md`, `commands/fix.md`, `commands/review.md`, `agents/demo-director.md` (gate), `agents/scene-automator.md` (S2b), `templates/qa.md`, `templates/demo.yaml` (preset), `assets/voice-samples/`, `.github/workflows/ci.yml`.
- **Exit criteria:** tiêu chí 12–19; trên example, G-1 không còn fail và M-2 bị dead-air bắt; tiêu chí 20 (dry-run mọi command) pass với roster cũ.
- **Rollback:** tắt hook bằng cách xoá entry trong `hooks.json` (không ảnh hưởng dữ liệu). Nháp ở G2 có cờ `gates.draft: false`.

### P2: thu gọn roster và chuyển phần cơ khí thành script

- **Phạm vi:**
  - `timeline.py`, `captions.py`, `mix.py`, `render.py` (`--scenes`, re-concat), `package.py`, `vo.py synth`.
  - `demo.py next|brief|run` (có `--scenes`) và contact sheet so sánh trước/sau theo scene.
  - Gộp `story` (strategist + storyboarder + scriptwriter), gộp `scene-automator` + `capture-operator`, gộp `editor`.
  - Xoá 8 agent haiku và toolsmith. Viết lại director (≤ 1200 từ). Thu gọn run-kits. PreToolUse Bash guard. CI Tier 2.
  - Cân nhắc `ffmpeg-normalize` và `stable-ts`.
- **Map command → stage** (phải xong trước khi xoá agent tương ứng) [RT-9]:

  | Command | Hiện gọi (ví dụ) | Sau P2 |
  |---|---|---|
  | `/new` | director, strategist, … | `demo.py next` từ S0 |
  | `/run` | director | `demo.py next` (tiếp tục) |
  | `/script` | strategist, storyboarder, scriptwriter | agent `story` → `demo.py run script` |
  | `/shoot` | scene-automator, capture-operator | agent `scene-automator` → `demo.py run capture` |
  | `/revoice` | voice-producer, caption-writer, sync-editor, render-engineer | `demo.py run voice --scenes …` → downstream stale |
  | `/rerecord` | scene-automator, capture-operator, privacy-blurrer, render-engineer | `demo.py run capture --scenes …` → downstream stale |
  | `/cut` | motion-designer, caption-writer, sync-editor, render-engineer | agent `editor` (override) → `demo.py run timeline` → render/checks |
  | `/fix` | theo owner finding | `demo.py fail … ` → route theo owner mới |
  | `/review` | demo-qa | `checks.py` + agent `demo-qa` |
  | `/tools` | toolsmith | director gọi `setup_tools.py --plan` |

- **File chạm tới:** thêm vào danh sách trên: **toàn bộ** `commands/*.md` (cut, fix, new, rerecord, review, revoice, run, script, shoot, tools), các agent bị gộp hoặc xoá, `skills/run-kits/SKILL.md`, `.claude-plugin/plugin.json`.
- **Exit criteria:** tiêu chí 20–22; e2e example khớp golden; revoice/rerecord một scene đạt mục tiêu ≤ 5/≤ 10 phút; token/lần chạy và số tool call giảm so với baseline P0 (**mục tiêu**: ≥ 40%, là suy luận, chốt sau khi có baseline).
- **Rollback:** gộp theo kiểu strangler, từng agent một. Mỗi lần gộp là một release riêng; rollback bằng cài lại version trước. Không giữ bản sao agent cũ trong cây.

### Tương thích ngược cho các `.demo/` có sẵn [RT-10]

- `project.py` đọc được schema 1 và 2. Khi ghi lần đầu, `project.py migrate --slug S` nâng schema lên 2:
  - backup `project.json.schema1.bak` trước khi ghi;
  - thêm `_meta.keys.*.inputs = {}`, nghĩa là "fingerprint không rõ" → stale khi chạy stage kế tiếp, chỉ cho các key downstream của thay đổi;
  - đánh dấu mọi clip cũ `events.clips.*.masked = false` (clip quay trước v0.3 không có mask);
  - **giữ nguyên** mọi vùng `#blur`, gắn `source: "legacy"`; không gộp vùng lúc migrate (gộp chỉ xảy ra khi `blur.py plan` lập plan mới, và plan mới vẫn giữ mọi vùng cho clip `masked:false`);
  - `privacy.data_mode` lấy từ `real_data`: `false` hay `true` đều thành `real-redacted` (an toàn mặc định; **không** tự suy ra `seeded`). Vì clip `masked:false`, mọi lần render lại đi đường `blur.py` hậu kỳ cộng verify mọi output và full-frame thưa.
- Project đã giao (`delivery` có mặt) không bị đụng trừ khi user chạy `/fix`, `/rerecord` hoặc `/cut`.
- Lệnh `/status` đọc được cả hai schema.
- Test bắt buộc: `/cut` trên bản schema 1 của example cho 0 leak OCR trên mọi output (Tier 2).
- Bump `plugin.json` version: P0 → 0.3.0, P1 → 0.4.0, P2 → 0.5.0. Cập nhật `description` ("18 agents") ở P2.

---

## 9. Rủi ro và câu hỏi mở

| # | Rủi ro / câu hỏi | Ảnh hưởng | Giảm thiểu / ai quyết |
|---|---|---|---|
| R1 | **Tầng `seeded` có làm thay đổi tinh thần "no fake data"?** | Định vị sản phẩm | Cần chủ repo quyết. Thiết kế giữ "agent không bao giờ bịa hoặc thay dữ liệu", `seeded` chỉ bật bằng câu trả lời của người, mặc định là `real-redacted`. |
| R2 | Cross-origin iframe, shadow DOM, canvas, ảnh chứa chữ chưa được test với scanner | Có thể lộ dữ liệu | Fail-closed: cover cả box từ trang cha, hoặc đẩy vào `unmaskable` + full-frame OCR thưa. Thêm test P1. |
| R3 | App thật của user không có selector hay `data-*` ổn định, nên regex scanner phải gánh nhiều hơn | Che nhầm text UI (false positive) | app-scout dẫn xuất selector; regex chặt theo từng giá trị; contact sheet ở G2. |
| R4 | Độ khớp giữa rect log theo rAF/`boundingBox` và frame `recordVideo` (≤ 1 frame ở 25 fps?) chưa được đo | Gate `privacy_capture` và đường track cho non-mask | Thí nghiệm đầu P0 trước khi chốt dung sai của gate. |
| R5 | Ngưỡng SLO đến từ một benchmark tổng hợp trên máy dùng chung, chưa gồm thời gian agent | Budget sai thì kill nhầm hoặc chờ thừa | Baseline đầu P0; tinh chỉnh từ `runs.jsonl` sau khoảng 5 lần chạy thật. |
| R6 | Windows: process-group kill không áp dụng được | Treo trên host Windows | Nhánh Job Object hoặc `taskkill /T /F`, chưa test. |
| R7 | RapidOCR với tiếng Việt có dấu (model `ch` mặc định) | Positive control fail giả, cho ra `inconclusive`, chặn S8 | Chọn model theo `language`; test Tier 1-vi ở P0. |
| R8 | Gộp agent có thể làm giảm chất lượng sáng tạo | G1/G2 kém hơn | Đo trước và sau ở P2; gộp từng bước; rollback theo version. |
| R9 | Subagent có gọi được AskUserQuestion không? | Có thể đặt gate trong nested agent | Chưa kiểm chứng; giữ gate ở main session. |
| R10 | Tier 2 CI cần TTS mạng (edge-tts) | CI flaky | Dùng TTS stub hoặc cache. |
| R11 | Nguồn bị chặn mạng: docs.sentry.io, supademo, storylane, ffmpeg.org, docs.python.org, gnu.org, netflix partnerhelp, cdn.openai.com, docs.langchain.com | Một số trích dẫn chỉ là web-snippet | Kiểm lại khi mở host; các kết luận then chốt đều có thí nghiệm cục bộ chống lưng. |
| R12 | Dưới 3 phút cho 2–3 lần render là mục tiêu, không phải số đo | Kỳ vọng sai | Đo baseline ở đầu P0. |
| R13 | Tỉ lệ demo chạy trên app user kiểm soát được so với app bên thứ ba | Quyết định mặc định mask/seed | Hỏi user; thu thập từ `demo.yaml` qua các lần chạy. |
| R14 | CSS Custom Highlight API: hỗ trợ trên Chromium của Playwright, nhưng Firefox/WebKit của Playwright có thể khác; chỉ một tập thuộc tính CSS áp được cho `::highlight` | Mask không áp trên engine khác | Assertion fail-closed phát hiện; dự phòng overlay; P0 chỉ cam kết Chromium **(chưa test)**. |
| R15 | Overlay theo rAF có thể trễ một frame khi cuộn nhanh | Lộ một frame ở mép | Overlay phủ rộng thêm `pad`; gate §6.4 bắt được; ưu tiên Highlight (vẽ cùng frame với text). |
| R16 | UI bản địa hoá (vi) đổi độ dài text và layout lúc quay | Rect, word budget và caption lệch | localizer làm nháp stale; G2 duyệt lại nháp đã bản địa hoá. |

---

## 10. Nguồn tham khảo

### Web (đọc được trực tiếp)
- Playwright params (recordVideo không có mask; screenshot có `mask`/`maskColor`): https://raw.githubusercontent.com/microsoft/playwright/main/docs/src/api/params.md
- Sentry Session Replay privacy: https://raw.githubusercontent.com/getsentry/sentry-docs/master/docs/platforms/javascript/common/session-replay/privacy.mdx
- rrweb guide: https://raw.githubusercontent.com/rrweb-io/rrweb/master/guide.md
- playwright-recast README: https://raw.githubusercontent.com/ThePatriczek/playwright-recast/main/README.md
- Anthropic, Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, Multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Writing tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents
- Anthropic, Effective context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code hooks: https://code.claude.com/docs/en/hooks

### Web-snippet (chỉ có đoạn trích tìm kiếm)
- Loom blur: https://support.atlassian.com/loom/docs/blur-sensitive-information/
- Unredacter (pixelate có thể đảo ngược): https://thehackernews.com/2022/02/this-new-tool-can-retrieve-pixelated.html
- Screen Studio masking: https://screen.studio/guide/masking-sensitive-data-in-screen-recordings
- Storylane: https://www.storylane.io/blog/remove-sensitive-data-from-software-demo
- Supademo Smart Blur: https://supademo.com/features/blur
- Sauce Labs FLAG_SECURE: https://docs.saucelabs.com/mobile-apps/features/bypass-screenshot/
- Guardsquare Android 15: https://guardsquare.com/blog/android-15-screen-spying-protection
- Tracker OpenCV: https://pyimagesearch.com/2018/07/30/opencv-object-tracking/
- Sighthound CSRT/KCF: https://www.sighthound.com/blog/csrt-kcf-opencv-tracker-real-time-video
- Benchmark tracker: https://arxiv.org/pdf/2110.05102
- OpenAI agents guide: https://openai.com/business/guides-and-resources/a-practical-guide-to-building-agents/
- LangGraph durable execution: https://docs.langchain.com/oss/python/langgraph/durable-execution
- Bazel remote caching: https://bazel.build/remote/caching
- Netflix 42 chars/line: https://backlothelp.netflix.com/hc/en-us/articles/219375728
- Netflix 2 dòng: https://backlothelp.netflix.com/hc/en-us/articles/215758617
- Netflix 17 cps (Slovak): https://backlothelp.netflix.com/hc/en-us/articles/115002812588-Slovak-Timed-Text-Style-Guide
- Szarkowska et al. (20 cps tiếng Anh): https://ueaeprints.uea.ac.uk/id/eprint/100082/1/6_Szarkowska_et_al.pdf
- BBC R&D tốc độ phụ đề: https://bbcbreakingnews.pages.dev/rd/blog/2015-09-how-fast-should-subtitles-be
- YouTube −14 LUFS: https://productionadvice.co.uk/youtube-loudness/
- ebur128 mặc định −23: https://ayosec.github.io/ffmpeg-filters-docs/4.3/Filters/Multimedia/ebur128.html
- FFmpeg FATE: https://ffmpeg.org/pipermail/ffmpeg-cvslog/2017-September/109408.html
- WCAG 1.2.2: https://www.w3.org/WAI/WCAG21/Understanding/captions-prerecorded.html
- Wistia độ dài video: https://wistia.com/blog/optimal-video-length
- Arcade benchmarks: https://www.arcade.software/post/arcade-benchmarks-2024
- Meta video best practices: https://creators.facebook.com/blog/10-video-best-practices
- So sánh công cụ demo: https://www.ngram.com/blog/demo-video-maker-comparison
- ICO synthetic data: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/privacy-enhancing-technologies/what-pets-are-there/synthetic-data
- ICO case study: https://cy.ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/privacy-enhancing-technologies/case-studies/synthetic-data-to-test-the-effectiveness-of-a-vulnerable-persons-detection-system-in-financial-services/
- MAST (multi-agent failures): https://arxiv.org/abs/2503.13657
- Cognition, Don't build multi-agents: https://cognition.ai/blog/dont-build-multi-agents
- playwright-recast voiceover: https://thepatriczek.github.io/playwright-recast/docs/guides/adding-voiceover

### Thí nghiệm cục bộ
Gốc: `/tmp/claude-0/-home-user-demo-studio/93a734b2-3873-5432-9c4d-49479b80e3ba/scratchpad/exp/` (thư mục tạm, có thể bị dọn; các số liệu then chốt đã chép vào tài liệu này).

- **capture-redaction/**
  - E1: mask CSS + MutationObserver trong recordVideo. 230/230, 211/211, wall 9.2–9.8 s.
  - E2: OCR full frame. Đối chứng 23/24; blur2 lộ 5 frame; solid/blur4/blur8 cho 0; 1.18–2.39 s/frame. Kiểm pixel dùng mask magenta + connected components (`mag.py`).
  - E3: bán kính blur so với OCR và mắt người (`out/human_montage.png`).
- **media-perf/**
  - a: chiến lược sample. 18.2 s so với 1.34–1.85 s; VP8 11.4 s so với 1.34 s.
  - b1: 17 vùng. 13.4 → 7.6 s; tách pass khoảng 155 s.
  - b2: tốc độ và độ kháng OCR của từng kiểu blur.
  - b3: latency RapidOCR. 3334 → 316 ms; montage 599 ms.
  - c: vùng chuyển động. Lerp lộ 3/41, chính xác 0/41; sendcmd 7.7 s.
  - d: semantics của kill; quét không giới hạn bị kill ở 300 s.
- **agent-architecture/**
  - Sampling: 33.8 s so với 4.5 s.
  - OCR batch: 108 crop mất 194.6 s.
  - `stage_runner.py`: FIFO trả timeout ở 5.01 s.
  - Context director: khoảng 6.5–7k token.
- **reliability-qa/**
  - E1/E2: timeout ngây thơ để lại ffmpeg mồ côi.
  - E3: thiếu `-nostdin` chỉ còn 61/108.
  - E4: 51.0 s so với 6.8 s.
  - E5: combined checks 8.1 s so với 22.0 s.
  - E6: watchdog stall (`-progress pipe:1`) 4.0 s, kill ở 6.2 s, không process nào sót.
- **end-user-product/**
  - Nháp 15 s: capture 15.7 s, encode 3.67 s, contact sheet 0.41 s (`draft.mp4`, `sheet.png`).
  - CSS blur 8px trên `[data-sensitive]` (`email_crop.png`).
- **contrarian/**
  - `rec.js`, `rec2.js`, `rec3.js` + `ocrall.py`: 0/149 lộ; inject ngây thơ lộ 6/25 hoặc lộ toàn bộ.
  - Sampling: 16.7 s so với 2.5 s.
  - OCR: 0.44–0.49 s/frame.
  - Kiểm licence npm/PyPI.
  - Số liệu repo: 18 agent / 11,222 từ; 52 lần ghi state.

### Repo
- `plugins/demo-studio/agents/privacy-blurrer.md:3,14-23,29`
- `agents/render-engineer.md:14-24`
- `agents/demo-qa.md:14`
- `agents/app-scout.md:29`
- `agents/demo-director.md:13,27,51,54,68-69`
- `commands/{cut,fix,new,rerecord,review,revoice,run,script,shoot,tools}.md`
- `skills/media-specs/SKILL.md:24,36-44,50-54,70-76`
- `skills/run-kits/SKILL.md:8,24`
- `skills/platform-automation/references/web.md:74`, `mobile.md:38`, `desktop.md:75`
- `scripts/project.py:37-66,94-116,148,225,296-317`
- `scripts/setup_tools.py:345-361,506,1058-1063`
- `templates/demo.yaml:68-70`
- `.claude-plugin/plugin.json` (version 0.2.0)
- `example/index.html:16,44`
- `example/data.js:69`
- `example/.demo/STATE.md`
- `example/.demo/ai-video-trends-v2/{project.json, qa.md, app-map.md:6, demo.yaml:61-63}`

---

## Phụ lục A. Phản biện đã xử lý (red-team review)

Verdict red-team: `revise`. 17 issue: 2 blocker, 8 major, 7 minor. Chấp nhận 17/17 (RT-13 chấp nhận với một điều chỉnh nhỏ, ghi rõ ở cột thay đổi). Từ chối 0.

| # | Mục | Issue (tóm tắt) | Mức | Quyết định | Thay đổi |
|---|---|---|---|---|---|
| RT-1 | 6.2 / X1 | "an toàn tuyệt đối" quá mức; mask không phủ input, thuộc tính, tooltip, SVG, `::selection`, ảnh nền | blocker | accepted | Bỏ "tuyệt đối"; bảng bề mặt trong §6.2 (input `-webkit-text-fill-color`, listener `.value`, placeholder, SVG `fill`, `::selection`, tooltip/autofill → tránh hoặc `unmaskable`); test Tier 1 gõ giá trị vào input; tiêu chí 1. |
| RT-2 | 6.2 / privacy_mask.js | bọc `span.ds-mask` phá reconciliation của framework | major | accepted | X14 mới: Highlight API là chính, overlay shadow root dự phòng, không sửa DOM app; fixture React ở Tier 1; tiêu chí 2; R14, R15. |
| RT-3 | 6.4 / capture.py | gate pixel thuần không khả thi với pill trung tính; P0 thiếu `capture.py` | major | accepted | Gate dựa trên log DOM theo rAF + đối chiếu pixel trên rect + viền sentinel 1 px (§6.4, X2); `capture.py` vào danh sách file P0; R4 chuyển lên đầu P0. |
| RT-4 | X4 / 6.1 | `seeded` có thể bật bằng bằng chứng do agent viết hoặc G1 auto-approve | blocker | accepted | `seed_confirmation` bắt buộc, không auto-approve; app-map chỉ điền sẵn câu hỏi; auto mode → `real-redacted`; `config.py validate` từ chối; tiêu chí 6; test Tier 0. |
| RT-5 | 6.4 / X3 | verify chỉ ROI bỏ sót PII không marker; bỏ verify 9x16/1x1 là giả định chưa chứng minh | major | accepted | Verify mọi output; full-frame regex OCR thưa có budget cho `real-redacted`/non-web; `#checks.blur.<aspect>`; tiêu chí 8; bảng ngân sách cập nhật. |
| RT-6 | 4.5 / preview / runs.jsonl | hash trần brute-force được; crop raw và contact sheet chứa plaintext; argv lộ regex; raw clip giữ vô hạn | major | accepted | §6.5 mới: `match_len` hoặc HMAC khoá ngoài `project.json`; crop raw ở thư mục tạm; G3 chỉ hiện bản đã che; redact argv; `raw_retention`; `.gitignore` template; `package.py` loại; tiêu chí 7. |
| RT-7 | 5 S3/S4 | nháp không có scene để quay; quay hai lần; SLO 10 phút ngoại suy thiếu thời gian agent | major | accepted | Thêm S2b (scene-automator trước nháp); `capture.py --reuse-draft` theo fingerprint; SLO ghi "chưa đo", baseline đầu P0 gồm thời gian agent. |
| RT-8 | G1 / tiêu chí 13 | G1 "một màn hình" vượt giới hạn AskUserQuestion; mẫu giọng cần TTS chưa cài | minor | accepted | G1 ≤ 2 vòng (brief/preset; data_mode + cài đặt); mẫu giọng dựng sẵn trong `assets/voice-samples/`; tiêu chí 17 đếm theo vòng. |
| RT-9 | 8 commands | xoá agent ở P2 làm hỏng 7 command; SLO revoice/rerecord không có cơ chế | major | accepted | Bảng map command → stage trong P2; toàn bộ `commands/*.md` vào danh sách file; `--scenes` + re-concat + contact sheet trước/sau; SLO revoice/rerecord chỉ hiệu lực từ P2; tiêu chí 20 (dry-run mọi command). |
| RT-10 | Tương thích ngược | clip cũ quay không mask nhưng migrate về đường mask với 0 vùng hậu kỳ; gộp b1–b10 đổi nghĩa dữ liệu cũ | major | accepted | Clip cũ `masked:false`; giữ nguyên mọi vùng (`source: legacy`), không gộp lúc migrate; `blur.py plan` giữ vùng cho clip `masked:false`; test `/cut` trên schema 1 cho 0 leak mọi output. |
| RT-11 | 4.3 Hooks | hook toàn session chặn cả plugin khác; "sau 2 lần" thiếu state; `project.py set checks` qua Bash lọt hook | major | accepted | Lọc `agent_type`, exit 0 với agent ngoài; `stop_hook_active` + bộ đếm trong `.demo/<slug>/hook-state.json`; ownership ép trong `project.py` (`write_checks()` chỉ import được, CLI `set checks` bị từ chối); tiêu chí 14, 16. |
| RT-12 | 4.2 Exit codes | exit 1 trùng crash Python; `run_bounded` chuyển tiếp rc của tool | minor | accepted | Finding = 10, leak = 11, bug/env = 70 qua handler cấp cao; `run_bounded` trả `tool_rc` trong JSON; bỏ exit 1; nhóm `bug` trong fix loop; test Tier 1. |
| RT-13 | 8 Rollback | `agents/legacy/` có thể bị loader nạp trùng `name:`; hai pipeline song song tốn công | minor | accepted (một phần về hình thức) | Rollback bằng plugin version / git tag; bỏ `agents/legacy/` và công tắc `v2|legacy`. Giữ một cờ hẹp `privacy.capture_mask: false` để rơi về đường hậu kỳ có sẵn (cùng pipeline, không nhân đôi spec), xem lại sau một minor version. |
| RT-14 | 4.2 run_bounded | stall chỉ định nghĩa cho ffmpeg; `-progress pipe:2` trộn với log | minor | accepted | Giao thức heartbeat jsonl cho mọi worker; ffmpeg dùng `-progress pipe:1`; `--heartbeat none` phải ghi rõ; test treo cho OCR worker và recorder. |
| RT-15 | 6.2 b15–b17 | b15–b17 là dải API key cuộn, lý do "không đọc được" sai sau zoom | minor | accepted | Sửa D8 và §6.2: chỉ bỏ khi có bằng chứng mask lúc quay; ở đường fallback giữ làm vùng `cover` `drawbox t=fill`. |
| RT-16 | Localization | regex/OCR/CPS chưa tính tiếng Việt; localizer không kích hoạt dựng lại nháp | minor | accepted | Tier 1-vi ở P0 (model OCR theo `language`, positive control có dấu, regex non-ASCII); localizer làm nháp stale và G2 duyệt lại; R16. |
| RT-17 | 4.5 fingerprints | sha256 file media mỗi lần `set` phá tiêu chí no-op < 2 s | minor | accepted | Fingerprint `(size, mtime_ns, inode)`, sha256 chỉ khi đổi, cache ở `cache/hashes.json`; tiêu chí 12 thêm "không hash lại file lớn". |
