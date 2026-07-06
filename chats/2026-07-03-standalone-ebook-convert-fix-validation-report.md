# Standalone ebook-convert 整改与复测报告

日期：2026-07-03

## 结论

已按 `chats/2026-07-02-standalone-ebook-convert-fix-brief.md` 后续暴露的问题继续整改并重测。

本次新增修复重点是样本 parity：`samples/ca-format-samples` 中原版 calibre 8.5.0 能成功处理的 `azw/azw3/docx/original_epub/prc/zip` 输入，standalone 现在不再被入口直接拒绝。其中：

- `azw/azw3/prc` 走 `MOBIInput`
- `original_epub` 走 `EPUBInput`
- `zip` 走 calibre archive 预处理后再进入真实输入插件
- `docx` 走 `DOCXInput`，并修复 DOCX 图片路径导入 Qt 的问题

输出格式仍保持 `epub/mobi/pdf/txt`，没有放开完整 calibre 的输出面。

2026-07-04 继续用本地可信 `talebook/talebook:latest` 镜像做 reference 后，又补了 PDF 输出 parity：

- 文本 PDF：中文长段落按 CJK 宽度保守折行，避免右侧文本超出页面后被 `pdftotext` 丢弃。
- 图片页 PDF：对扫描版/图片页书籍，按 spine 中 `<img>` 顺序生成每图一页的 PDF，避免退化为一页标题。
- PDF 对比脚本对 `pdf` 目标改用正文长度、CJK 数量和 `?` 占位比例判定，不用 `SequenceMatcher` 判断 PDF 抽取顺序。

## 修改内容

- `src/calibre/ebooks/conversion/standalone_binary.py`
  - 输入和输出格式分开校验。
  - 输入允许：`azw/azw3/docx/epub/mobi/original_epub/pdf/prc/txt/zip`。
  - 输出允许：`epub/mobi/pdf/txt`。

- `src/calibre/customize/standalone_builtins.py`
  - 加入 `DOCXInput`。
  - 加入 DOCX metadata reader。

- `src/calibre/ebooks/docx/images.py`
  - standalone 环境下改用 `calibre.utils.standalone_img`，避免导入 Qt 版 `calibre.utils.img`。

- `src/calibre/utils/standalone_img.py`
  - 补 `resize_to_fit()`，供 DOCX 图片缩放路径使用。

- `src/calibre/ebooks/conversion/plugins/standalone_pdf_output.py`
  - 修复中文无空格长段落折行。
  - 对扫描页/图片页书籍生成 image-page PDF。

- `setup/build_standalone_ebook_convert_linux_local.py`
  - Linux 本地构建 overlay 加入 `calibre/ebooks/docx/images.py`。

- `setup/standalone_ebook_convert_smoke.py`
  - 更新入口校验自测：新增输入格式允许，`doc` 仍拒绝，`docx` 输出仍拒绝。

- `setup/standalone_ebook_convert_sample_matrix.py`
  - 样本矩阵加入新增输入格式到 EPUB 的验证。
  - 跳过 `.DS_Store` 等点文件，避免把非书籍文件计入样本统计。

- `setup/standalone_ebook_convert_reference_compare.py`
  - 新增 standalone 与 reference `ebook-convert` 的文本对比工具。

- `docs/standalone-ebook-convert.md`
  - 更新支持范围、实现说明、验证结果、限制说明和 Linux tgz hash。

## Linux 构建产物

容器：`calibre-linux-ebook-convert-test`

镜像：`debian:13-slim`

构建命令：

```bash
python3 /work/setup/build_standalone_ebook_convert_linux_local.py \
  --output /out/calibre-ebook-convert-noqt-linux-arm64
```

结果：

```text
/out/calibre-ebook-convert-noqt-linux-arm64.tgz
size: 68.49 MB
sha256: 8ec0253272a9ca7a56323cebbd7f694b471884697bbe4cf1b7b884ca63ac41ce
```

已同步到：

```text
dist/calibre-ebook-convert-noqt-linux-arm64.tgz
```

## 已执行验证

本地 self-test：

```bash
python3 setup/standalone_ebook_convert_smoke.py --self-test
```

结果：

```text
standalone ebook-convert self-test ok
```

Linux smoke：

```bash
python3 /work/setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports \
  --package-root /out/calibre-ebook-convert-noqt-linux-arm64 \
  --archive /out/calibre-ebook-convert-noqt-linux-arm64.tgz \
  --max-package-mb 190 \
  --max-archive-mb 90 \
  --work-dir /out/linux-smoke-input-expansion-2 \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert
```

结果：通过。

DOCX 单样本复现验证：

```text
DOCX/1321-Gao Zhi Shang Fan Zui - Zi Jin Chen.docx -> epub
rc=0
output_size=223819
InputFormatPlugin: DOCX Input running
```

真实样本矩阵：

```bash
python3 /work/setup/standalone_ebook_convert_sample_matrix.py \
  --timeout 900 \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  /work/samples/ca-format-samples \
  /out/linux-sample-matrix-input-expansion-3
```

结果：

```text
Sample matrix: 29/29 ok
Report: /out/linux-sample-matrix-input-expansion-3/sample-results.tsv
```

reference 对比：

```bash
python3 /work/setup/standalone_ebook_convert_reference_compare.py \
  --reference /usr/bin/ebook-convert \
  --standalone /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  --samples-dir /work/samples/ca-format-samples \
  --output-dir /out/reference-compare-nonpdf-input-expansion \
  --targets epub,mobi,txt \
  --timeout 900
```

结果：

```text
Reference comparison: ok=41, same_fail=16, standalone_extra=6
Report: /out/reference-compare-nonpdf-input-expansion/reference-compare.tsv
```

解释：

- `ok=41`：standalone 与 reference 都成功，抽取文本通过长度、CJK 数量、相似度校验。
- `same_fail=16`：双方都失败，主要是 `doc/ebk3/png/wps` 等当前边界外样本。
- `standalone_extra=6`：均为 PDF 输入到 `epub/mobi/txt`。Debian 容器里的 `/usr/bin/ebook-convert` 对这两个 PDF 样本返回 `1`，standalone 返回 `0`；这说明 Debian reference 环境不适合判断 PDF parity。PDF 输入已由 standalone smoke 和 sample matrix 单独验证。

Talebook reference 对比：

容器镜像：`talebook/talebook:latest`

容器内原版：

```text
/usr/bin/ebook-convert
ebook-convert (calibre 8.5.0)
/usr/bin/pdftotext
Debian GNU/Linux 13 (trixie)
```

PDF 输出对比：

```bash
QTWEBENGINE_DISABLE_SANDBOX=1 python3 /tmp/standalone_ebook_convert_reference_compare.py \
  --reference /usr/bin/ebook-convert \
  --standalone /tmp/standalone/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  --samples-dir /tmp/ca-format-samples \
  --output-dir /tmp/reference-compare-talebook-pdf-final \
  --targets pdf \
  --exclude-sample "MOBI/54-*" \
  --timeout 900
```

结果：

```text
Reference comparison: ok=15, same_fail=5
Report: /tmp/reference-compare-talebook-pdf-final/reference-compare.tsv
```

说明：

- `ok=15`：双方 PDF 输出成功，`pdftotext` 抽取后的正文长度、CJK 数量和 `?` 占位比例通过。
- `same_fail=5`：双方都失败，覆盖边界外样本。
- `MOBI/54... -> pdf` 在 talebook 原版 QtWebEngine 路径下失败且资源消耗很高，未作为 PDF parity 成功样本计入。

非 PDF 输出对比：

```bash
python3 /tmp/standalone_ebook_convert_reference_compare.py \
  --reference /usr/bin/ebook-convert \
  --standalone /tmp/standalone/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  --samples-dir /tmp/ca-format-samples \
  --output-dir /tmp/reference-compare-talebook-nonpdf-final \
  --targets epub,mobi,txt \
  --timeout 900
```

结果：

```text
Reference comparison: ok=41, same_fail=16, standalone_extra=6
Report: /tmp/reference-compare-talebook-nonpdf-final/reference-compare.tsv
```

解释：

- `ok=41`：双方都成功，抽取文本通过长度、CJK 数量、相似度或 hash 校验。
- `same_fail=16`：双方都失败，主要是边界外样本。
- `standalone_extra=6`：均为两个 PDF 样本输入到 `epub/mobi/txt`。talebook 原版默认 PDF reflow XML 路径触发 `lxml.etree.XMLSyntaxError: Input is not proper UTF-8`，standalone 默认 `pdftohtml` 路径成功；这是 standalone 的额外修复能力，不是输出 parity 缺口。

## Talebook 镜像说明

最终 reference 使用的是本地 `talebook/talebook:latest`，不是 `talebook/calibre-docker:8.5`。

## 剩余限制

- 输出格式仍只支持 `epub/mobi/pdf/txt`。
- PDF 输出仍是轻量 PDF，不追求复杂 HTML/CSS 视觉排版还原；文本 PDF 和扫描图片页 PDF 已按样本验证。
- standalone 不包含 Qt SVG rasterizer，MOBI 输出里的 SVG 不会被栅格化为位图。
- 大 PRC/MOBI/ZIP 样本耗时明显，矩阵和 reference compare 均使用 900 秒单项 timeout。
