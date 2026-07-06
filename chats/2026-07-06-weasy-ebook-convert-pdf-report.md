# WeasyPrint ebook-convert-pdf 实现与验证报告

日期：2026-07-06

## 结论

已新增独立工具 `ebook-convert-pdf`，使用 WeasyPrint 作为 PDF 输出引擎。

这个工具没有并入轻量 `ebook-convert` standalone 包，而是作为单独的 PDF 增强包存在。
原因是 WeasyPrint 带来 Pango/Cairo/Fontconfig/字体等依赖，运行面和包体都比轻量包更重。

## 实现

新增文件：

- `src/calibre/ebooks/conversion/weasy_pdf_binary.py`
- `setup/build_standalone_ebook_convert_pdf_linux_local.py`
- `setup/standalone_ebook_convert_pdf_sample_matrix.py`
- `docs/standalone-ebook-convert-pdf.md`

转换流程：

1. 校验输入格式和 `.pdf` 输出。
2. 调用 calibre 输入插件，把输入书转换成临时 OEB 目录。
3. 解析 OEB 的 OPF manifest/spine。
4. 拼接 spine XHTML，修正资源 URL。
5. 用 WeasyPrint 写出 PDF。

支持输入：

```text
azw, azw3, docx, epub, mobi, original_epub, pdf, prc, txt, zip
```

输出固定为：

```text
pdf
```

## 构建

构建镜像：

```text
talebook/ebook-convert-pdf-build:weasy
```

该镜像基于本地可信 `talebook/talebook:latest`，安装：

```text
weasyprint python3-cffi python3-pydyf python3-tinycss2
python3-cssselect2 python3-pyphen python3-ply fonts-wqy-microhei
```

最终产物：

```text
/private/tmp/calibre-weasy-build-output/calibre-ebook-convert-pdf-weasy-linux-arm64.tgz
dist/calibre-ebook-convert-pdf-weasy-linux-arm64.tgz
```

大小：

```text
uncompressed: 217 MB
archive: 75.44 MB
sha256: 2f914d09dfde7415ace67d7f56a05547e28323e2f8da6557faf111035755207b
```

## 验证

### Clean Debian smoke

在 `debian:13-slim` 中运行包内二进制：

```text
txt -> pdf: ok
pdftotext 抽取中文: ok
```

抽取文本包含：

```text
Standalone WeasyPrint PDF smoke 这是中文测试，用于确认 ebook-convert-pdf 可以独立
```

### 样本矩阵

命令：

```bash
PKG=/pkg/calibre-ebook-convert-pdf-weasy-linux-arm64
PYTHONHOME=$PKG PYTHONPATH=$PKG/lib/python/site-packages LD_LIBRARY_PATH=$PKG/lib \
  $PKG/bin/python3 /work/setup/standalone_ebook_convert_pdf_sample_matrix.py \
  --timeout 900 \
  $PKG/ebook-convert-pdf \
  /work/samples/ca-format-samples \
  /out/pdf-sample-matrix
```

结果：

```text
PDF sample matrix: 23/23 ok
Report: /out/pdf-sample-matrix/pdf-sample-results.tsv
```

覆盖结果：

- `azw/azw3/docx/epub/mobi/original_epub/pdf/prc/txt/zip -> pdf` 全部成功。
- `doc/ebk3/png/wps` 按预期拒绝。
- 大 MOBI `MOBI/54...` 成功，输出 6939 页，但耗时很长。
- 两个 PDF 输入样本均成功：
  - `PDF/183...pdf -> pdf`: 254 页，99,268 CJK chars
  - `PDF/187...pdf -> pdf`: 250 页，88,851 CJK chars

### Talebook reference compare

命令：

```bash
QTWEBENGINE_DISABLE_SANDBOX=1 python3 /work/setup/standalone_ebook_convert_reference_compare.py \
  --reference /usr/bin/ebook-convert \
  --standalone /pkg/calibre-ebook-convert-pdf-weasy-linux-arm64/ebook-convert-pdf \
  --samples-dir /work/samples/ca-format-samples \
  --output-dir /out/reference-compare-weasy-pdf-excl-big-mobi \
  --targets pdf \
  --exclude-sample "MOBI/54-*" \
  --timeout 900
```

结果：

```text
Reference comparison: ok=15, same_fail=5
Report: /out/reference-compare-weasy-pdf-excl-big-mobi/reference-compare.tsv
```

说明：

- `ok=15`：原版 calibre 和 `ebook-convert-pdf` 都成功，抽取文本长度/CJK 数量校验通过。
- `same_fail=5`：双方都失败，覆盖 `doc/ebk3/png/wps` 等边界外样本。
- 排除了 `MOBI/54-*`：完整 reference compare 在这个样本上运行超过 30 分钟仍未结束。样本矩阵已验证 `ebook-convert-pdf` 能成功转换该样本。

### PDF 输入手工对比

reference compare 脚本会跳过 `input_ext == target_ext`，所以手工测试了两个 `PDF -> PDF`。

结果：

- talebook 原版 `/usr/bin/ebook-convert PDF -> PDF` 均失败。
- `ebook-convert-pdf PDF -> PDF` 均成功。

原版失败原因：

```text
lxml.etree.XMLSyntaxError: Input is not proper UTF-8
```

这是之前 PDF 输入路径的同一类问题；新工具沿用 standalone PDF input 的 `pdftohtml` 路径，因此成功。

## 风险和限制

- WeasyPrint 不是 QtWebEngine；文本内容保留对齐，但不承诺逐像素排版一致。
- 包体比轻量 standalone 包大：75.44 MB tgz，217 MB 解压目录。
- 大 MOBI/PRC 输入耗时明显，尤其 `MOBI/54...`。
- 部分样本的 `SequenceMatcher` 相似度低，但长度和 CJK 数量一致；原因是 PDF 内部文本抽取顺序可能不同。
- 扫描页 PDF 可有效生成，但 `pdftotext` 文本可能为空，这是图片页 PDF 的正常表现。
