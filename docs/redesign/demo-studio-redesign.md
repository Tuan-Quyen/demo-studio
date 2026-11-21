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
> - `[exp2: …]` là thí nghiệm của vòng desktop/mobile (§6.7); `[RTn-k]` trỏ tới issue k của bảng "Phản biện desktop/mobile" trong Phụ lục A.
>
> **Phiên bản tài liệu:** rev 2 (2026-11-21). Rev 1 chỉ thiết kế chi tiết cho web. Rev 2 thêm §6.7 (desktop & mobile) từ 4 báo cáo chuyên gia mới (`android`, `apple`, `desktop`, `posthoc-tracking`) và một vòng red-team thứ hai, kèm các chỉnh sửa liên quan ở §1–§10.

---

## 1. Tóm tắt quyết định

1. **Che dữ liệu nhạy cảm ngay lúc quay là mặc định cho web.** Script `scripts/privacy_mask.js` được inject qua `context.addInitScript`. Nó **không sửa DOM của app** [RT-2]. Cơ chế:
   - text node: CSS Custom Highlight API (`::highlight(ds-mask)`) trên các `Range` khớp selector hoặc regex; dự phòng bằng overlay div định vị theo `Range.getClientRects()` trong một shadow root cấp cao nhất;
   - `<input>`/`<textarea>`: `-webkit-text-fill-color:transparent` cho phần tử khớp selector, và listener `input` áp regex lên `.value` [RT-1];
   - thuộc tính hiển thị (placeholder, title, aria-label dùng cho tooltip), SVG `<text>` (`fill`), `::selection`, autofill: có rule riêng (xem §6.2).
   - Khi đó blur hậu kỳ chỉ còn là đường ngoại lệ.
   - Bằng chứng: mask có mặt ở 230/230 frame, toast chèn muộn được che 211/211 frame, không lệch vị trí, overhead thời gian quay ≈ 0 [exp: capture-redaction E1] [exp: contrarian rec3.js: 0/149 frame lộ]. Các thí nghiệm này **chỉ phủ text node tĩnh và một toast**; input, SVG, tooltip và cơ chế Highlight/overlay là **(chưa test)** và phải có test Tier 1 ở P0 trước khi bật mặc định.
   - `recordVideo` của Playwright không có option mask; `mask` chỉ có ở `screenshot` (https://raw.githubusercontent.com/microsoft/playwright/main/docs/src/api/params.md; `playwright-core/types/types.d.ts:11549`).
   - Với non-web, nguyên tắc "che lúc quay là mặc định" cũng áp dụng, theo bậc thang ở §6.7, và chỉ với các tầng đã có trong version đang cài. Electron dùng main-process hook chạy chính `privacy_mask.js` trong main world (biến thể chỉ có stylesheet đã đo 0/324, n=1; biến thể main-world đầy đủ chưa test). Bản thân `addInitScript` sau `electron.launch()` lộ 324/324 frame [exp2: desktop D1b].
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
5. **Chỉ verify một lần, trên mọi bản render được giao, bằng `blur.py verify`** [RT-5]. Mỗi output giải mã tuần tự một lần, gộp nhiều ROI vào một montage cho mỗi lần gọi OCR, đặt `Det.limit_type=max`, bắt buộc có positive control. Với `real-redacted` và non-web, thêm một pass OCR regex full-frame thưa (stride thô) có budget, để bắt PII không có marker. Non-web chọn frame theo change gate thay cho stride cố định (§6.7.4).
   - Một lần decode nhanh hơn 6.8–10 lần so với chạy một `ffmpeg -ss` cho mỗi sample [exp: contrarian, agent-architecture, reliability-qa E4, media-perf a].
   - Với `limit_type=max`, ROI 700x120 giảm từ 3334 ms xuống 316 ms [exp: media-perf b3].
   - Xoá các pass OCR trùng ở `privacy-blurrer.md:20`, `render-engineer.md:24` và `demo-qa`.
6. **Vùng chuyển động lấy vị trí chính xác theo từng frame, không nội suy keyframe qua chỗ nhảy.** Thứ tự ưu tiên: mask lúc quay > bbox DOM log theo frame > re-detect > CSRT (có re-detect, fail-closed).
   - Nội suy (lerp) 2 s lộ email và số thẻ ở 3/41 sample; vị trí chính xác theo frame lộ 0/41 [exp: media-perf c].
   - Đây là nguyên nhân của QA M-1.
   - **Web giữ nguyên thứ tự trên. Với non-web, thứ tự là** [RTn-15]: mask cùng frame lúc quay > vị trí suy ra từ pixel của frame (scroll-offset propagation) > log vị trí chính xác đồng bộ bằng stamp + pts > overlay a11y có pad/guard > rect a11y chỉ khi tĩnh > cover container (§6.7.3). Cấm lerp/hold và CSRT/KCF cho container cuộn; CSRT chỉ cho bề mặt không có hình học. Số đo: lerp lộ 1472–3099/9807 [exp2: apple E1]; KCF mất 28/28 item ở frame fling đầu tiên [exp2: posthoc-tracking A5].
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
14. **Mọi thời gian non-web theo pts của từng frame.** `blur.py timebase` chạy trước CFR. Map theo index lộ 2286/3894 item-frame [exp2: posthoc-tracking C1]; lệch tới 2433 ms [exp2: android E3]. Mọi rect đi qua một hàm `transform` duy nhất sang pixel của clip (§6.7.1).
15. **Không bao giờ dùng content-protection** (`FLAG_SECURE`, `WDA_EXCLUDEFROMCAPTURE`, `setContentProtection`, `NSWindowSharingNone`) làm cơ chế privacy. Dry run kiểm trực tiếp cờ tự che của app và trả `blocked` (§6.7.5).
16. **Trung thực về platform:** mọi cơ chế Android/iOS/macOS/Windows mang nhãn "chưa test trên platform thật" cho tới khi fixture pass trên thiết bị thật (P3). Số đo duy nhất là Electron và GTK3 trên Linux/Xvfb, phần lớn n=1; phần còn lại là mô phỏng.

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
| D16 | **Non-web chỉ có fallback hậu kỳ**; không có tầng che lúc quay, không có assertion fail-closed. | critical | §6.3 (bản rev 1, 4 bước nguồn); `references/mobile.md` chỉ có "mark sensitive". Thí nghiệm cho thấy làm được: Electron hook 0/324, GTK CSS 0/350 (đo-Linux, n=1). |
| D17 | **Hướng dẫn Electron ngầm định đường web áp được nguyên**, nhưng `addInitScript` sau launch không tới cửa sổ đầu tiên và script không phát hiện ra. | critical | `desktop.md:13-23`; [exp2: desktop D1b] `masked:false`, 324/324. |
| D18 | **Nguồn bbox a11y tĩnh và CSRT (§6.3 rev 1, bước 3–4) lộ trên list cuộn.** | critical | Overlay/a11y không guard: 181/325 (desktop, đo-Linux), 207–219/360 (android, mô phỏng); hold/lerp 1440–3099/9807 (apple, mô phỏng); CSRT mất 13/28, KCF 28/28. |
| D19 | **Hướng dẫn mobile nói "normalize CFR" nhưng không yêu cầu pts khi tính thời gian.** | major | `mobile.md` (dòng scrcpy); [exp2: android E3] lệch 2433 ms; [exp2: posthoc-tracking C1]. |
| D20 | **Query a11y không có giới hạn**: WDA có thể chặn vô hạn; UiAutomator2 waitForIdle có đường hardcode 10 s; page-source mất > 1 phút. | major | Appium `settings.md` `accessibilityDeadline` mặc định 0; appium#9147, discuss.appium.io (web-snippet). |
| D21 | **`desktop.md:44` khuyên `gdigrab title=`**, kiểu quay chỉ-cửa-sổ sẽ loại overlay mask khỏi bản quay. | major | **suy luận** từ cơ chế quay theo cửa sổ; chưa test trên Windows. |
| D22 | **Vệ sinh OS chỉ có một dòng gợi ý**: không có chuỗi lệnh SystemUI, không khôi phục khi fail, không xử lý bàn phím/autofill/clipboard/heads-up; `simctl status_bar` được báo hỏng trên iOS 17+. | major | `mobile.md` DND; AOSP `demo_mode.md`; jessesquires.com (web-snippet); [RTn-5]. |
| D23 | **Giả định OCR/regex của §6.4 vỡ trên native**: `_` bị đọc thành dấu cách; RapidOCR bỏ qua detect khi w/h > 8. | major | [exp2: posthoc-tracking B2]: 2040/2611 và 360/360. |

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
| X6 | **Tracking vùng cuộn** | OpenCV CSRT; vị trí từ DOM lúc quay; re-detect | — | **Mask lúc quay (web) > bbox DOM/accessibility log theo frame > re-detect > CSRT có re-detect, fail-closed** (mở rộng vùng che ra toàn bộ panel cuộn). | [exp: media-perf c]: vị trí chính xác 0/41 lộ. Tracker drift (pyimagesearch, sighthound: web-snippet). Độ khớp giữa `boundingBox` và frame `recordVideo` **chưa được đo** (R4). **Áp cho web.** Với non-web, thay bằng X16/X17 và §6.7.3 (CSRT bị cấm cho container cuộn) [RTn-15]. |
| X7 | **Độ mạnh blur hậu kỳ** | lr25:lp3 "cho chắc"; quy tắc theo chiều cao chữ | spec hiện tại; MP-5 | **Theo chiều cao chữ:** boxblur `lr ≥ ceil(h/4)`, `lp=1`; pixelize ≥ `ceil(h/3)` chỉ cho vùng không phải secret; vùng secret dùng `drawbox` đục (`t=fill`). | lr20:lp3 chậm hơn pixelize khoảng 4x mà không an toàn hơn [exp: b2]. Với secret, xem X1: dùng mask đục. |
| X8 | **Ngưỡng CPS cho caption** | 17 cứng; 17 mềm, chặn > 20 | RQ-6 (17, nguồn tiếng Anh chưa xác nhận); EU-4 (20, qua Szarkowska, web-snippet) | **Cảnh báo ở > 17, chỉ chặn ở > 20** (tiếng Anh). Ngôn ngữ khác, kể cả `vi`, giữ 17 mềm cho tới khi có nguồn riêng. Ghi rõ trong spec là hai nguồn mâu thuẫn. | Cả hai nguồn đều là web-snippet. BBC R&D (web-snippet) cho thấy tốc độ ít ảnh hưởng đến khả năng hiểu, nên quyết định theo hướng ít chặn. |
| X9 | **Freeze gate** | giữ làm gate; dẫn xuất allow + kiểm tra dead-air | spec; RQ-5 | **Allow được dẫn xuất bằng script** (±250 ms) từ holds và khoảng trống VO. Nếu allow > 30% thì freeze chỉ để thông tin. Thêm gate `dead-air`. | G-1 là false positive thuần sổ sách. M-2 là lỗi thật mà gate không thấy. |
| X10 | **SLO** | bội số của độ dài L (RQ-2) hay con số tuyệt đối (EU-6) | — | **Code dùng bội số L** (hard kill), **sản phẩm báo cáo bằng con số tuyệt đối** (mục tiêu). Cả hai tinh chỉnh lại từ `runs.jsonl` sau khoảng 5 lần chạy thật. | Số liệu hiện tại chỉ đến từ benchmark tổng hợp trên một máy dùng chung, và chưa tính thời gian agent [RT-7]. |
| X11 | **Mua hay tự xây** | adopt playwright-recast/Remotion; mua công cụ hẹp | contrarian B1 | **Không adopt framework làm lõi.** Remotion chỉ giữ làm engine motion tuỳ chọn và phải cảnh báo licence. P2 cân nhắc `ffmpeg-normalize` (MIT) và `stable-ts` (MIT). | Licence Remotion yêu cầu Company License khi tổ chức > 3 nhân viên (`remotion@4.0.545 LICENSE.md:18-21`). playwright-recast còn pre-1.0 và chỉ có một tác giả. |
| X12 | **Video nháp ở G2** | chỉ bảng storyboard (hiện tại); nháp không có motion | EU-2 | **Thêm nháp ở P1,** gắn nhãn "DRAFT". Clip raw của nháp được tái dùng ở S4 khi fingerprint không đổi [RT-7]. | Hai vòng làm lại lớn nhất trong example là vấn đề gu, đúng loại mà nháp bắt được. |
| X13 | **Phạm vi platform v0.3** | chỉ web; giữ cả 4 platform | A-arch hỏi mở | **Giữ adapter 4 platform.** Mask lúc quay là mặc định cho web từ P0 và cho Electron từ P0-native. Native theo bậc thang §6.7 từ P1 (snippet T1, T3 sau cờ), T2 X11 ở P2, T2 Android/Windows/macOS ở P3; tất cả gắn nhãn chưa test trên platform thật. iOS cần host Mac; Wayland chỉ có T3/T4. | Không có bằng chứng về tỉ lệ dùng thực tế; xoá platform là quyết định không đảo ngược được. |
| X14 | **Cơ chế mask trên DOM** | (a) bọc text khớp trong `span.ds-mask`; (b) CSS Custom Highlight API; (c) overlay div trong shadow root | draft đầu: (a); red-team: (b)/(c) | **(b) là chính, (c) dự phòng** khi trình duyệt không hỗ trợ Highlight hoặc với vùng cần che cả hộp. Không dùng (a). | Bọc text node làm thay đổi DOM do framework quản lý; React/Vue/Svelte có thể lỗi reconciliation (`removeChild`/`insertBefore`) và chỉ hỏng khi bật mask, đúng trên app thật cần mask nhất [RT-2]. (b)/(c) **(chưa test)**: cần fixture React ở Tier 1. |
| X15 | **Mask Electron** | (a) `addInitScript` như web (posthoc-tracking R9, **suy luận**); (b) main hook `-r` + session preload (desktop) | — | **(b), preload chạy toàn bộ `privacy_mask.js` trong main world** để dùng đúng assertion và gate của web; (a)+reload+cắt pre-roll làm fallback cho bản đóng gói; fuse tắt inspector → đường native | Đo: (a) 324/324 lộ, (b) 0/324 (n=1, biến thể chỉ stylesheet). Biến thể main-world chưa test [RTn-4]. |
| X16 | **Mask lúc quay trên native** | (a) in-app/toolkit cùng frame; (b) overlay hệ thống từ a11y; (c) chỉ hậu kỳ | android A1/A3, apple A1, desktop D-R2/D-R3, posthoc R9 (c cho Windows/macOS) | **(a) khi user sở hữu code hoặc có styling toolkit; (b) có guard cho app bên thứ ba trên X11 (P2) và Android/Windows/macOS (P3); (c)/T4 là sàn** | (a) là cách duy nhất 0 lộ và 0 flicker khi fling (đo-Linux Electron/GTK). (b) đạt 0 lộ **chỉ khi** có pad/guard, primitive cuộn giới hạn tốc độ và handshake guard; công thức pad chưa đo đúng như phát biểu [RTn-1]. iOS không có (b). |
| X17 | **Hậu kỳ cho list cuộn** | (a) CSRT có re-detect (§6.3 rev 1); (b) still-window + cover container (apple A3); (c) scroll-offset propagation + mosaic OCR (posthoc R1–R4) | — | **(c) là chính (P1, sau cờ); (b) là sàn khi offset không ước lượng được và là nguồn cho tên; (a) cấm cho list** | (c) che 0.09–0.20 frame và lộ 0 loại khớp regex; (b) che 0.85–0.97 container, lộ 0 (đều mô phỏng). "track" của apple lộ vì không biết chính xác thời điểm snapshot được chụp; (c) tránh được vì chỉ dùng snapshot tĩnh, đổi sang toạ độ nội dung. |
| X18 | **Phạm vi quay trên macOS/Windows** | chỉ cửa sổ (apple M1; `desktop.md:44`) hay display/vùng (desktop D-R3/D-R7) | — | **Theo tầng:** chỉ-cửa-sổ khi T1/T3 (loại chrome, không cần overlay; macOS cần `ds-sck-record`, P3); display/vùng **bắt buộc** khi T2. Trước P3, macOS quay display + cover ngoài cửa sổ (H⁻) | Quay chỉ-cửa-sổ loại luôn cửa sổ overlay (**suy luận**). Hình thử màu ở dry run cho mọi platform để phát hiện. |
| X19 | **Recorder Android** | scrcpy hay `adb screenrecord` | android A5, posthoc R9 | **scrcpy mặc định** (`--no-playback --no-control --no-audio --capture-orientation=0@`, không `--max-size` khi T3); screenrecord chỉ là fallback | screenrecord giới hạn 180 s và không hỗ trợ xoay (docs). Khoá orientation làm rect a11y lệch khi app xoay → `transform` [RTn-12]. |
| X20 | **Tên và PII không khớp regex** | regex-only, alltext, hay a11y seed | posthoc R8 | **Mặc định regex + a11y seed khi tĩnh hoặc cột user chỉ định; alltext chỉ khi không có cả hai** | alltext che tên về 0 nhưng mask tăng lên 0.27–0.36 frame. |
| X21 | **Ship code mask cho app** | (a) thư viện/APK/Swift package do plugin bảo trì; (b) snippet copy-paste trong references | android/apple open questions | **(b) ở P1; (a) chỉ sau khi xác thực trên thiết bị thật (P3)** | Chi phí bảo trì chưa rõ; chưa có lần chạy nào trên thiết bị. Trước khi quyết, bảng §6.7.2 ghi chi phí là "copy snippet", không phải "1 dòng Gradle" [RTn-3]. **Quyết định sản phẩm, cần chủ repo xác nhận.** |

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
| `blur.py verify` | `--video F --slug S --aspect A [--budget-s 300] [--fullframe-stride-s 2]` | budget 120 s (seeded/không vùng) / 300 s (real), cho mỗi output; non-web `max(300, 1.5 × estimate)` (§6.7.4) | Một decode PyAV cho mỗi output. Sample ROI mỗi 0.5 s, cộng first/last, cộng mọi frame trong đoạn chuyển động. Gộp ROI thành montage. Với `real-redacted` (web): thêm full-frame regex OCR mỗi `stride` giây, chia chung budget. Non-web: det-only + change gate (§6.7.4). RapidOCR chạy trong worker subprocess với `Det.limit_type=max, limit_side_len=960`, model chọn theo `language` (R7), worker in heartbeat jsonl. Hit chỉ ghi `region, t_ms, match_len` và tuỳ chọn `hmac` (khoá ngẫu nhiên theo project, lưu ở `.demo/<slug>/.secret/key`, ngoài `project.json`, trong `.gitignore`) [RT-6]. |
| `checks.py` | `--slug S [--only …] --json`; `checks.py dod <stage>` | 0.3×L + 60 s | Một pass ffmpeg kết hợp ebur128 + blackdetect + freezedetect + silencedetect (8.1 s so với 22 s chạy riêng [exp: RQ E5]). Gồm lint VTT, drift, loudness so với cả target và `#mix.preview`, dead-air, allow dẫn xuất. Là **nơi duy nhất** ghi `#checks`, qua code path riêng của `project.py` (§4.3). |
| `timeline.py`, `captions.py`, `mix.py`, `render.py`, `package.py` | `--slug S [--scenes s03,…]` | timeline 30 s; mix 0.5×L; render 3×L (mỗi tỉ lệ thêm 2×L), stall 30 s | P1/P2. `--scenes` cho phép render lại một phần rồi re-concat (§5, revoice/rerecord). `package.py` loại `media/preview/`, `.secret/` và raw clip khỏi delivery. |
| `demo.py` | `status --json`, `next --json`, `run <stage> [--scenes …]`, `fail <stage> --finding ID`, `accept <check> <span>`, `brief <stage>`, `migrate` | — | State machine. Bảng `STAGES` chứa kind, inputs, outputs, owner, `timeout_s`, `max_attempts`, `tool_feature`. Mở rộng từ `project.py:37-63` (`OWNERS`, `DOWNSTREAM`, `RUN_ORDER`). |

**Bổ sung cho non-web (§6.7):**
- **`capture.py`: thêm** `--platform electron|tauri|android|ios|macos|windows|linux` (đọc từ `demo.yaml`) và `--tier`.
  - Lúc khởi động: `os_hygiene status` và khôi phục mọi entry còn treo trong `hygiene.json` [RTn-13].
  - Trước khi quay: armed assertion theo §6.7.5, vệ sinh OS (enter), dry-run probe (cờ tự che của app, hình thử màu đúng rect, TCC không tương tác, status bar, fuse Electron).
  - Sau khi quay: `blur.py timebase`, ghi `#events.clips.<sid>` với `tier`, `timebase`, `transform`, `container_roi`, `a11y_snapshots`, `hygiene`.
  - Khôi phục vệ sinh OS trong `finally`. Dừng recorder: SIGINT → 10 s → KILL → ffprobe.
  - Fingerprint `--reuse-draft` cho non-web thêm `tier`, thiết bị + version OS, hash mask kit, hash timebase (§6.7.8).
- **Thêm** `blur.py timebase` (P0-native) và `blur.py track` (P1, sau cờ), spec ở §6.7.4; mở rộng `plan`, `graph` (`--space source`, theo `t`), `verify` (change gate, det-only).
- **Thêm** `scripts/os_hygiene.py enter|exit|status --platform …`, timeout 30 s, idempotent, lưu giá trị cũ vào `.demo/<slug>/hygiene.json`. Mỗi lệnh adb/xcrun chạy qua `run_bounded`.
- **Thêm** helper `ds.scroll()` và `guard.arm/disarm` trong adapter `platform-automation`, cùng lint chặn swipe/fling trần khi T2 bật (§6.7.3).
- **Thêm (P2)** `scripts/overlay_mask.py` (X11, dựa trên prototype `overlay.py` đã đo): công thức pad và guard, input shape rỗng, sự kiện cửa sổ mới, log `mask.jsonl`, heartbeat jsonl, fail-closed khi poll lỗi.
- **Thêm** `assets/mask-kits/`:
  - `electron/mask_hook.js` + `mask_preload.js` (P0-native; biến thể stylesheet đã đo, biến thể main-world chưa test);
  - `gtk/gtk.css.tmpl` (P2, đã đo);
  - `android/` (snippet debug, Compose modifier, `<DemoMask>` cho RN, `DemoMask` cho Flutter) và `apple/` (snippet SwiftUI/UIKit lớp đục + log, `WKUserScript`), đều P1.

  Mọi snippet native gắn nhãn chưa test trên platform thật.
- **Thêm (P3, chưa test)** helper Swift `ds-sck-record` cho macOS, helper APK accessibility cho Android, overlay UIA cho Windows.
- **Timeout:** `timebase` 30 s + 0.5×dur; `track` theo `--budget-s` (mặc định `max(60, 1.5 × estimate)`); `verify` non-web `max(300, 1.5 × estimate)`; `os_hygiene` 30 s; page-source ≤ 15 s; `accessibilityDeadline` 3 s; TCC preflight ≤ 10 s; build WDA ≤ 600 s; tìm pid webview ≤ 10 s.

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
- Thêm mục "Privacy" vào `platform-automation`: masking cho web (gồm input, tooltip, SVG) và cảnh báo **không** dùng `FLAG_SECURE` vì nó làm đen cả cửa sổ (Sauce Labs, web-snippet). Phần non-web của mục này là tham chiếu tới §6.7 (bậc thang tầng, vệ sinh OS, primitive cuộn).
- Sửa `desktop.md:44`: bỏ `gdigrab title=` khi dùng T2; sửa `desktop.md:13-23`: Electron dùng mask kit, không dùng `addInitScript` sau launch.
- Sửa `mobile.md`: dùng pts thay cho CFR khi tính thời gian; thay dòng DND bằng chuỗi lệnh SystemUI, `set_dnd none`, bàn phím/autofill/clipboard và bước khôi phục (§6.7.6).
- Thêm `references/ios.md`, `macos.md` (TCC, Retina point→pixel, `accessibilityDeadline`) và mục WebView/CDP, Tauri, mobile web.

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

Non-web thêm (§6.7):
- `events.clips.<sid>`: `tier`, `timebase`, `transform:{src_size, clip_size, scale, rotation, offset, crop}`, `container_roi`, `track`, `hygiene:{entered, restored}`, `mask_ready_t`.
- `checks.blur.<aspect>`: `mask_area_frac`, `failclosed`.
- `.demo/<slug>/hygiene.json`: giá trị OS cũ theo thiết bị, để khôi phục sau crash.
- `demo.yaml`: `privacy.platform.{tier, fallback, pii_classes, max_mask_area, device, track}`.

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
| S3 Draft | script | TTS + `capture.py --all` (có mask) + caption burn + encode veryfast + contact sheet 1 fps | mục tiêu (chưa đo) ≤ 10 phút từ G1, gồm cả S2 | Nháp phát được; `checks.privacy_capture.frames_unmasked = 0`. Non-web: dry-run probe pass (không tự che, hình thử màu đúng rect, status bar sạch), `armed` đúng tầng | Capture fail thì retry env ≤ 2, sau đó route về scene-automator. Probe fail → `blocked` có lý do, không retry |
| **G2** | gate | — | — | User duyệt **video nháp** + script. Lexicon đã nằm trong audio nháp. | Phản hồi kiểu "quá nhanh" hay "thiếu nội dung" quay về S2a; đổi ngôn ngữ thì localizer chạy và nháp dựng lại |
| S4 Capture final | `capture.py --reuse-draft` | → `raw/*.webm`, `#events` | 3×scene + 30 s, chỉ cho scene stale | Mọi clip probe được; marker ≥ số mark; mọi rect đã log khớp frame (§6.4) | Exit ≠ 0 thì route theo bảng exit code |
| S5 Privacy fallback | script `blur.py plan|preview` (chỉ khi có `unmaskable`, clip `masked:false`, hoặc có vùng non-web ở tầng < T1 → `blur.py track` cho container cuộn hoặc `plan --positions/--a11y`; non-web burn vào `masked/<sid>.mp4`) | → `#blur` | plan 30 s + preview 30 s; `track` theo §6.7.4, exit 3 → block | Schema hợp lệ; mỗi vùng có positive control và contact sheet (đã che) | `needs-input` gửi cho director |
| S6 Timeline/motion/captions/mix | script (+ override từ `editor`) | → `#timeline`, `#motion`, `#captions`, `#mix` | timeline 30 s; mix 0.5×L | Allow spans được dẫn xuất; VTT lint pass | — |
| S7 Render | script `render.py` (nhúng `blur.py graph` theo từng aspect) | → `final-*.mp4` | 3×L + 2×L cho mỗi tỉ lệ thêm, stall 30 s | Thời lượng khớp `#timeline` ±40 ms | Exit 124/125 thì retry 1 lần, sau đó hỏi user |
| S8 Checks | script `checks.py` + `blur.py verify` cho **mỗi** output | → `#checks` | 0.3×L + 60 s; verify ≤ 120 s (seeded) / 300 s (real) mỗi output; non-web theo ước tính (§6.7.4) | Tất cả check blocking pass. Không vùng nào `inconclusive` mà chưa được người xác nhận. | Exit 3 nghĩa là incomplete: **block**, không pass âm thầm. Exit 11: block delivery |
| S9 QA | agent `demo-qa` | contact sheet + `#checks` → `qa.md` | `maxTurns` 25 | Finding có owner và mức (blocking/advisory) | — |
| **G3** | gate | — | — | File final, contact sheet đã che, "Blocking: none / Optional: N" bằng ngôn ngữ thường. Không hiện bảng JSON, không hiện crop raw. | — |
| S10 Package | script | → `delivery` | 60 s | Có đủ file cho mọi kênh trong preset; không chứa `media/preview/`, `.secret/`, raw | Xoá raw theo `privacy.raw_retention` |

**Luồng sửa theo scene** (`/revoice`, `/rerecord`) [RT-9]: `demo.py run voice --scenes s03` hoặc `demo.py run capture --scenes s03` → `render.py --scenes s03` render lại đoạn đó và re-concat → `checks.py` + `blur.py verify` trên output mới → contact sheet so sánh trước/sau cho scene đó. Mục tiêu revoice ≤ 5 phút và rerecord ≤ 10 phút chỉ có hiệu lực khi cơ chế `--scenes` đã có (P2); trước đó là chạy lại toàn bộ downstream. Non-web: rerecord chạy đủ adapter capture, và mọi retime/reframe đọc từ clip đã che (§6.7.8).

**Mục tiêu sản phẩm (chưa đo, chốt sau baseline P0 có tính thời gian agent):**
- Từ G1 đến nháp: ≤ 10 phút.
- Từ G2 đến bản final: ≤ 20 phút.
- Toàn bộ hậu kỳ sau capture: ≤ 10×L.
- Revoice một scene: ≤ 5 phút. Rerecord một scene: ≤ 10 phút (từ P2).
- Sửa chỉ caption hoặc motion: ≤ 3 phút, không OCR lại phần không đổi.
- Non-web: `track` hậu kỳ ≤ 1.5×L (mục tiêu; đo 6.7–17.8 s cho clip tổng hợp 12 s, mô phỏng).

**Capture theo platform (S3/S4, non-web)** [§6.7]:

| Platform | Chuỗi bước |
|---|---|
| Electron | probe fuse → hook + `privacy_mask.js` main world → assertion như web → `recordVideo` |
| Android | khôi phục hygiene treo → hygiene enter → `armed` (T1/T2) hoặc CDP (hybrid, mobile web) → scrcpy → `timebase` (stamp) |
| iOS | hygiene/cover status bar → `DS_PRIVACY_MASK` (T1, có log) → `simctl recordVideo --codec=h264` (simulator) hoặc `startXCTestScreenRecording` (máy thật) → snapshot có giới hạn, ghi `t_req/t_done` |
| macOS | TCC preflight không tương tác → trước P3: `avfoundation` display + cover ngoài cửa sổ (H⁻); từ P3: `ds-sck-record` chỉ-cửa-sổ (T1/T3) hoặc SCK display (T2) |
| Windows | DPI PMv2, cửa sổ cố định trong work area → (P3) overlay UIA → `ddagrab`/`gdigrab` vùng |
| Linux X11 | (P2) gtk.css hoặc overlay → `x11grab` vùng |

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

Thứ tự nguồn dữ liệu cho non-web: **xem §6.7.2–6.7.3** (thay cho 4 bước của rev 1; bbox a11y tĩnh chỉ dùng trong still-window, CSRT bị cấm cho container cuộn, D18). Phần `plan`/`graph` dưới đây vẫn áp cho mọi platform, với mở rộng ở §6.7.4: timing theo `t` (pts), không theo `n`.

`blur.py plan`:
- Gộp vùng trùng (b1–b10 trở thành 1 vùng nhiều span) khi lập plan mới.
- Tách segment ở mọi chỗ nhảy > `pad`. Keyframe nhảy mà không tách thì exit 2.
- Dải mỏng như b15–b17 được giữ dưới dạng vùng `cover` (`drawbox t=fill`), chi phí gần bằng 0 [RT-15].
- Clip `masked:false` (gồm mọi clip cũ) giữ toàn bộ vùng hiện có.

`blur.py graph`:
- `crop,boxblur=lr=ceil(h/4):lp=1:enable='…'` với `enable` trên **cả** blur và overlay.
- Secret và vùng cover dùng `drawbox=…:t=fill`.
- Vùng chuyển động dùng `sendcmd` theo timestamp pts của từng frame (khoảng 270 fps trong graph, nhanh hơn vòng OpenCV ngoài ở 168 fps [exp: media-perf c]).

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
- Với `real-redacted` trên web: thêm full-frame regex OCR mỗi `stride` giây (mặc định 2 s); non-web chọn frame theo change gate và budget theo ước tính (xem phần bổ sung bên dưới), để bắt PII không có marker (vai trò của `privacy-blurrer` bước 4 cũ). Pass này dùng chung budget; hết budget thì exit 3.
- OCR chạy trong worker subprocess, in heartbeat jsonl, bị kill khi stall.
- Bắt buộc positive control. Positive control fail thì verdict là `inconclusive`.
- Hit OCR thì exit 11. Không có hit thì ghi "not-machine-readable"; contact sheet đã che đi kèm cho người duyệt.
- Kết quả được ghi vào `#checks.blur.<aspect>`. `privacy-blurrer` không chạy sweep; `demo-qa` không chạy OCR lại.

**Bổ sung cho non-web** (chi tiết §6.7.4):
- Regex chịu được lỗi OCR (`_` thành dấu cách) và pad crop `h ≥ max(64, w/4)` [exp2: posthoc-tracking B2].
- Full-frame dùng det-only + rec trên box, frame chọn theo change gate (mọi sự kiện overlay có ≥ 1 frame OCR), budget `max(300, 1.5 × estimate)` thay cho stride 2 s và 300 s cố định.
- `--mask-log` cho T1/T2 có log, kiểm như gate `privacy_capture`.
- Luôn báo `mask_area_frac`.

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

| | Hiện tại (example) | Đích, web `seeded` | Đích, web `real-redacted` | Đích, non-web T1 | Đích, non-web T3 |
|---|---|---|---|---|---|
| Vùng blur hậu kỳ | 17 | 0 | 0 (+ unmaskable) | 0 (+ cover chrome OS nếu cần) | vùng `track` theo frame + cover, burn vào clip source |
| Số lần OCR | 2–3 pass, 108 sample mỗi pass | 0 | 1 pass bounded mỗi output, có full-frame thưa | 1 pass bounded mỗi output, change gate | 1 OCR mosaic + sự kiện, rồi 1 verify bounded mỗi output |
| Drift kiểu M-1 | có | không xảy ra với phần tử được che (mask đi theo DOM) | như bên trái | không (mask cùng frame) | vị trí theo pixel của frame, fail-closed qua residual |
| Treo | có thể | timeout cứng | timeout cứng | timeout cứng | timeout cứng, budget theo ước tính |

### 6.7 Desktop & mobile: privacy và capture

> Phần này mở rộng cho non-web các nguyên tắc ở §1 và §6.2: che ngay lúc quay là mặc định, vị trí phải chính xác theo từng frame, fail-closed, và mọi bước đều có giới hạn thời gian. Với non-web, nó **thay thế** thứ tự nguồn ở §6.3 và thứ tự ưu tiên ở §1.6/X6; phần web giữ nguyên. Nội dung tổng hợp từ 4 báo cáo chuyên gia mới (`android`, `apple`, `desktop`, `posthoc-tracking`) và một vòng red-team riêng (Phụ lục A, bảng "Phản biện desktop/mobile", ký hiệu `[RTn-k]`). Thí nghiệm nằm ở `scratchpad/exp2/<id>/`, là thư mục tạm; các số liệu then chốt đã chép vào đây, và generator + script đo được commit ở P0-native (§8) [RTn-18].
>
> **Giới hạn bằng chứng, cần đọc trước:**
> - Container không có `/dev/kvm`, CPU không có cờ vmx/svm, và proxy trả HTTP 403 cho `dl.google.com`. Vì vậy không chạy được Android emulator.
> - Không có máy Apple, Windows hay thiết bị thật nào.
> - Số liệu "đo" chỉ có cho Electron và GTK3 trên Linux/Xvfb/X11 (không compositor), cùng các clip tổng hợp do ffmpeg/OpenCV sinh ra. Hầu hết cấu hình chỉ chạy **1 lần**; số run được ghi ở từng ô.
> - Mọi hành vi trên Android, iOS, macOS và Windows được ghi **(chưa test trên platform thật)**.
>
> Nhãn trạng thái dùng trong bảng:
> - **đo-Linux (n=k)**: thí nghiệm thật trên Xvfb/X11, k lần chạy.
> - **mô phỏng**: hình học số hoặc clip tổng hợp. "mô phỏng hình học" mà kết quả 0 do cách dựng (mask trùng rect nội dung) **không** được tính là bằng chứng.
> - **chưa test**: chưa có thí nghiệm nào.
>
> Cột **"Có từ"** ở §6.7.2 cho biết tầng đó có sẵn từ phase nào (§8). G1 **chỉ** đưa ra các tầng đã có trong version đang cài [RTn-3].

#### 6.7.1 Nguyên tắc chung (rút ra từ đo đạc)

1. **Chỉ có mask vẽ trong cùng frame với nội dung mới vừa không lộ vừa không nhấp nháy khi cuộn hoặc fling.** "Cùng frame" ở đây nghĩa là mask nằm trong process của app, trong toolkit hoặc trong compositor của WebView. Bằng chứng đo được:
   - Electron qua hook: 0/324 frame lộ [exp2: desktop D1c] (đo-Linux, n=1).
   - GTK user CSS: 0/350 [exp2: desktop D2] (đo-Linux, n=1).

   Android in-app (E2 S0: 0/360, flicker 0, overmask 1.01) là **mô phỏng hình học**: mask được dựng trùng rect nội dung nên 0 là hiển nhiên, không phải bằng chứng; thư viện tương ứng chưa được viết [RTn-2].
2. **Mask đặt từ bên ngoài app luôn trễ ít nhất 1 frame.** Đây là trường hợp overlay đọc vị trí từ accessibility, hoặc hộp hậu kỳ có sai lệch đồng hồ. Nếu không có guard thì lộ gần như mọi frame đang chuyển động:
   - Overlay AT-SPI 25 Hz không pad: 181/325 [desktop D3] (đo-Linux, n=1).
   - Android overlay: 207–219/360 frame lộ, tối đa 61 px [android E2 S1] (mô phỏng).
   - Hộp hậu kỳ có vị trí chính xác nhưng lệch đồng hồ 8 ms: 200/360 frame lộ ở pad 0, vẫn còn 12 ở pad 64 [android E4] (mô phỏng).
3. **Cấm hold, lerp và CSRT/KCF cho container cuộn.**
   - Giữ hoặc nội suy giữa các a11y snapshot thưa lộ 1440–3099/9807 sample [apple E1] và 3242–5106/18574 item-frame [posthoc-tracking A3].
   - KCF mất cả 28 item ở frame 61, tức frame fling đầu tiên. CSRT tốn 26.3 ms cho mỗi lần cập nhật một item (khoảng 1.5 fps với 25 item) và mất 13/28 item [posthoc-tracking A5].
   - Tracker không phát hiện được dòng mới cuộn vào khung hình.
4. **Mọi thời gian tính theo PTS của từng frame, không bao giờ theo `index/fps`.** scrcpy và screenrecord ra VFR.
   - Map theo index lệch tới 2433 ms (median 1267 ms) [android E3].
   - Cùng một bộ mask đặt theo index thì lộ 2286/3894 item-frame email; đặt theo pts thì lộ 0 [posthoc-tracking C1].
5. **Mọi rect đi qua một hàm biến đổi duy nhất sang toạ độ pixel của clip** (scale, xoay, offset, crop), lưu ở `events.clips.<sid>.transform` [RTn-12]. Nguồn rect (AX point, UIA có toạ độ âm ở màn hình phụ, a11y Android theo toạ độ display khi scrcpy khoá orientation, crop status bar hay device frame) không bao giờ được dùng trực tiếp.
6. **Không dùng content-protection làm cơ chế privacy.** Thuộc các nhóm sau: `FLAG_SECURE`, `setContentSensitivity`, `WDA_EXCLUDEFROMCAPTURE`, `setContentProtection` của Electron, `NSWindow.sharingType = .none`.
   - Các cơ chế này làm đen hoặc loại **cả cửa sổ** khỏi bản quay.
   - Nếu đặt nhầm lên cửa sổ mask, mask biến mất khỏi bản quay và PII lộ ra [android/A8] [desktop/D-R6] (web-snippet + tài liệu chính thức).
7. **Ghi hình phải bắt đầu sau khi mask sẵn sàng.** Frame 12, chụp trước khi overlay sẵn sàng, bị OCR đọc ra `fake@` [desktop D3].
8. **PII không chỉ nằm trong app.** Bàn phím, autofill, clipboard, notification và recents của OS cũng hiện dữ liệu; chúng do vệ sinh OS (§6.7.6) xử lý, không phải mask của app [RTn-5].

#### 6.7.2 Bậc thang theo platform

Mọi platform dùng chung các tầng sau:
- **T0**: chính sách dữ liệu (§6.1), luôn áp dụng.
- **T1**: mask cùng frame lúc quay.
- **T2**: overlay lúc quay, lấy vị trí từ accessibility, có guard.
- **T3**: hậu kỳ bằng `blur.py track`, hoặc dùng log vị trí chính xác.
- **T4**: cover tĩnh cả panel, container hoặc vùng. Đây là sàn fail-closed: luôn an toàn, nhưng mất nội dung.

Cách chọn:
- Chọn tầng cao nhất **đã có trong version đang cài** và áp dụng được cho **từng vùng**; nhiều tầng có thể kết hợp trong một scene. `setup_tools --plan` in ma trận `available_tiers` theo platform; G1 chỉ hỏi trong ma trận đó.
- Vệ sinh OS (H, §6.7.6) luôn chạy; nó làm sạch chrome và các bề mặt PII của OS, không che nội dung app.
- Mỗi output kết thúc bằng một lần `blur.py verify` (§6.4, §6.7.4), có full-frame regex OCR cho mọi clip non-web.
- Một màn hình, scale cố định khi dùng T2 (probe kiểm). Multi-window/split view/Stage Manager: cấm, hoặc T4 phủ pane của app khác.

| Platform | Tầng | Cơ chế | Khi nào dùng | Chi phí setup cho user | Có từ | Trạng thái |
|---|---|---|---|---|---|---|
| **Electron** | T1 | Main-process hook: `electron.launch({args:['-r', mask_hook.js, main.js]})`. Hook gọi `session-created` → `setPreloads([...,mask_preload.js])`. Preload chạy **toàn bộ** `privacy_mask.js` (§6.2: highlight, input `.value`, thuộc tính, SVG) trong main world qua `webFrame.executeJavaScript`, để Electron dùng đúng thiết kế web, cùng assertion (highlight đã đăng ký + computed style, đọc bằng `page.evaluate` ở main world) và cùng log rect rAF, nên gate `privacy_capture` (§6.4) áp nguyên [desktop/D-R1] [RTn-4] | App dev/unpackaged, hoặc bản đóng gói còn bật fuse inspector. Probe đọc fuse (`npx @electron/fuses read --app <path>`) trước G1 | ≈ 0 (đã cần electron + playwright) | P0-native | Biến thể chỉ có stylesheet qua `adoptedStyleSheets`: **đo-Linux (n=1)** 0/324 frame, OCR 0/27. Đối chứng `addInitScript` sau launch: `masked:false`, lộ 324/324. Biến thể main-world đầy đủ: chưa test |
| Electron | T1' | Bản đóng gói không nhận `-r`: `app.context().addInitScript(MASK)` + `firstWindow().reload()` + cắt pre-roll trước `scene_start` | Packaged app còn cho Playwright điều khiển | ≈ 0 | P0-native | **đo-Linux (n=1)**: 0/324. Phụ thuộc timing; cần ≥ 5 run mới tin được |
| Electron | → native | Fuse tắt inspector/RunAsNode (mặc định của template Forge) thì Playwright không điều khiển được app; đây là trường hợp phổ biến với app Electron bên thứ ba | — | — | — | Đi theo hàng Windows/macOS/Linux bên dưới |
| **Tauri** | T1 | Có source: thêm `privacy_mask.js` làm initialization script của webview khi build demo (mọi OS). Không có source, trên Windows: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=…` → CDP → inject như web. macOS/Linux không có source: theo hàng WKWebView/WebKitGTK, tức T3/T4 [RTn-11] | App Tauri | Sửa build (có source) hoặc 1 biến môi trường (WebView2) | P1 | chưa test |
| **Windows** (native) | T1 | Cờ `DEMO_MASK` trong app (WPF/WinUI) do user tự thêm, theo snippet trong references [desktop/D-R2] | User sở hữu code | Sửa code một lần, khoảng 10–30 dòng (**suy luận**) + rebuild | P1 (snippet) | chưa test |
| Windows | T2 | Overlay `WS_EX_LAYERED\|TRANSPARENT\|TOPMOST\|TOOLWINDOW\|NOACTIVATE`. Vị trí từ UIA `CurrentBoundingRectangle`: resolve phần tử một lần rồi poll (comtypes/uiautomation, không gọi `child_window()` mỗi tick), đăng ký UIA `WindowOpened`/`StructureChanged` cho cửa sổ mới. Pad và guard theo §6.7.3. Phải quay **cả vùng hoặc cả màn hình** (`ddagrab` hoặc `gdigrab` desktop có offset/size), **không bao giờ** `gdigrab title=` [desktop/D-R3,D-R7] | App bên thứ ba | Process DPI-aware Per-Monitor-V2; package comtypes/uiautomation; không cần admin (**suy luận**) | P3 | chưa test trên platform thật (chưa có số latency UIA; pywinauto có báo cáo ≥ 30 s khi tìm `top_window`, web-snippet). Chưa rõ `gdigrab` có bắt cửa sổ `WS_EX_LAYERED` hay không (CAPTUREBLT), nên hình thử màu là bắt buộc với cả hai recorder [RTn-19] |
| Windows | T3/T4 | `blur.py track` (§6.7.4); cover panel | Phần còn lại | — | T3: P1; T4: P0-native | T3 **mô phỏng**; T4 đo-Linux (overlay tĩnh 0/349, n=1) |
| **macOS** (native) | H | ScreenCaptureKit **chỉ quay cửa sổ**: `SCContentFilter(desktopIndependentWindow:)`, chạy qua helper `ds-sck-record` khoảng 150 dòng Swift. Helper ghi sidecar JSONL theo frame (`displayTime, contentRect, scaleFactor, dirtyRects`). Notification, app khác, menu bar và desktop không bao giờ vào frame [apple/M1] | Mặc định từ P3 khi **không** dùng T2 | Xcode CLT để build helper; cấp quyền TCC Screen Recording; Sequoia được báo là hỏi lại hằng tháng (web-snippet) | P3 | chưa test |
| macOS | H⁻ | **Mặc định trước P3:** ffmpeg `avfoundation` quay display, ẩn Dock/menu-bar extras, cover đục phần ngoài cửa sổ app (T4 theo rect cửa sổ, qua `transform`), cộng T3/T4 cho nội dung [RTn-3] | Mọi app macOS trước P3 | TCC Screen Recording cho terminal/ffmpeg | P1 | chưa test |
| macOS | T1 | SwiftUI/AppKit: khi `DS_PRIVACY_MASK=1`, snippet phủ **lớp đục** lên view có `.privacySensitive()` hoặc accessibilityIdentifier mang prefix. `.redacted(reason:.privacy)` chỉ cho mục ít nhạy cảm, vì placeholder giữ độ dài và hình dạng text. Snippet **phải** ghi log (`os_log` hoặc file do launch arg chỉ định) gồm `n_rules/n_matched` và rect các vùng che ≥ 1 lần/s. Truyền cờ qua `appium:arguments`/`appium:environment` (Mac2) [apple/A1] [RTn-14] | User sở hữu code | Sửa code khoảng 40–80 dòng + rebuild | P1 (snippet) | chưa test (API có thật theo DocC; hiệu ứng trên màn hình là **suy luận**) |
| macOS | T2 | Overlay `NSWindow` borderless ở level cao, `ignoresMouseEvents`. Vị trí từ AX/Mac2. Phải quay `SCContentFilter(display:excludingWindows:)` để overlay **có** trong frame (xung đột với H "chỉ cửa sổ") [desktop/D-R3,D-R7] | App bên thứ ba | TCC Accessibility (cấp cho WebDriverAgentRunner, mất sau mỗi lần rebuild ad-hoc nếu không ký) + Screen Recording | P3 | chưa test |
| macOS | T3 | Rect AX tính bằng point → pixel qua `transform` (gốc cửa sổ, `scaleFactor` của **display chứa cửa sổ**; cửa sổ trải qua 2 display có scale khác nhau → cover). Quy tắc still-window (§6.7.3). `dirtyRects` có thể thay change gate (**suy luận**) [apple/A3,M2] | Phần còn lại | Appium + Mac2 | P1 | mô phỏng |
| **Linux** (X11) | T1 | GTK3: user CSS `$XDG_CONFIG_HOME/gtk-3.0/gtk.css` (ví dụ `label.pii{background-color:#333;color:transparent}`), chạy với `XDG_CONFIG_HOME` trỏ vào thư mục tạm. Không đổi code app. Qt: `-stylesheet`/QSS [desktop/D-R2] | Widget nhạy cảm có class/name ổn định | 0 | P2 (P1 nếu chủ repo xác nhận nhu cầu, R29) | GTK **đo-Linux (n=1)**: 0/350, OCR 0/30. Qt chưa test |
| Linux | T2 | Cửa sổ override-redirect (GTK POPUP) với **input shape rỗng** (`input_shape_combine_region(cairo.Region())`) để click xuyên qua. Vị trí từ AT-SPI `getExtents`, poll 25 Hz; đăng ký `window:create` và `object:children-changed`. Quay `x11grab` theo vùng [desktop/D-R3] [RTn-6] | App bên thứ ba có a11y tree | apt `at-spi2-core python3-pyatspi gir1.2-gtk-3.0`; X11 | P2 (như trên) | **đo-Linux (n=1 mỗi cấu hình, Xvfb không compositor, app GTK tổng hợp tự cuộn, không click)**: 0 frame lộ với pad24+guard40 ở 360 px/s và pad64+guard80 ở 1200 px/s. Công thức pad ở §6.7.3 **chưa** được đo đúng như phát biểu [RTn-1] |
| Linux | — | **Wayland: ngoài phạm vi T1/T2.** Không có overlay toàn cục, không có hình học a11y tin cậy | — | — | — | Chỉ T3/T4; báo rõ cho user |
| **Java/Compose desktop, Swing, JavaFX** | T3/T4 | Hậu kỳ hoặc cover. T2 qua a11y bridge (Java Access Bridge trên Windows, AT-SPI bridge trên Linux) **chỉ** sau P3 [RTn-11] | App JVM | — | T3: P1; T2: P3 | chưa test |
| **Android native** (View/Compose) | T1 | Snippet debug-only (copy vào module `debug`/`demo` của app; thư viện chính thức chỉ có nếu X21 quyết sau P3). Mỗi frame (`OnPreDrawListener` + vẽ overlay trên decor root) phủ rect đục lên view khớp rule trong một file JSON: tag `demo-mask`, class (EditText có inputType password/email), regex trên text của TextView. Compose dùng `Modifier.demoMask()` + rule theo semantics. Helper báo `armed:{n_rules,n_matched}` và rect qua logcat [android/A1] | User sở hữu code và build được bản debug/demo | Copy snippet (vài file Kotlin; số file chốt ở P1) + đăng ký trong Gradle + rebuild; user tự bảo trì đoạn copy cho tới khi X21 quyết [RTn-3] | P1 (snippet) | **mô phỏng hình học** (0 do cách dựng, không phải bằng chứng). Snippet chưa viết, chưa test trên platform thật |
| Android native | T2 | Helper APK có AccessibilityService vẽ `TYPE_ACCESSIBILITY_OVERLAY` (cửa sổ trusted nên touch vẫn đi xuyên qua; `TYPE_APPLICATION_OVERLAY` > 0.8 opacity sẽ chặn touch trên Android 12+). Bật service: `adb shell settings put secure enabled_accessibility_services …` + `appium:disableSuppressAccessibilityService: true`. **Bắt buộc có scroll guard** theo handshake ở §6.7.3 [android/A3] [RTn-7] | Bản release, app bên thứ ba | `adb install` + bật service; Android 13+ có thể cần bấm tay "allow restricted settings", khoảng 5–10 phút mỗi thiết bị | P3 (helper APK) | **mô phỏng**: có guard 0 lộ, overmask 2.33; overlay có pad theo vận tốc vẫn lộ 39 frame. Chưa test trên platform thật |
| Android native | T3 | `blur.py track` trên clip scrcpy; hoặc log vị trí theo frame từ T1/T2 đồng bộ bằng stamp + pts [android/A5,A6] [posthoc-tracking/R1–R8]. Cấm `scrcpy --max-size` khi dùng T3 (scale lẻ làm offset không nguyên), trừ khi pad ≥ 6 px [RTn-12] | Clip không có T1/T2, vùng không che được, belt-and-braces | adb + scrcpy | P1 (cờ `track`) | mô phỏng |
| **Android hybrid / WebView** | T1 | CDP: `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>` (tìm pid ≤ 10 s) → `chromium.connectOverCDP` → inject `privacy_mask.js` bằng `Page.addScriptToEvaluateOnNewDocument` + evaluate một lần trong document hiện tại. Áp cho Capacitor, Cordova, react-native-webview [android/A2] | App gọi `WebView.setWebContentsDebuggingEnabled(true)`, mặc định tắt và không theo cờ debuggable | Sửa một dòng trong bản debug + adb forward (vài phút) | P1 | chưa test. Phần native bao quanh WebView vẫn cần T1/T2/T3 |
| **Mobile web** (Chrome Android, Safari iOS) | T1 | Chrome: `adb forward … localabstract:chrome_devtools_remote` → CDP → `privacy_mask.js` như web. Safari: Appium web context, inject sau mỗi navigate + cover rect webview tới khi `window.__dsMaskReady === true`. Chrome UI (thanh địa chỉ, gợi ý) thuộc vệ sinh OS [RTn-11] | Demo trang web trên điện thoại | adb, hoặc Mac + Appium | P1 | chưa test |
| **iOS native** | T1 | Giống macOS T1 (lớp đục + log bắt buộc): `DS_PRIVACY_MASK` truyền qua `appium:processArguments {args, env}`. UIKit dùng helper phủ subview [apple/A1] [RTn-14] | User sở hữu code | Sửa code khoảng 40–80 dòng + rebuild. **Bắt buộc có Mac + Xcode**; host Linux/Windows trả `blocked` | P1 (snippet) | chưa test |
| iOS native | T2 | **Không có.** Không có cơ chế overlay hệ thống tương đương | — | — | — | — |
| iOS native | T3 | Rect a11y từ XCUITest chỉ dùng khi màn hình đứng yên (still-window, §6.7.3). Query luôn có giới hạn (`accessibilityDeadline` > 0, ví dụ 3 s). Rect qua `transform` (point × scale, rồi crop status bar/device frame và kích thước output của simctl) [apple/A3,A4] | App bên thứ ba, hoặc chỉ có clip | Appium + xcuitest + WDA; thiết bị thật cần ký WDA | P1 | mô phỏng |
| **iOS hybrid** (WKWebView) | T1 | (1) Tốt nhất: khi có `DS_PRIVACY_MASK`, app thêm `privacy_mask.js` làm `WKUserScript` ở document start. (2) App không sửa được nhưng `isInspectable=true` (iOS 16.4+, mặc định false): inject qua Appium web context sau mỗi lần navigate, và **cover rect native của webview** cho tới khi `window.__dsMaskReady === true` [apple/A2] | Có source, hoặc webview đã inspectable | Sửa code, hoặc 0 nếu đã inspectable | P1 | chưa test |
| **Flutter** | T1 | Widget `DemoMask` bật bằng `--dart-define=DEMO_MASK=1`, vẽ lớp đục và ghi log như Android T1. Flutter vẽ vào một surface duy nhất nên mask phải là widget [android/A1] | Có source | Bọc từng widget nhạy cảm (vài phút đến vài giờ) | P1 (snippet) | mô phỏng (Android). Trên iOS: **suy luận** rằng cùng widget hoạt động được, chưa test |
| Flutter | T2 | Overlay Android **chỉ** khi semantics tree có text | — | như Android T2 | P3 | chưa test |
| **React Native** | T1 | Wrapper `<DemoMask>`. Text RN render ra native view nên rule regex của snippet Android T1 cũng áp được. RN WebView đi T1 hybrid [android/A1] | Có source | Bọc widget | P1 (snippet) | mô phỏng (Android), iOS chưa test |
| **.NET MAUI, Mac Catalyst** | — | Đi theo hàng native của OS bên dưới: MAUI → Android/iOS/Windows (T1 là snippet trên native view của từng handler); Catalyst → quay như macOS, T1 là snippet UIKit [RTn-11] | — | — | như hàng tương ứng | chưa test |
| Mọi platform | T4 | Cover đục cả panel/container/cửa sổ (overlay tĩnh, hoặc `drawbox t=fill` hậu kỳ trong toạ độ source) | Không định vị được phần tử, Wayland, không có a11y tree, sàn fail-closed | 0 | P0-native | đo-Linux (n=1): 0/349 |
| **Không bao giờ** | — | Content-protection flags; CSRT/KCF cho list; lerp/hold giữa snapshot; quay chỉ-cửa-sổ khi dùng T2; swipe/fling trần khi T2 bật | — | — | — | — |

Ghi chú về tầng Flutter/RN và app bên thứ ba:
- Session-replay SDK (Datadog, Sentry) chứng minh pattern "che theo class/tag/widget" chạy được trong production trên cả 4 stack (Datadog: tài liệu chính thức; Sentry: web-snippet).
- Nhưng các SDK này chỉ che **luồng replay của chính chúng**, không che pixel trên màn hình. App có Sentry hay Datadog **không** có nghĩa là bản quay màn hình đã được che.
- Sentry tự gọi việc che trong SwiftUI là "best-effort".

#### 6.7.3 Chiến lược vị trí theo từng frame

Thứ tự ưu tiên dùng chung cho non-web, thay cho quyết định 6 và X6 đối với non-web (web giữ nguyên §1.6):
1. Vị trí do chính frame đó vẽ (T1).
2. Vị trí suy ra từ pixel của chính frame: scroll-offset propagation.
3. Log vị trí chính xác cộng đồng bộ frame-exact (stamp + pts).
4. Overlay từ accessibility, có pad, guard và giới hạn tốc độ cuộn.
5. Rect a11y chỉ trong cửa sổ tĩnh.
6. Cover container.

| Chiến lược | Cơ chế | Số đo | Kết luận |
|---|---|---|---|
| **Same-frame** (T1) | Mask vẽ trong cùng draw pass với nội dung | Electron 0/324 (đo-Linux, n=1). GTK 0/350 (đo-Linux, n=1). Android S0 0/360 chỉ là mô phỏng hình học, không tính | Chiến lược duy nhất vừa không lộ vừa không nhấp nháy khi fling. Mặc định khi user sở hữu code |
| **Accessibility polling → overlay** (T2) | Poll rect của các phần tử nhạy cảm đã resolve sẵn | AT-SPI: walk toàn cây 120 dòng mất 49.7 ms; `getExtents` p50 0.1/0.84/2.94/4.6 ms cho 1/8/32/120 phần tử; process overlay ở 25 Hz với 8 phần tử tốn khoảng 4.6% một core; có 1 outlier 45.9 ms. Lộ (mỗi cấu hình n=1, Xvfb không compositor): pad0 181/325; pad48 không guard còn 5 (dòng đang vào ở mép); **pad24 + guard40 ở 360 px/s: 0**; **pad64 + guard80 ở 1200 px/s: 0**; pad24 + guard ở 1200 px/s: 37. Vị trí chính xác gửi qua UDP vẫn lộ 19 frame ở pad0, vì overlay trễ khoảng 1 frame. Android S1: 207–219/360 (mô phỏng) | Áp các rule bên dưới |
| **Scroll-offset propagation** (T3, `blur.py track`) | Phase correlation trên ROI container (ds 0.5, hoặc 0.25 khi ROI ≥ 1600 px), refine offset nguyên ở full-res (bắt buộc), offset cộng dồn theo frame. OCR **một lần** trên mosaic nội dung, map box theo pts | Sai số offset 0 px trên portrait 60/25 fps, landscape 30 fps, VFR. Không refine: drift 5.44 px (ds 0.5) và 17 px (ds 0.25). Tốc độ 55–91 fps ở 1080x2400, 172–261 fps ở 720p. End-to-end: **0** item-frame lộ > 10% với mọi loại khớp regex (email, API key, header, toast) trên 5 clip tổng hợp, gồm clip stress có nhảy offset và refresh dữ liệu; 6.7–17.8 s cho clip 12 s; 12–16 lần gọi OCR; mask phủ 0.09–0.20 frame [posthoc-tracking A1, B3, B4] (mô phỏng) | Đường hậu kỳ chính cho container cuộn dọc. Vị trí lấy từ chính pixel nên **không có sai lệch đồng hồ**. Chưa mô hình hoá: parallax, sticky header trong list, pinch-zoom, stretch/rubber-band overscroll, cuộn ngang/2-D, scroll lồng nhau; các trường hợp này phải fail-closed qua residual |
| **Log chính xác + đồng bộ** (T3) | Log vị trí trong app hoặc từ helper, nối với frame qua stamp 16-bit vẽ trong frame + pts | Stamp giải mã đúng 215/215 sau h264 qp18, sai số pts 0 ms. Lệch đồng hồ 8 ms: lộ 200/71/22/12 ở pad 0/8/24/64; 33 ms pad64: 28; 100 ms pad64: 50 (mô phỏng). Log GTK nối theo wall-clock PTS khớp chính xác 331/338, sai số tối đa 6 px → pad 8 ở 360 px/s [android E3/E4] [desktop D2] | Chỉ dùng khi đồng bộ frame-exact (stamp). Khi nối theo wall clock thì pad ≥ 8 px **và** tốc độ cuộn bị giới hạn. Pad không bao giờ bù được fling |
| **Still-window a11y** (T3) | Chỉ tin rect của snapshot mà cả khoảng [t_req, f] không có chuyển động (\|dy\| < 0.5 px ±1 frame, drift cộng dồn < pad/2). Khi đang chuyển động thì cover cả container. Change gate phủ mọi pixel khác frame t_req (bắt toast, dòng chèn muộn) | 0/9807 lộ ở độ trễ snapshot 0.15/0.5/1.5 s và ở idle-wait. Đổi lại: container bị phủ trung bình 0.85/0.90/0.97 (rect chính xác là 0.69), bật/tắt 2–8 lần (mỗi gesture một lần). Render: 30 segment, 66 drawbox, 64 fps, verify 0/9807. Kết hợp offset propagation (snapshot tĩnh đổi sang toạ độ nội dung): 0/18574 với mask 0.52 container [apple E1/E3] [posthoc-tracking A3] (mô phỏng) | Nguồn cho tên và PII khác không bắt được bằng regex. Khi không ước lượng được offset, đây là sàn trước T4. Snapshot chậm thì list gần như trống trong lúc cuộn, phải nói trước với user |
| **Detection theo frame** | OCR mọi frame | RapidOCR det+rec mất 3.1–5.3 s cho mỗi frame 1080x2400; quét 1 fps tốn 186–315 s cho mỗi phút video [posthoc-tracking B1] | **Cấm** theo frame. Chỉ OCR mosaic, OCR sự kiện overlay (≤ 3 frame mỗi sự kiện), và sample có change gate ở verify (§6.7.4) |
| Hold / lerp / CSRT / KCF | — | hold 1440–2263, lerp 1472–3099/9807; KCF mất 28/28 ở frame 61; CSRT mất 13/28 | **Cấm** cho container cuộn. CSRT chỉ dùng cho bề mặt không có hình học (canvas, video, RDP/VM), một phần tử không thuộc list, có re-detect, fail-closed |

**Primitive cuộn duy nhất** [RTn-7]. Trên Android/iOS, một swipe nhả tay khi còn vận tốc sẽ fling theo vật lý của OS, script không kiểm soát được. Vì vậy mọi scene gọi một helper `ds.scroll(container, dy)` của adapter:
- Mobile: kéo với tốc độ ≤ `v_max`, **giữ khoảng 100 ms trước khi nhấc tay** để vận tốc nhả ≈ 0 (Appium `mobile: dragFromToForDuration`, hoặc W3C actions có pause trước pointerUp).
- Desktop: wheel step cố định với khoảng cách cố định (xdotool/SendInput/CGEvent); không dùng gesture có quán tính.
- Khi T2 bật, lint từ chối swipe/fling/scroll trần trong scene.

**Guard là một handshake, không phải "2 frame trước"** [RTn-7]: `guard.arm(container)` → chờ overlay ghi `guard painted` vào `mask.jsonl` (timeout 500 ms; quá hạn thì huỷ scene với exit 11) → `ds.scroll` → chờ idle + 150 ms → `guard.disarm()`.

**Rule bắt buộc cho T2** [desktop/D-R3] [android/A3]:
1. Áp `pad ≥ v_max × (1/Hz + 1/60 s) + 8 px`, trong đó `v_max` do `ds.scroll` **ép**. Demo có lời dẫn nên giới hạn khoảng 400 px/s. Công thức này là **ước lượng bảo thủ, suy ra từ D3, chưa được đo đúng như phát biểu**: các cấu hình đã pass dùng pad nhỏ hơn công thức (24 < 28.4 px ở 360 px/s; 64 < 76 px ở 1200 px/s), mỗi cấu hình 1 run, không compositor. Tiêu chí 24 yêu cầu sweep ≥ 3 run ở pad theo công thức, có một case với compositor (ví dụ picom) [RTn-1].
2. Pad áp **trước** khi clip vào viewport.
3. Khi bất kỳ rect nào đã dịch chuyển kể từ lần poll trước: cover dải guard ở mép trên và mép dưới, chiều cao ≥ pad, vì dòng đang cuộn vào chưa được biết cho tới lần poll sau.
4. Nếu pad tính ra vượt khoảng cách giữa các dòng (row pitch), hoặc vượt nửa container (fling Android 6000 px/s cần pad khoảng 340 px): chuyển sang **column/container guard** cho cả đoạn cuộn, cộng 150 ms sau khi idle.
5. **Cửa sổ mới và cây thay đổi** [RTn-6]: overlay đăng ký sự kiện tạo cửa sổ (AT-SPI `window:create`, UIA `WindowOpened`) và `children-changed`. Cửa sổ top-level lạ xuất hiện trong vùng quay (autocomplete, context menu, tooltip, dialog, toast) → cover cả vùng quay cho tới khi resolve xong. Mỗi lần re-walk (row recycling của list ảo) bị giới hạn ≤ 200 ms; quá hạn → cover panel.
6. Overlay phải click xuyên qua: input shape rỗng (X11), `WS_EX_TRANSPARENT` (Windows), `ignoresMouseEvents` (macOS), `TYPE_ACCESSIBILITY_OVERLAY` (Android). Tiêu chí 24 có test click qua overlay.
7. Log rect của overlay kèm wall time vào `events/<sid>.mask.jsonl`.

#### 6.7.4 Mở rộng `blur.py` (spec)

Áp dụng chung: quy ước §4.2 (stdlib, import lazy, heartbeat jsonl ≤ 2 s, một dòng JSON trên stdout, exit 0/2/3/4/10/11/70), chạy dưới `run_bounded --heartbeat jsonl`, không spawn process cho từng frame. Mọi rect vào/ra đều ở toạ độ pixel của clip source, qua `transform` (§6.7.1 mục 5).

**`blur.py timebase`** (mới, P0-native)
- Lệnh: `--video F [--stamp-strip y,h] [--device-log L.jsonl]`.
- Output: `.demo/<slug>/track/<sid>.timebase.json` = `{vfr, avg_frame_rate, r_frame_rate, frames:[{i, t}], stamps:[{i, device_ms}], device_to_pts:{offset_ms, residual_ms}}`.
  - `t` = `frame.pts × time_base`, lấy qua PyAV/ffprobe `pts_time`.
- Phải chạy **trước** mọi bước chuẩn hoá CFR. Bản CFR lặp frame khi idle, gây stale tới 583 ms [android E3].
- Exit codes:
  - exit 2 nếu thiếu pts;
  - exit 2 nếu yêu cầu stamp mà tỉ lệ giải mã < 100% số frame sync;
  - exit 2 nếu residual nối device-log > ½ frame.
- Budget: 30 s + 0.5 × duration_s (**suy luận**, từ tốc độ decode khoảng 460 fps).

**`blur.py track`** (mới, P1 sau cờ `privacy.platform.track: true`; prototype là `posthoc.py` [posthoc-tracking/R1–R8])
- Input:
  - `--video F`;
  - `--container x,y,w,h` | `--a11y snapshots.jsonl` (bounds của node scrollable; mỗi snapshot có `t_req, t_done`);
  - `--mode regex|alltext`;
  - `[--a11y-still-only]` (luôn bật khi có `--a11y`);
  - `[--allow-failclosed]`;
  - `--budget-s S`. Mặc định `max(60, 1.5 × estimate)`, với `estimate` theo công thức budget bên dưới (frames, độ phân giải, số dòng mosaic dự kiến). Ước tính được in ra ở G1 [RTn-9].
- Thuật toán:
  - pass 1: offset + mosaic. Chỉ ghi đè dòng khi dòng đó đã dịch chuyển quan sát được (motion-confirmed overwrite).
  - pass 2: decode lại, so với mosaic cuối để tìm overlay (ô 16×16, ngưỡng > 10), gộp thành sự kiện.
  - OCR mosaic theo tile 1280 dòng, chồng nhau 96, `Det.limit_type=max`, `limit_side_len=1280`.
  - OCR mỗi sự kiện ở 1/4, 1/2, 3/4.
  - Map `y_screen = y_content − offset(t) + container_top`, không nội suy.
- Regex chịu được lỗi OCR: OCR đọc `_` thành dấu cách nên regex chặt lộ 2040/2611 [B2]. Ví dụ `(sk|pk|rk)[\s_.-]*(live|test)[\s_.-]*\w{6,}`.
- Crop đưa vào OCR phải pad sao cho `h ≥ max(64, w/4)`. Nếu không, RapidOCR bỏ qua detect (w/h > 8): email trên header lộ 360/360 [B2].
- Output: `.demo/<slug>/track/<sid>.json` = `{frames:[{t, boxes:[[x,y,w,h,kind,source]]}], segments[], reanchors[], events[], failclosed:{frames, content_rows, events}, mask_area_frac}`.
- Exit codes [RTn-16]:
  - 0: ok. Với `--allow-failclosed` mà thiếu OCR/PyAV hoặc phải che cả container: vẫn 0, verdict `failclosed`, `mask_area_frac` hiện như advisory ở G2.
  - 2: input sai (không có container; keyframe không có `t`; cấu hình mosaic vượt `MAXROWS` 60000).
  - 3: vượt budget. Phần chưa xử lý bị che hết, ghi coverage một phần.
  - 4: thiếu OCR/PyAV khi **không** có `--allow-failclosed` (route director, G1 như §4.2).
  - 11: self-check phát hiện hit regex (OCR lại 1 frame đã che cho mỗi sự kiện và mỗi 10 s). Route như mọi leak: owner `blur`, block delivery.
  - 70: bug.
- Budget theo số đo:
  - `track_s ≈ frames / (55 fps ở ≥ 1080x2400; 170 fps ở 720p) × 1.25`;
  - `ocr_s ≈ 1.4 s / 1000 dòng mosaic` (regex) hoặc `1.0 s` (alltext);
  - cộng khoảng 1.5 s × 3 cho mỗi sự kiện overlay.
  - Ví dụ: clip 3 phút 1080x2400@60 có `track_s` ≈ 10800/55 × 1.25 ≈ 245 s riêng phần track; công thức cũ `60 + 1.0×dur` (240 s) sẽ luôn exit 3, nên bị thay.

**`blur.py plan`** (mở rộng)
- Nguồn mới:
  - `--positions P.jsonl`: log theo frame từ T1/T2, nối qua `timebase`;
  - `--a11y snapshots.jsonl`: quy tắc still-window;
  - `--track <sid>.json`.
- Vùng `moving` phải có **một keyframe cho mỗi pts**. Keyframe thưa trên vùng chuyển động → exit 2: không còn đường lerp.
- Đoạn chuyển động không có vị trí chính xác → vùng `cover` toàn container.
- Mọi keyframe tính bằng giây (`t`). File không có `t`, hoặc input VFR (`avg_frame_rate ≠ r_frame_rate`) mà thiếu pts → exit 2.

**`blur.py graph`** (mở rộng)
- Mọi `enable` dùng `between(t,a,b)` và `sendcmd` theo timestamp pts, không dùng `n`.
- Non-web luôn dùng `--space source`: mask T3/T4 được burn vào clip trung gian `masked/<sid>.mp4` theo pts của source, **trước** mọi retime/reframe (§6.7.8).
- Quyết định hằng (still-window, cover) gộp thành segment hằng (không cần `sendcmd`).
- Vùng chuyển động theo frame dùng `sendcmd` trong một graph duy nhất.
- Budget: chi phí ≤ 1.5× encode không mask. Đo được 1.33× với 12 slot ở 1080x2400@60 [android E5]; 64 fps với 66 drawbox ở 780x1688 [apple E3] (mô phỏng).

**`blur.py verify`** (mở rộng cho non-web) [RTn-9]
- `--mask-log` cho T1/T2 có log (snippet Android/iOS/macOS, overlay desktop): kiểm tương tự gate `privacy_capture` (§6.4), dùng rect + pixel.
- Full-frame: **det-only** trên frame, rồi rec chỉ trên box đã phát hiện; det-only được red-team ước khoảng 0.17–0.8 s/frame từ B1 (**suy luận**, phải đo lại ở P1), so với 3.1–5.3 s cho det+rec.
- Chọn frame theo **change gate** dùng chung detector sự kiện của pass 2 trong `track`: mọi sự kiện overlay (toast, heads-up, dialog) có ít nhất 1 frame được OCR; ngoài sự kiện thì stride thưa. Không còn stride cố định 5 s.
- Budget non-web: `max(300, 1.5 × estimate)` với `estimate` từ số frame được chọn × chi phí det/rec, in ở G1; hết budget → exit 3. Web giữ budget §6.4.
- Luôn báo `mask_area_frac`. Vượt ngưỡng đã chấp nhận ở G1 (mặc định cảnh báo ở 0.30) → finding advisory hiện ở G2.

#### 6.7.5 Quy tắc fail-closed cho non-web

1. **Armed assertion trước khi quay.** Nếu tầng đã chọn chưa armed thì `capture.py` exit 11 và không quay. Điều kiện armed theo tầng:
   - Electron (T1 main-world): cùng assertion web (highlight đã đăng ký + computed style) + log rAF có entry đầu tiên.
   - Android/Flutter/RN T1, Android T2: helper `armed` với `n_rules > 0` và `n_matched ≥` số SENSITIVE mong đợi trên màn đầu tiên.
   - WebView/mobile web qua CDP: highlight đã đăng ký.
   - iOS/macOS T1: log của snippet có `n_rules/n_matched`, và tập accessibilityIdentifier đã che phải phủ danh sách identifier ghi ở G1. **Không có log** → tầng là `T1-unverified`: chỉ được dùng kèm T3 still-window cho tên/PII không khớp regex, không bao giờ một mình [RTn-14].
   - Overlay desktop: đã vẽ xong (rect đầu tiên có trong `mask.jsonl`).

   Chỉ được hạ xuống T3 khi G1 đã ghi `privacy.fallback: posthoc` (raw sẽ chứa PII → §6.5).
2. **Pre-roll:** mọi frame trước `mask_ready_t` bị cắt khỏi clip scene. Electron T1' bắt buộc cắt.
3. **Overlay:** poll lỗi, mất phần tử, một lần poll > 100 ms, hoặc re-walk > 200 ms → cover cả panel cho tới lần poll hợp lệ kế tiếp. Cửa sổ top-level lạ trong vùng quay → cover cả vùng.
4. **Chuyển động không có vị trí chính xác** → cover container cho cả span.
5. **Alignment** (`track`): residual > 6.0 (clip thường tối đa 1.27; stress 13.2–15.1) → cover cả container cho frame lỗi ±1. Sau đó re-anchor bằng template match (`TM_SQDIFF_NORMED < 0.02`, residual full-res < 2.0), hoặc mở segment mới.
6. **Sự kiện overlay** không OCR kịp trong budget → che cả hộp sự kiện. Blob full-width (bàn phím, sheet) → thêm dải một dòng chữ ở mỗi mép.
7. **Thiếu OCR hoặc hết budget** → che full-width các dòng nội dung đó, verdict `failclosed`. Clip `--ocr 0` có mask phủ 1.14 frame, an toàn nhưng không dùng được cho demo.
8. **Thời gian:** thiếu pts → exit 2. Lint chặn `index/fps`.
9. **App tự che khi bị quay** (FLAG_SECURE, Android 15, `sceneCaptureState`, `GetWindowDisplayAffinity ≠ 0`) [RTn-8]. Kiểm trực tiếp cờ, không so screenshot (vì `adb screencap` cũng bị FLAG_SECURE làm đen):
   - Android: `dumpsys window` của cửa sổ đang focus có cờ `SECURE`; hoặc view hierarchy (UiAutomator) có text hiển thị trong khi frame gần đồng nhất về luma.
   - Windows: `GetWindowDisplayAffinity`. macOS: `kCGWindowSharingState` của cửa sổ trong `CGWindowListCopyWindowInfo` bằng none.
   - `blackdetect` chỉ là tín hiệu phụ, và yêu cầu frame gần đồng nhất (độ lệch chuẩn luma thấp), không chỉ tối, để app dark theme không bị báo nhầm.
   - Kết quả: `blocked: app blanks under capture`, không retry.
10. **Dùng T2 mà recorder chỉ quay cửa sổ** → exit 2. Dry run vẽ một hình chữ nhật thử màu biết trước, hình này phải xuất hiện đúng rect pixel. Probe này chạy cho **mọi** platform và tầng (không chỉ T2), gồm một lần ở landscape trên mobile, để bắt quay chỉ-cửa-sổ, lệch DPI, xoay và crop [RTn-12].
11. **Vệ sinh OS** ghi trạng thái cũ vào `.demo/<slug>/hygiene.json` **trước** khi đổi; khôi phục trong `finally` cộng session-end hook; và mỗi lần `capture.py` khởi động thì chạy `os_hygiene status` và khôi phục mọi entry còn treo trước (adb rớt, host crash, session bị kill) [RTn-13].
12. **Mọi query a11y, adb và bước tương tác OS có giới hạn** [RTn-13]:
    - iOS: `accessibilityDeadline` > 0, `waitForIdleTimeout` 1–2 s, `animationCoolOffTimeout` 0. Build WDA lần đầu ≤ 600 s, có heartbeat.
    - Android: page-source có wall ≤ 15 s, `waitForIdleTimeout` 0–500 ms, tắt animation. Tìm pid webview ≤ 10 s.
    - TCC preflight không tương tác: chỉ kiểm, không bao giờ kích hoạt prompt; thiếu quyền → `blocked` trong ≤ 10 s.
    - Dừng recorder (scrcpy, simctl, ffmpeg): SIGINT → chờ 10 s → KILL → ffprobe file.
    - Tất cả chạy dưới `run_bounded`.
    - UiAutomator2/XCUITest **chỉ** dùng cho rect tĩnh, không bao giờ để lấy vị trí theo frame.
13. **Nhập dữ liệu nhạy cảm**: dùng Appium `setValue` hoặc `adb input text` khi bàn phím đã ẩn; không bao giờ bấm từng phím khi `show_touches` bật (popup phím lộ mật khẩu) [RTn-5].

#### 6.7.6 Vệ sinh OS: status bar, notification, bàn phím, autofill

Mọi mục dưới đây do `os_hygiene.py` làm, mỗi mục có bước `status` và bước khôi phục, giá trị cũ lưu trong `hygiene.json`. Tất cả **chưa test** trên platform thật, trừ dòng Linux.

| Platform | Xử lý | Kiểm | Trạng thái |
|---|---|---|---|
| Android: status bar | `settings put global sysui_demo_allowed 1`; `am broadcast -a com.android.systemui.demo -e command enter`, rồi `clock -e hhmm 0941`, `network -e wifi show -e level 4`, `battery -e level 100 -e plugged false`, `notifications -e visible false` (chỉ ẩn icon). Khôi phục: `-e command exit` [android/A7] | Một screenshot dải status bar (SystemUI của OEM có thể bỏ qua lệnh, web-snippet) | chưa test |
| Android: notification | `cmd notification set_dnd none` (chặn cả alarm và cuộc gọi, khác `alarms`). Khôi phục `set_dnd off` [RTn-5] | Đọc lại trạng thái DND; dry run gửi một notification thử, không được xuất hiện | chưa test |
| Android: bàn phím, autofill, clipboard | `settings put system show_password 0`; `settings put secure autofill_service null`; chuyển IME sang bàn phím không học (ADBKeyboard, hoặc AOSP LatinIME tắt gợi ý) bằng `ime set`; xoá clipboard trước scene (Appium `mobile: setClipboard` rỗng) để chip clipboard của Android 13+ và gợi ý clipboard không có gì. Khôi phục giá trị cũ từ `hygiene.json` [RTn-5] | `settings get` từng khoá; `ime list -s` | chưa test |
| Android: touches, recents | `settings put system show_touches 1` chỉ khi mọi input nhạy cảm đi qua `setValue` (§6.7.5 mục 13). Recents/app switcher cấm trong scene, trừ khi T4 phủ; xoá recents trước scene khi version cho phép (cơ chế theo version, chưa test). Khôi phục `show_touches 0` | — | chưa test |
| iOS simulator | Ưu tiên simulator vì không có dữ liệu cá nhân. `simctl status_bar override`; được báo là hỏng trên iOS 17+ (web-snippet), nên fallback là cover đục `statusBarSize × scale` lấy từ `mobile: deviceScreenInfo` (qua `transform`), hoặc crop bằng device frame. Tắt QuickType, autofill, gợi ý mật khẩu (cách tự động hoá chưa test) [apple/A5] [RTn-5] | Kiểm override bằng một frame; fail thì dùng cover | chưa test |
| iOS device | Focus/DND, cấp sẵn quyền, tắt QuickType/autofill/gợi ý mật khẩu (thao tác tay ở G1). Recorder `mobile: startXCTestScreenRecording` (Xcode 15 / iOS 17+) | Notification thử trong dry run | chưa test |
| macOS | Từ P3: quay chỉ cửa sổ (H) loại hết chrome. Trước P3 (H⁻) hoặc khi dùng T2: quay display, ẩn Dock và menu-bar extras, ghim hình học bằng `macos: adjustWindow`, cover phần ngoài cửa sổ app | Notification thử gửi giữa lúc quay không xuất hiện ở frame nào | chưa test |
| Windows | Đặt cửa sổ app với kích thước cố định, nằm hẳn trong work area và tránh góc toast; probe kiểm hình học. Quay vùng đúng bằng cửa sổ (offset/size). Bật Do Not Disturb qua Settings là **bước tay ở G1**, được kiểm bằng một toast thử trong dry run [RTn-19] | Hình thử màu bắt buộc cho cả `ddagrab` và `gdigrab`; toast thử | chưa test |
| Linux X11 | `x11grab` theo vùng cửa sổ | Hình thử màu | đo-Linux (vùng, n=1) |
| Mọi platform | Vùng status bar/chrome vẫn nằm trong full-frame regex OCR của verify | — | — |

#### 6.7.7 G1 cho non-web (vẫn ≤ 2 vòng; app-scout điền sẵn)

**Vòng 2** (cùng `data_mode` và phần duyệt kế hoạch cài đặt), tối đa 4 câu. Mọi lựa chọn tầng lấy từ `available_tiers` của version đang cài; tầng chưa có thì không hiện [RTn-3]:
1. **`data_mode`**: luật §6.1 giữ nguyên.
   - Với non-web, nói rõ cho user: `seeded` giúp tránh đường T3 đắt và dễ che quá tay.
   - Không trả lời, hoặc đang ở auto mode → `real-redacted`.
2. **Quyền với app và khả năng che lúc quay.** Lựa chọn tuỳ platform:
   - "tôi build được bản debug/demo" → T1 (snippet);
   - "app đã có `DS_PRIVACY_MASK` / `DEMO_MASK` / thư viện mask";
   - "WebView đã bật debugging / inspectable";
   - "app bên thứ ba / chỉ có bản release" → T2 nếu đã có (P2 cho X11, P3 cho Android/Windows/macOS), nếu không thì T3/T4;
   - "chỉ có clip có sẵn" → T3, cần một ROI container cho mỗi scene, do a11y cung cấp hoặc user vẽ.
3. **Loại PII trên màn hình:**
   - chỉ loại regex bắt được (email, key, số) → `regex`;
   - có tên hoặc text tự do → cần a11y resource-id hoặc cột do user chỉ định, nếu không có thì `alltext` (mask khoảng 0.27–0.36 frame).
   - Kèm câu hỏi: ngưỡng `mask_area_frac` chấp nhận được, có chấp nhận fallback hậu kỳ (`privacy.fallback: posthoc`) hay không, và ước tính budget hậu kỳ (§6.7.4).
4. **Thiết bị và quyền** (gộp vào kế hoạch cài đặt):
   - Thiết bị: emulator, simulator hay máy thật; host có Mac không (iOS bắt buộc).
   - Quyền và thao tác tay: TCC Screen Recording/Accessibility, helper accessibility service, "allow restricted settings" trên Android 13+, Do Not Disturb trên Windows, tắt QuickType/autofill trên iOS device.
   - Mỗi mục kèm thời gian ước tính từ bảng §6.7.2.

Mọi lựa chọn được ghi vào `demo.yaml` `privacy.platform.*`. Không auto-approve phần privacy [RT-4].

#### 6.7.8 Tương tác với các lệnh hiện có [RTn-10]

- **Mask T3/T4 luôn được burn vào clip source** (`masked/<sid>.mp4`, theo pts của source, kể cả cover status bar) **trước** mọi retime (revoice, sync-editor) hay reframe (cut). Mọi bước sau đọc từ clip đã che; `track.json` và `transform` không bao giờ phải biến đổi theo aspect.
- **`/cut`** (đổi tỉ lệ, ví dụ 9:16 → 16:9): không biến đổi box nào, render từ clip đã che, rồi chạy `verify` trên từng output như §6.4.
- **`/revoice`**: retime chỉ chạm clip đã che; không chạy lại `track`.
- **`/rerecord`**: chạy đủ adapter capture (vệ sinh OS, armed assertion, probe, timebase), rồi `track` nếu tầng < T1, rồi blur.
- **Fingerprint `--reuse-draft`** (§4.2) với non-web thêm: `tier`, thiết bị + version OS, hash của mask kit/snippet, và hash của timebase.
- **Map trong `fix.md`**: `events → timebase → track → blur (masked clip) → render → checks`. Đổi `privacy.platform.tier` hoặc mask kit map về `events` (tức rerecord), không phải blur lại.
- Raw clip bị xoá theo `raw_retention` thì đổi mask cũng cần rerecord; `demo.py` báo rõ thay vì thử blur lại.
- Test hồi quy: `/cut` và `/revoice` trên một fixture T3 cho 0 leak trên mọi output (tiêu chí 31).

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

**Desktop & mobile (§6.7)**

23. Electron: 0 frame lộ, OCR 0 trên frame được sample, qua ≥ 3 run, kể cả frame 0; gate `privacy_capture` của web chạy nguyên trên clip Electron (main-world `privacy_mask.js`, gồm input và SVG). Bỏ hook thì assertion exit 11. Fallback reload pass ≥ 5 run, nếu không thì bị đánh dấu không tin cậy. Probe fuse định tuyến app có fuse tắt sang đường native.
24. Overlay T2: 0 frame lộ sau `mask_ready` ở mọi tốc độ ≤ `v_max`, qua sweep ≥ 3 run ở pad **theo công thức** §6.7.3, có ít nhất một case với compositor (ví dụ picom). Đặt pad=0 hoặc bỏ guard thì bộ đếm lộ **phải fail** (test âm). Click qua overlay tới đúng phần tử bên dưới. Cửa sổ top-level mới (menu, tooltip) trong vùng quay được cover cho tới khi resolve. CPU ≤ 10% một core ở 25 Hz. Poll > 100 ms hoặc re-walk > 200 ms → cover panel. Guard handshake timeout → exit 11.
25. `blur.py track` trên bộ clip hồi quy (portrait 60/25, landscape 30, VFR, stress):
    - offset sai số 0 px;
    - 0 item-frame lộ > 10% với mọi loại khớp regex (regex mode), và với tên (alltext hoặc a11y seed);
    - track ≤ 1.25× thời lượng ở 1080x2400@60 (đo 55–91 fps) và ≤ 0.25× ở 720p30;
    - toàn bộ stage ≤ 20 s cho clip 12 s;
    - budget quá nhỏ → exit 3; OCR tắt với `--allow-failclosed` → exit 0, verdict `failclosed`, 0 lộ; không có cờ → exit 4.
26. Still-window: 0/9807 trên fixture apple ở độ trễ 0.15/0.5/1.5 s. Hold/lerp bị lint chặn.
27. Mọi map thời gian dùng pts: fixture VFR sai số 0 ms; map theo index làm test fail; stamp giải mã 100%. Hàm `transform` đúng trên fixture xoay, crop status bar, scale Retina 2× và toạ độ âm.
28. `graph` hậu kỳ ≤ 1.5× encode không mask ở 1080x2400@60; một graph duy nhất, không spawn theo frame.
29. Vệ sinh OS được khôi phục sau cả thành công lẫn thất bại, **và** sau khi process bị kill giữa chừng (lần `capture.py` kế tiếp khôi phục từ `hygiene.json`); query a11y có deadline; TCC preflight không bao giờ treo; dry run phát hiện app tự che qua cờ, không báo nhầm app dark theme.
30. Mọi tuyên bố cho Android/iOS/macOS/Windows giữ nhãn "chưa test trên platform thật" cho tới khi tiêu chí 23–29 và 32 pass trên thiết bị thật tương ứng.
31. `/cut` và `/revoice` trên một fixture T3: 0 leak trên mọi output; `track` không chạy lại khi chỉ đổi aspect hoặc voice; đổi `tier` làm `events` stale.
32. Vệ sinh mobile: contract test kiểm đủ chuỗi lệnh cho `show_password`, autofill, IME, clipboard, `set_dnd none`, status bar, và mỗi lệnh có bước khôi phục; scene T2 có swipe trần bị lint từ chối.

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
- **Desktop & mobile, chạy được trong CI Linux** (GitHub Actions ubuntu + Xvfb):
  - Electron có hook, không hook, reload (tái hiện D1) và biến thể main-world đầy đủ [P0-native].
  - `blur.py timebase/plan/graph` (P0-native) và `track` (P1) trên clip tổng hợp **sinh lúc chạy test** (port `gen.py` của posthoc-tracking/apple/android vào `scripts/tests/fixtures/`, không lưu byte video).
  - Mô phỏng hình học E2/E4 làm unit test cho logic guard và pad (chỉ kiểm logic, không tính là bằng chứng cho Android).
  - Lint `index/fps`, lint swipe trần, lint lerp/hold/CSRT trên container cuộn.
  - Contract test cho `os_hygiene.py` với adb/xcrun giả: chuỗi lệnh, `hygiene.json`, khôi phục sau kill (**không** kiểm hành vi thiết bị).
  - P2: GTK3 + AT-SPI + overlay + `x11grab`, gồm test âm pad0/không guard, sweep ≥ 3 run, case picom, click-through. Cần apt `at-spi2-core python3-pyatspi gir1.2-gtk-3.0 xdotool x11-utils`.
  - Ước tính: Tier 1 thêm khoảng 2–3 phút (**suy luận** từ thời gian thí nghiệm).
- **Không chạy được ở đây, có thể chạy trên runner khác** (**suy luận**, chưa kiểm): Android emulator trên runner có KVM (container này không có KVM và `dl.google.com` bị 403); iOS simulator và Mac2 trên runner macOS; UIA/`ddagrab` trên runner Windows (`ddagrab` cần D3D11, có thể không có trên runner headless). Tất cả xếp vào Tier 2 nightly, không chặn PR.
- **Chỉ kiểm được trên thiết bị thật** (checklist tay ở P3):
  - Android: restricted settings 13+; phát hiện quay màn hình của Android 15 và FLAG_SECURE với scrcpy; SystemUI demo mode trên máy OEM; độ trễ thật của overlay và throttle `TYPE_VIEW_SCROLLED`; gợi ý bàn phím, autofill, chip clipboard, heads-up với `set_dnd none`.
  - iOS: ký WDA và độ trễ snapshot XCUITest với 50–300 phần tử; `sceneCaptureState` với simctl/XCTest; `simctl status_bar` trên iOS 26/27; QuickType/autofill.
  - macOS: TCC trên Sequoia, overlay trong SCK display, cửa sổ trải hai display khác scale.
  - Windows: độ trễ UIA, overlay trong WGC/`ddagrab` và `gdigrab` (CAPTUREBLT), toast với Do Not Disturb, đa màn hình mixed-DPI.
- **CI:** chưa có `.github/` nên phải tạo mới; GitHub Actions ubuntu với ffmpeg qua apt và Chromium của Playwright.
- **Đo trước và sau** từ `runs.jsonl` và transcript: thời gian từng stage (gồm thời gian agent), số tool call, token. Đây là cách kiểm các khẳng định đang được đánh dấu "suy luận" trong tài liệu này.

---

## 8. Kế hoạch migrate theo phase

### 8.0 Quy tắc vận hành và phạm vi (rev 3, 2026-11-21, chủ repo chốt) — ưu tiên hơn mọi chỗ khác trong §8

Lý do: P0-web tốn 3 vòng review riêng (code + security), mỗi vòng mở thêm vòng sửa; lợi ích giảm dần, token tăng.

1. **Review:** mỗi vòng chỉ **một lượt review gộp** (code + security cùng một agent/báo cáo). **Tối đa 2 vòng mỗi phase.** Chỉ blocker được sửa trong phase; mức "nên sửa"/minor/suggestion vào `.team/backlog/BACKLOG.md`, không mở thêm vòng.
2. **Phạm vi theo thứ tự ưu tiên R29:**
   - P0-native: **chỉ Electron** (mask kit + probe fuse). Phần timebase/lint/T4 dời sang khi có nhu cầu.
   - P1: **chỉ Android hybrid/WebView** (CDP → `privacy_mask.js`). Mọi nền tảng khác chỉ dùng T3/T4 (`blur.py` hậu kỳ + cover đục).
3. **P3 hoãn** cho tới khi có thiết bị thật. Trong container chỉ làm mô phỏng, và ghi nhãn rõ.
4. **Điểm dừng mặc định: sau P1.** Mục tiêu chính (blur hết treo, hết chậm) đạt ở P0–P1. P2 (thu gọn roster, giảm token mỗi lần chạy) chỉ làm khi chủ repo yêu cầu lại.

**Trạng thái P0-web:** xong. Code review vòng 3 có 1 blocker (R-18), đã sửa. Security vòng 3: PASS. S-19, S-26, S-27 và S-29 chuyển vào backlog theo quy tắc 1; bản sửa dở được lưu ở `.team/backlog/s19-s26-partial.patch`.

### P0 (P0-web): chữa nỗi đau chính (blur chậm/treo) mà không đổi roster

Phạm vi P0-web giữ nguyên như rev 1. Việc non-web tách sang P0-native để không làm chậm bản sửa cho web [RTn-17].

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

### P0-native: nền tảng non-web kiểm được trên Linux (sau P0-web, không chặn nó)

- **Phạm vi** (giữ nhỏ có chủ đích) [RTn-17]:
  - `blur.py timebase`; `plan`/`graph` theo `t` (pts) và `--space source`; lint `index/fps`; lint chặn lerp/hold/CSRT trên container cuộn; regex chịu lỗi OCR và pad crop trong `verify`.
  - T4 container cover (overlay tĩnh hoặc `drawbox t=fill`) làm sàn cho mọi platform.
  - Mask kit Electron (`assets/mask-kits/electron/`: hook + preload chạy `privacy_mask.js` main world) + assertion + probe fuse.
  - Cảnh báo content-protection; sửa `desktop.md:13-23,44` và dòng pts trong `mobile.md`.
  - Commit generator và script đo của exp2 (`gen.py`, prototype `posthoc.py`, `overlay.py`, `rec.js`) vào `scripts/tests/fixtures/exp2/` kèm README ghi số run của từng thí nghiệm [RTn-18].
- **Lý do:** non-web hiện đi thẳng vào đường blur hậu kỳ chậm và hay treo, đúng nỗi đau mà P0 nhắm tới. Các phần trên đều kiểm được trên Linux và không cần thiết bị.
- **File:** `scripts/blur.py`, `scripts/tests/test_blur_timebase.py`, `scripts/tests/fixtures/gen_native.py`, `scripts/tests/fixtures/exp2/`, `assets/mask-kits/electron/`, `skills/platform-automation/references/{desktop,mobile}.md`.
- **Exit:** tiêu chí 23, 27, 28 (trên Linux); lint xanh.
- **Rollback:** cờ `privacy.platform.tier` ép về T4; version plugin như P0.

### P1: checks một nguồn, hook, trải nghiệm gate

- **Phạm vi:**
  - `checks.py` đầy đủ: combined pass, VTT lint, dead-air, allow dẫn xuất, `dod`.
  - `hooks/hooks.json` (SubagentStop có lọc `agent_type` và bộ đếm, PreToolUse Write/Edit); `maxTurns` cho mọi agent.
  - `demo.py status|accept`.
  - Cache key và `runs.jsonl`.
  - G1 hai vòng có kế hoạch cài đặt gộp và mẫu giọng dựng sẵn; S2b scene authoring trước nháp; G2 có video nháp; S4 tái dùng raw nháp; G3 dùng bản tóm tắt bằng ngôn ngữ thường.
  - Channel presets.
  - CI Tier 0–1.
  - **Non-web** [§6.7]: `blur.py track` sau cờ `privacy.platform.track` (regex mode, rồi `alltext` + a11y seed); `verify` non-web (det-only, change gate, budget theo ước tính); `os_hygiene.py` (gồm bàn phím, autofill, clipboard, `hygiene.json`); adapter `capture.py` theo platform với `ds.scroll`, `transform` và dry-run probe; Android WebView/Chrome qua CDP; iOS WKUserScript/web context; Tauri; macOS H⁻; snippet T1 cho Android/Compose/RN/Flutter/SwiftUI/UIKit có log (nhãn chưa test); nạp snapshot iOS/macOS theo still-window có `accessibilityDeadline`; câu hỏi G1 non-web (§6.7.7) theo `available_tiers`; §6.7.8 trong `commands/{cut,revoice,rerecord,fix}.md`; `references/ios.md`, `macos.md`.
- **File chạm tới:** `scripts/checks.py`, `scripts/demo.py`, `scripts/capture.py` (`--reuse-draft`), `hooks/hooks.json`, `hooks/demo_hook.py`, `commands/new.md`, `commands/run.md`, `commands/fix.md`, `commands/review.md`, `agents/demo-director.md` (gate), `agents/scene-automator.md` (S2b), `templates/qa.md`, `templates/demo.yaml` (preset), `assets/voice-samples/`, `.github/workflows/ci.yml`.
- **Exit criteria:** tiêu chí 12–19; trên example, G-1 không còn fail và M-2 bị dead-air bắt; tiêu chí 20 (dry-run mọi command) pass với roster cũ. Non-web: tiêu chí 25, 26, 29, 31, 32 (Linux + contract test).
- **Rollback:** tắt hook bằng cách xoá entry trong `hooks.json` (không ảnh hưởng dữ liệu). Nháp ở G2 có cờ `gates.draft: false`.

### P2: thu gọn roster và chuyển phần cơ khí thành script

- **Phạm vi:**
  - `timeline.py`, `captions.py`, `mix.py`, `render.py` (`--scenes`, re-concat), `package.py`, `vo.py synth`.
  - `demo.py next|brief|run` (có `--scenes`) và contact sheet so sánh trước/sau theo scene.
  - Gộp `story` (strategist + storyboarder + scriptwriter), gộp `scene-automator` + `capture-operator`, gộp `editor`.
  - Xoá 8 agent haiku và toolsmith. Viết lại director (≤ 1200 từ). Thu gọn run-kits. PreToolUse Bash guard. CI Tier 2.
  - Cân nhắc `ffmpeg-normalize` và `stable-ts`.
  - Gộp `scene-automator` gồm luôn adapter platform; không thêm platform mới.
  - Linux X11: GTK CSS + `overlay_mask.py` (T1/T2), trừ khi chủ repo xác nhận nhu cầu sớm hơn (R29). Exit thêm tiêu chí 24 trên Linux.
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

### P3: xác thực trên platform thật (→ 0.6.0)

- Chạy tiêu chí 23–29 và 32 trên emulator/simulator và ít nhất một thiết bị thật cho mỗi OS (Android, iOS, macOS, Windows).
- Quyết định X21 (thư viện Android debug-only + helper APK, Swift package, `ds-sck-record`, overlay UIA trên Windows, a11y bridge cho JVM) và ship các tầng có cột "Có từ: P3" ở §6.7.2.
- Gỡ nhãn "chưa test" chỉ cho những mục đã pass.
- **Rollback:** cờ `privacy.platform.tier` ép về T3/T4.

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
- Bump `plugin.json` version: P0 → 0.3.0 (P0-native → 0.3.x), P1 → 0.4.0, P2 → 0.5.0, P3 → 0.6.0. Cập nhật `description` ("18 agents") ở P2.
- Clip non-web cũ được migrate với `tier: T3` và `transform` identity (vùng cũ đã ở pixel clip); `timebase` chạy lại trên raw trước khi blur, không có raw thì giữ nguyên vùng `legacy`.

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
| R11 | Nguồn bị chặn mạng: docs.sentry.io, supademo, storylane, ffmpeg.org, docs.python.org, gnu.org, netflix partnerhelp, cdn.openai.com, docs.langchain.com; vòng desktop/mobile thêm `dl.google.com` (403), `playwright.dev`, `learn.microsoft.com`, `appium.github.io`, `unpkg.com` | Một số trích dẫn chỉ là web-snippet | Kiểm lại khi mở host; các kết luận then chốt đều có thí nghiệm cục bộ chống lưng. |
| R12 | Dưới 3 phút cho 2–3 lần render là mục tiêu, không phải số đo | Kỳ vọng sai | Đo baseline ở đầu P0. |
| R13 | Tỉ lệ demo chạy trên app user kiểm soát được so với app bên thứ ba | Quyết định mặc định mask/seed | Hỏi user; thu thập từ `demo.yaml` qua các lần chạy. |
| R14 | CSS Custom Highlight API: hỗ trợ trên Chromium của Playwright, nhưng Firefox/WebKit của Playwright có thể khác; chỉ một tập thuộc tính CSS áp được cho `::highlight` | Mask không áp trên engine khác | Assertion fail-closed phát hiện; dự phòng overlay; P0 chỉ cam kết Chromium **(chưa test)**. |
| R15 | Overlay theo rAF có thể trễ một frame khi cuộn nhanh | Lộ một frame ở mép | Overlay phủ rộng thêm `pad`; gate §6.4 bắt được; ưu tiên Highlight (vẽ cùng frame với text). |
| R16 | UI bản địa hoá (vi) đổi độ dài text và layout lúc quay | Rect, word budget và caption lệch | localizer làm nháp stale; G2 duyệt lại nháp đã bản địa hoá. |
| R17 | Toàn bộ hành vi Android/iOS/macOS/Windows chưa chạy trên thiết bị; số đo Linux phần lớn n=1, Xvfb không compositor | Thiết kế có thể sai ở chi tiết | Nhãn "chưa test"; sweep ≥ 3 run (tiêu chí 24); P3; T3/T4 an toàn độc lập với platform (dựa trên pixel). |
| R18 | Android 13+ "restricted settings" chặn bật helper service qua adb | T2 Android cần thao tác tay | Hỏi trong kế hoạch cài đặt ở G1; fallback T3. |
| R19 | App tự che khi bị quay (Android 15, `sceneCaptureState`, FLAG_SECURE) | Clip đen, bị hiểu nhầm là freeze | Dry run kiểm cờ trực tiếp (§6.7.5 mục 9) → `blocked`. Chưa biết scrcpy hay simctl có kích hoạt cơ chế này không. |
| R20 | TCC trên Sequoia hỏi lại hằng tháng (web-snippet); quyền Accessibility của WDA mất sau mỗi lần rebuild ad-hoc | Chạy unattended bị chặn | Preflight TCC không tương tác → `blocked` ≤ 10 s kèm các bước cụ thể trong System Settings. |
| R21 | `simctl status_bar` hỏng trên iOS 17+ (web-snippet) | Status bar lộ giờ/mạng | Cover đục `statusBarSize × scale`. |
| R22 | Chi phí bảo trì snippet/thư viện/helper cho 4 stack | Nợ kỹ thuật; user phải tự bảo trì đoạn copy | X21: snippet trước, thư viện sau P3. |
| R23 | Electron fuse chặn `-r`/inspector (phổ biến ở app đóng gói); `setPreloads` có thể bị deprecated, thay bằng `registerPreloadScript` (**suy luận**) | Mất T1 cho Electron | Probe fuse trước G1; kiểm theo version; fallback sang đường native. |
| R24 | Wayland không có overlay toàn cục và hình học a11y | Chỉ còn T3/T4 | Báo rõ ở G1. |
| R25 | Che quá tay: still-window phủ 0.85–0.97 list; alltext 0.27–0.36 frame; bàn phím landscape 0.37 | Demo không dùng được | Báo `mask_area_frac`; ngưỡng chấp nhận ở G1; hướng user sang T1. |
| R26 | Cuộn không cứng chưa mô hình hoá (stretch/rubber-band overscroll, parallax, sticky header, pinch-zoom), cuộn ngang/2-D, scroll lồng nhau | Lộ, hoặc fail-closed quá tay | Fail-closed qua residual; ROI cho từng container; mở test ở P3. |
| R27 | Container ROI cần a11y hoặc user vẽ; chưa có tự dò | Thêm thao tác cho clip cũ | Hỏi một ROI cho mỗi scene ở G1. |
| R28 | Toạ độ lệch: Windows DPI/toạ độ âm, macOS cửa sổ trải 2 display, Android xoay khi khoá orientation, scrcpy `--max-size` | Mask lệch | Một hàm `transform`; hình thử màu ở mọi platform, cả landscape; một màn hình, scale cố định cho T2. |
| R29 | **Chưa biết platform nào được dùng nhiều** (X13) | Có thể tốn công cho target ít dùng (ví dụ Linux X11) | **Đã chốt (2026-11-21, chủ repo uỷ quyền):** 1 Web → 2 Electron → 3 Android (hybrid trước, native sau) → 4 Windows → 5 macOS → 6 iOS → 7 Linux X11. Wayland, JVM, MAUI/Catalyst chỉ T3/T4. Lý do: (a) case thật duy nhất trong repo là web (`example/`); (b) Electron dùng lại nguyên `privacy_mask.js`, đã đo 0/324; (c) Android quay được từ mọi host OS (adb, scrcpy), hybrid đi CDP như web; còn iOS bắt buộc có Mac + Xcode, nên xếp sau macOS (**suy luận** về mức dùng, chưa có dữ liệu người dùng). Linux GTK/overlay giữ ở P2. Xem lại thứ tự khi có dữ liệu dùng thực tế. |
| R30 | Bề mặt PII của OS trên mobile (gợi ý bàn phím, autofill, chip clipboard, `show_password`, heads-up, recents) chỉ có xử lý trên giấy | Lộ dữ liệu ngoài app | `os_hygiene` có status + khôi phục; nhập qua `setValue`; ưu tiên simulator/emulator sạch; full-frame verify vẫn quét. Chưa test. |

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

### Web, vòng desktop/mobile (§6.7)
- *Đọc trực tiếp:*
  - developer.android.com: FLAG_SECURE / `setContentSensitivity`; Android 15 screen-recording detection; Android 12 untrusted touch; `UiAutomation` (`FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`, `setAnimationScale`); `AccessibilityEvent`; WebView remote debugging; `adb screenrecord`.
  - AOSP SystemUI `demo_mode.md`: https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/main/packages/SystemUI/docs/demo_mode.md
  - scrcpy `doc/recording.md`, `doc/video.md`.
  - Datadog mobile session replay privacy options.
  - Apple DocC JSON: `RedactionReasons.privacy`, `View.redacted(reason:)`, `WKWebView.isInspectable`, `SCContentFilter`, `SCStreamFrameInfo`, `UIScreen.isCaptured`, "Protecting sensitive content when screen sharing".
  - Sentry Apple custom redact (`sentry-docs` raw).
  - Repo ngoài: `appium-xcuitest-driver` docs (`capabilities.md`, `settings.md`, `execute-methods.md`, `hybrid.md`, `wda-slowness.md`); `appium-mac2-driver` docs (`capabilities.md`, `execute-methods.md`, `accessibility-permission.md`).
- *Web-snippet:*
  - docs.sentry.io Android replay privacy; appium#9147; discuss.appium.io (page source chậm, DOM iOS lớn 57 s); lanbaoshen.github.io (accessibility conflict); source.android.com DND; androidauthority (Android 15 sensitive notifications).
  - jessesquires.com (`simctl status_bar` hỏng); WWDC20 10647; tidbits, 9to5mac (Sequoia hỏi hằng tháng); Apple forums 808016.
  - learn.microsoft.com (`SetWindowDisplayAffinity`, hiệu năng UIA); mirror commit Electron; lightrun (pywinauto); ayosec ffmpeg-filters `ddagrab`; unpkg appium-uiautomator2-driver README.

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

Vòng desktop/mobile: gốc `/tmp/claude-0/-home-user-demo-studio/93a734b2-3873-5432-9c4d-49479b80e3ba/scratchpad/exp2/` (thư mục tạm; generator và script đo được commit ở P0-native, §8). Hầu hết cấu hình chạy 1 lần.
- **android/** (không có emulator; toàn bộ là mô phỏng): E1 khả thi emulator (thất bại: không KVM, `dl.google.com` 403); E2 overlay khi cuộn (S0 là hình học, 0 do cách dựng); E3 VFR + stamp; E4 lệch đồng hồ so với pad; E5 chi phí `sendcmd`.
- **apple/** (mô phỏng): E1 snapshot thưa, still-window; E3 render segment hằng + verify.
- **desktop/** (đo-Linux, Xvfb không compositor): D1 Electron (D1b `addInitScript` sau launch, D1c hook, n=1); D2 GTK + user CSS + log vị trí; D3 overlay X11 (mỗi cấu hình n=1, app tổng hợp tự cuộn, không click); D4 chi phí AT-SPI; R1 nghiên cứu Windows/macOS.
- **posthoc-tracking/** (clip tổng hợp): A1–A5 offset, lerp, tracker; B1–B6 OCR, mosaic, stress, budget, alltext; C1 pts so với index.

### Repo
- `plugins/demo-studio/agents/privacy-blurrer.md:3,14-23,29`
- `agents/render-engineer.md:14-24`
- `agents/demo-qa.md:14`
- `agents/app-scout.md:29`
- `agents/demo-director.md:13,27,51,54,68-69`
- `commands/{cut,fix,new,rerecord,review,revoice,run,script,shoot,tools}.md`
- `skills/media-specs/SKILL.md:24,36-44,50-54,70-76`
- `skills/run-kits/SKILL.md:8,24`
- `skills/platform-automation/references/web.md:74`, `mobile.md:38`, `desktop.md:13-23,44,75`
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

### Phản biện desktop/mobile

Verdict red-team (vòng 2, cho §6.7 và các chỉnh sửa liên quan): `revise`. 19 issue: 3 blocker, 13 major, 3 minor. Chấp nhận 19/19 (RTn-9 và RTn-17 chấp nhận có điều chỉnh, ghi ở cột thay đổi). Từ chối 0.

| # | Mục | Issue (tóm tắt) | Mức | Quyết định | Thay đổi |
|---|---|---|---|---|---|
| RTn-1 | 6.7.2 Linux T2 / 6.7.3 rule 1 | Cấu hình pass (pad24+guard40, pad64+guard80) nhỏ hơn công thức pad; công thức chưa từng được đo; mỗi cấu hình 1 run, Xvfb không compositor | major | accepted | Ghi lại kết quả đúng như đo (n=1, không compositor); công thức gắn nhãn "bảo thủ, suy ra từ D3, chưa đo"; tiêu chí 24 thêm sweep ≥ 3 run ở pad theo công thức và case picom. |
| RTn-2 | 6.7.1 / Android T1 / Same-frame | Android S0 0/360 là hình học, 0 do cách dựng, đặt cạnh số đo thật | major | accepted | Bỏ khỏi danh sách bằng chứng; nhãn "mô phỏng hình học, không phải bằng chứng; thư viện chưa viết" ở §6.7.1, bảng §6.7.2, §6.7.3. |
| RTn-3 | 6.7.2 vs §8 / X21 | Bảng trình bày như đã có các tầng chỉ đến ở P3 hoặc chưa quyết; G1 đề nghị T2 không tồn tại; macOS không có mặc định trước P3 | blocker | accepted | Cột "Có từ" (P0-native/P1/P2/P3); G1 chỉ hỏi trong `available_tiers`; Android T1 = "copy snippet + rebuild"; hàng macOS H⁻ (avfoundation display + cover ngoài cửa sổ + T3/T4) là mặc định trước P3. |
| RTn-4 | 6.7.2 Electron T1 | "≈0 setup cho mọi app Electron" sai với app đóng gói có fuse; preload chỉ có stylesheet, lệch thiết kế web; D1c n=1 | major | accepted | Preload chạy toàn bộ `privacy_mask.js` ở main world, dùng assertion và gate web; probe `@electron/fuses read` trước G1; trạng thái "đo-Linux n=1, biến thể stylesheet; app dev/unpackaged"; X15, tiêu chí 23. |
| RTn-5 | 6.7.6 / 6.7.1 | Thiếu đường lộ PII của OS trên mobile: gợi ý bàn phím, autofill, clipboard, `show_password`, popup phím + `show_touches`, heads-up (`set_dnd alarms`), recents | blocker | accepted | §6.7.6 thêm hàng bàn phím/autofill/clipboard, `set_dnd none`, `show_password 0`, IME không học, recents; §6.7.5 mục 13 nhập qua `setValue`; iOS ưu tiên simulator, tắt QuickType/autofill; nguyên tắc 8; D22, R30, tiêu chí 32. Tất cả chưa test. |
| RTn-6 | 6.7.2 overlay desktop | Cửa sổ top-level mới không được poll; overlay GTK POPUP chặn click; re-walk không giới hạn | major | accepted | Input shape rỗng; sự kiện `window:create`/`children-changed`/UIA `WindowOpened`; cửa sổ lạ → cover cả vùng; re-walk ≤ 200 ms; rule T2 mục 5–6; test click-through ở tiêu chí 24. |
| RTn-7 | 6.7.3 T2 / guard.arm | `v_max` không ép được khi fling; "2 frame trước" không định nghĩa được | major | accepted | Primitive `ds.scroll` (kéo ≤ `v_max`, giữ ~100 ms trước khi nhấc); guard là handshake có ack `guard painted` (timeout 500 ms → exit 11); lint chặn swipe trần khi T2. |
| RTn-8 | 6.7.5 mục 9 | So recording với screenshot vô dụng vì screencap cũng bị FLAG_SECURE; blackdetect báo nhầm dark theme | major | accepted | Kiểm cờ trực tiếp (`dumpsys window`, `GetWindowDisplayAffinity`, `kCGWindowSharingState`) + view hierarchy có text mà frame đồng nhất; blackdetect chỉ phụ, yêu cầu luma gần đồng nhất. |
| RTn-9 | 6.7.4 budget / verify | Budget `track` mặc định thấp hơn ước tính của chính nó cho clip dài; verify stride 5 s trong 300 s cố định luôn exit 3 và bỏ sót toast | major | accepted (điều chỉnh) | `track` mặc định `max(60, 1.5 × estimate)`, in ở G1; verify non-web det-only + rec trên box, change gate dùng detector của `track`, budget `max(300, 1.5 × estimate)`. Số det-only 0.17–0.8 s là của red-team, ghi **suy luận**, đo lại ở P1. |
| RTn-10 | Lệnh rerecord/revoice/cut/fix | Không nói artefact mới đi qua các lệnh hiện có thế nào; fingerprint thiếu tier/thiết bị/mask kit; cut và retime làm box lệch | blocker | accepted | §6.7.8 mới: burn mask vào clip source theo pts trước mọi retime/reframe; cut không biến đổi box; rerecord chạy đủ adapter; fingerprint thêm tier, thiết bị + OS, hash mask kit, hash timebase; map fix.md; tiêu chí 31. |
| RTn-11 | 6.7.2 thiếu platform | Thiếu Tauri, mobile web, split view/foldable, JVM desktop, MAUI/Catalyst, đa màn hình | major | accepted | Thêm hàng Tauri, mobile web, JVM desktop, MAUI/Catalyst; split view cấm hoặc T4 phủ pane khác; T2 yêu cầu một màn hình scale cố định (probe kiểm). Tất cả chưa test. |
| RTn-12 | Map DPI/Retina/xoay | Crop, xoay khi khoá orientation, `--max-size`, cửa sổ trải hai display, toạ độ âm làm rect lệch | major | accepted | Hàm `transform` duy nhất lưu ở `events.clips.<sid>.transform` (nguyên tắc 5); probe hình thử màu cho mọi platform, cả landscape; cấm `--max-size` khi T3 (hoặc pad ≥ 6 px); tiêu chí 27, R28. |
| RTn-13 | 6.7.6 khôi phục / bước không giới hạn | Crash hoặc mất adb để thiết bị ở demo mode/DND/IME mới; TCC prompt, build WDA, dừng recorder, tìm pid không giới hạn | major | accepted | `hygiene.json` ghi trước khi đổi, khôi phục ở lần `capture.py` kế tiếp; TCC preflight không tương tác ≤ 10 s; WDA ≤ 600 s; recorder SIGINT → 10 s → KILL → ffprobe; tìm pid ≤ 10 s; tiêu chí 29. |
| RTn-14 | 6.7.5 mục 1 iOS/macOS | "100% frame được redact" không kiểm được khi không có log; `.redacted` lộ độ dài | major | accepted | Snippet bắt buộc ghi log `n_rules/n_matched` + rect ≥ 1/s; assertion đối chiếu identifier từ G1; không log → `T1-unverified`, phải kèm T3 still-window; mặc định lớp đục, `.redacted` chỉ cho mục ít nhạy cảm. |
| RTn-15 | §1.6 / X6 | Thay toàn bộ §1.6 làm mất "bbox DOM log theo frame" của web | major | accepted | §1.6 giữ thứ tự web, thêm thứ tự riêng cho non-web; X6 ghi "áp cho web", non-web theo X16/X17. |
| RTn-16 | 6.7.4 exit code `track` | Exit 4 + `--allow-failclosed` mâu thuẫn với route §4.2; exit 11 không được route | minor | accepted | Có cờ: exit 0, verdict `failclosed`, advisory ở G2; không cờ: exit 4. Exit 11 route như leak (owner blur, block delivery). |
| RTn-17 | §8 phase | P0 phình gấp đôi, làm chậm bản sửa web; Linux GTK/overlay tốn công cho target ít dùng; không có bằng chứng sử dụng | major | accepted (điều chỉnh) | Tách P0-web (giữ nguyên) và P0-native (timebase, lint pts, T4, Electron kit, lint phương pháp cấm). `track` sang P1 sau cờ. Linux GTK/overlay sang P2 trừ khi chủ repo xác nhận. Thêm R29 hỏi xếp hạng platform. Giữ regex chịu lỗi OCR trong P0-native vì rẻ và dùng chung với `verify`. |
| RTn-18 | §10 khả năng tái lập | Số then chốt nằm ở `/tmp` sẽ bị xoá; không ghi số run | minor | accepted | P0-native commit generator và script đo vào `scripts/tests/fixtures/exp2/` kèm README số run; mọi ô đo-Linux ghi `n=`. |
| RTn-19 | Windows toast / gdigrab | Đặt cửa sổ ở 0,0 vẫn có thể chồng toast; Focus Assist là suy luận; chưa rõ gdigrab bắt cửa sổ layered | minor | accepted | Cửa sổ kích thước cố định trong work area, tránh góc toast, probe kiểm; Do Not Disturb là bước tay ở G1, kiểm bằng toast thử; hình thử màu bắt buộc cho cả `ddagrab` và `gdigrab`. |
