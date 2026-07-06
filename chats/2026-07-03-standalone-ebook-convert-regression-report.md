# Standalone ebook-convert 整改回归报告

- 日期：2026-07-03
- 分支：`only-ebook-convert`
- 最新提交：`076dd89c6a Embed CJK font for standalone PDF output`
- 关联审查文档：
  - `chats/2026-07-02-standalone-ebook-convert-qa.md`
  - `chats/2026-07-02-standalone-ebook-convert-fix-brief.md`

## 结论

整改任务书里的关键项已经处理并完成回归：

- PDF 输出中文不再变成 `?`。
- PDF 输出已嵌入 standalone CJK 字体。
- `pdftotext` 可以从生成的 PDF 中抽取中文。
- Linux 和 macOS 都跑过 smoke。
- Linux 和 macOS 都跑过真实 samples 矩阵，结果均为 `29/29 ok`。
- no-Qt、拒绝不支持格式、PDF 输入、Pillow 图片路径等既有能力未被破坏。

## 本轮修复内容

### PDF 输出中文

原问题是 `StandalonePDFOutput` 使用 Latin-1 写 PDF 文本，非 Latin-1 字符会被替换为 `?`。

当前实现改为：

- PDF 字体使用 `CIDFontType2` / `Identity-H`。
- 包内携带 `resources/fonts/standalone-cjk.ttf` 或 `standalone-cjk.ttc`。
- PDF 输出时嵌入该 CJK 字体。
- 文本用 UTF-16BE hex string 写入。
- 写入 ToUnicode CMap，保证文本可复制、可由 `pdftotext` 抽取。
- 生成 CIDToGIDMap，避免只“可抽取”但不可显示。

实测 `pdffonts` 输出确认：

```text
name            type          encoding    emb sub uni
StandaloneCJK   CID TrueType  Identity-H  yes no  yes
```

### 测试补强

`setup/standalone_ebook_convert_smoke.py`：

- seed 文本加入中文 sentinel：`这是中文测试`。
- 所有 `* -> pdf` 输出均用 `pdftotext` 校验中文内容。
- 包结构校验要求存在 `resources/fonts/standalone-cjk.ttf` 或 `.ttc`。

`setup/standalone_ebook_convert_sample_matrix.py`：

- 样本矩阵从旧的单目标扩展为多目标：
  - `epub -> mobi`
  - `epub -> pdf`
  - `mobi -> epub`
  - `mobi -> pdf`
  - `pdf -> txt`
  - `txt -> epub`
  - `txt -> pdf`
- PDF 输出结果使用 `pdftotext` 校验：
  - CJK 字符数不能过低。
  - `?` 数量不能异常。

### 打包补强

本地打包脚本和 bypy 打包路径都会复制 CJK 字体：

- `setup/build_standalone_ebook_convert_linux_local.py`
- `setup/build_standalone_ebook_convert_local.py`
- `bypy/linux/__main__.py`
- `bypy/macos/__main__.py`

如果构建环境找不到 CJK 字体，打包会失败，避免生成“看似可用但中文 PDF 不可显示”的包。

Linux 容器中使用：

```text
/usr/share/fonts/truetype/wqy/wqy-microhei.ttc
```

macOS 本机使用：

```text
/System/Library/Fonts/Supplemental/Arial Unicode.ttf
```

### 入口参数校验

`src/calibre/ebooks/conversion/standalone_binary.py` 不再直接取 `args[1]` / `args[2]`。

当前逻辑会从命令行中定位前两个带扩展名的 positional 参数，并仍然遵循 calibre CLI 的调用形态：

```bash
ebook-convert INPUT OUTPUT [options...]
```

## 回归验证记录

### 自测

命令：

```bash
python3 setup/standalone_ebook_convert_smoke.py --self-test
```

结果：

```text
standalone ebook-convert self-test ok
```

### Linux 构建

容器：

```text
calibre-linux-ebook-convert-test
```

构建命令：

```bash
docker exec calibre-linux-ebook-convert-test sh -lc \
  'set -o pipefail; python3 /work/setup/build_standalone_ebook_convert_linux_local.py \
  --output /out/calibre-ebook-convert-noqt-linux-arm64 \
  2>&1 | tee /out/linux-build-cjk-embed.log'
```

结果：

```text
Package: /out/calibre-ebook-convert-noqt-linux-arm64
Archive: /out/calibre-ebook-convert-noqt-linux-arm64.tgz
Archive size: 68.48 MB
```

### Linux smoke

命令：

```bash
docker exec calibre-linux-ebook-convert-test sh -lc \
  'set -o pipefail; python3 /work/setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports --max-package-mb 190 \
  --work-dir /out/linux-smoke-cjk-embed \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  2>&1 | tee /out/linux-smoke-cjk-embed.log'
```

结果：通过。

额外字体确认：

```bash
docker exec calibre-linux-ebook-convert-test sh -lc \
  'pdffonts /out/linux-smoke-cjk-embed/seed.pdf; \
  /out/calibre-ebook-convert-noqt-linux-arm64/bin/pdftotext \
  /out/linux-smoke-cjk-embed/seed.pdf - | sed -n "1,20p"'
```

关键输出：

```text
StandaloneCJK  CID TrueType  Identity-H  yes  no  yes
# Standalone ebook-convert smoke test 这是中文测试，用于确认 PDF 输出不会丢失非 Latin-1 字符。
```

### Linux package/archive validation

命令：

```bash
docker exec calibre-linux-ebook-convert-test sh -lc \
  'python3 /work/setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports --max-package-mb 190 \
  --package-root /out/calibre-ebook-convert-noqt-linux-arm64 && \
  python3 /work/setup/standalone_ebook_convert_smoke.py \
  --archive /out/calibre-ebook-convert-noqt-linux-arm64.tgz \
  --max-archive-mb 90'
```

结果：通过。

### Linux samples matrix

命令：

```bash
docker exec calibre-linux-ebook-convert-test sh -lc \
  'set -o pipefail; python3 /work/setup/standalone_ebook_convert_sample_matrix.py \
  --timeout 900 \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  /work/samples/ca-format-samples \
  /out/linux-sample-matrix-cjk-embed \
  2>&1 | tee /out/linux-sample-matrix-cjk-embed.log'
```

结果：

```text
Sample matrix: 29/29 ok
Report: /out/linux-sample-matrix-cjk-embed/sample-results.tsv
```

PDF 输出样本摘要：

```text
EPUB -> PDF: pdf text CJK chars: 19958 / 24312
MOBI -> PDF: pdf text CJK chars: 20052 / 2137600
TXT  -> PDF: pdf text CJK chars: 11789 / 83765
```

### macOS 构建

命令：

```bash
/opt/homebrew/opt/python@3.14/bin/python3.14 \
  setup/build_standalone_ebook_convert_local.py \
  --output /private/tmp/calibre-ebook-convert-noqt-macos
```

结果：

```text
Package: /private/tmp/calibre-ebook-convert-noqt-macos
Archive: /private/tmp/calibre-ebook-convert-noqt-macos.tar.xz
Archive size: 37.93 MB
```

### macOS smoke

命令：

```bash
python3 setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports --max-package-mb 160 \
  --work-dir /private/tmp/calibre-ebook-convert-noqt-macos-smoke-cjk-embed \
  /private/tmp/calibre-ebook-convert-noqt-macos/ebook-convert
```

结果：通过。

额外字体确认：

```bash
pdffonts /private/tmp/calibre-ebook-convert-noqt-macos-smoke-cjk-embed/seed.pdf
/private/tmp/calibre-ebook-convert-noqt-macos/bin/pdftotext \
  /private/tmp/calibre-ebook-convert-noqt-macos-smoke-cjk-embed/seed.pdf -
```

关键输出：

```text
StandaloneCJK  CID TrueType  Identity-H  yes  no  yes
# Standalone ebook-convert smoke test 这是中文测试，用于确认 PDF 输出不会丢失非 Latin-1 字符。
```

### macOS samples matrix

命令：

```bash
python3 setup/standalone_ebook_convert_sample_matrix.py \
  --timeout 900 \
  /private/tmp/calibre-ebook-convert-noqt-macos/ebook-convert \
  samples/ca-format-samples \
  /private/tmp/calibre-ebook-convert-noqt-macos-sample-matrix-cjk-embed
```

结果：

```text
Sample matrix: 29/29 ok
Report: /private/tmp/calibre-ebook-convert-noqt-macos-sample-matrix-cjk-embed/sample-results.tsv
```

## 最终产物

Linux：

```text
dist/calibre-ebook-convert-noqt-linux-arm64.tgz
size: 68M
sha256: 1989d4c6bb0ebdac7256f7d855418029780e0fa34194d8e3b42c895df98dc4e4
```

macOS：

```text
dist/calibre-ebook-convert-noqt-macos-arm64.tgz
size: 38M
sha256: 6c252fdcaa9ad6ced6b06d938f5577704cd42ffb2eaa2a524e5fc4b4f3d0bd40
```

## 已知限制

- PDF 输出是轻量文本 PDF，能显示和抽取 Unicode/CJK 文本，但不保留复杂 HTML/CSS/图片排版。
- 每个 PDF 输出都会嵌入完整 standalone CJK 字体，因此 PDF 文件会比纯文本内容大。
- MOBI 中转不是无损链路；嵌入字体、CSS 背景装饰图、透明度、布局可能丢失，这是 MOBI 中间格式固有限制。
- standalone 禁用了 Qt SVG rasterizer，SVG 不会被栅格化为位图。
- 大书转换耗时明显；28MB、1415 章样本的 `epub -> mobi -> epub` 回环实测接近 24 分钟。

## 未提交/未纳入代码库的本地项

```text
.claude/
.codex/
.story/
.trae/
chats/
samples/
```

`chats/` 和 `samples/` 是本地 QA/样本材料，不在代码提交中。
