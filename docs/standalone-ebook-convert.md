# Standalone ebook-convert 方案归档

本文记录 `only-ebook-convert` 分支中将 calibre 剪裁为独立 `ebook-convert`
交付物的调研、实现和验证过程。

## 目标

目标是从完整 calibre 中拆出一个只暴露 `ebook-convert` 的独立发布包，用于
EPUB、MOBI、PDF、TXT 之间的转换。

交付物不是完整 calibre，也不是单个静态 ELF/Mach-O 文件。当前方案是一个目录式
runtime bundle：

- 顶层提供一个可执行入口 `ebook-convert`。
- 包内自带 Python 解释器、Python 标准库和必要 third-party 包。
- 包内自带剪裁后的 calibre Python 代码、必要 native 插件和资源。
- 包内自带 Poppler helper，例如 `pdftohtml`、`pdfinfo`、`pdftoppm`、
  `pdftotext`。
- 包内收集运行所需的非 Qt 动态库，并通过 launcher 设置
  `PYTHONHOME`、`PYTHONPATH`、`LD_LIBRARY_PATH` 或 macOS 对应环境。

因此使用方不需要安装 calibre，也不需要安装 Python Qt/PyQt。Linux 产物仍然要求
运行系统具备兼容的 Linux 内核和基础 libc ABI，这和大多数 Linux 二进制包一致。

## 调研结论

完整 calibre 体积和依赖主要来自几类能力：

- GUI、viewer、editor、server、device 集成、recipe/news 抓取、AI/store 插件。
- Qt/PyQt/QtWebEngine 及其 transitive 动态库。
- 大量输入/输出格式插件和平台集成命令。
- Python 运行时、第三方包、native calibre 插件、字体和资源。

`ebook-convert` 的核心转换链路可以从完整 calibre 中剥离出来，但有几个关键点：

- 插件系统默认会加载大量内置插件，需要提供 standalone 插件列表或运行时过滤。
- PDF 输出默认走 QtWebEngine 相关路径，不适合 no-Qt 独立包。
- MOBI 输出中 SVG rasterizer 依赖 Qt；standalone 包中需要禁用这条路径。
- MOBI 读写和图片处理部分原本会导入 `calibre.utils.img`，该模块依赖 Qt native
  image 插件；standalone 包需要切换到 Pillow fallback。
- PDF 输入在部分中文 PDF 上使用默认解析路径会遇到 XML/编码问题，standalone 包中
  默认使用 `pdftohtml` 路径。
- Debian 打包版 calibre 和当前源码主线之间存在 API 差异，Linux 本地验证脚本不能
  粗暴覆盖所有当前源码文件，需要以 Debian 8.5 的代码为底座做最小补丁。

## 支持范围

用户可直接使用的格式被限制为：

- 输入：`epub`、`mobi`、`pdf`、`txt`
- 输出：`epub`、`mobi`、`pdf`、`txt`

入口层会拒绝其它扩展，返回码为 `2`。例如 `azw`、`azw3`、`doc`、`docx`、
`ebk3`、`original_epub`、`png`、`prc`、`wps`、`zip` 在当前 standalone
策略下都不会进入转换管线。

这是一种有意的边界控制：减少隐式依赖、避免把完整 calibre 的插件面重新带回来。

## 核心实现

### 入口限制

`src/calibre/ebooks/conversion/standalone_binary.py` 是 standalone 入口。

它做三件事：

- 设置 `CALIBRE_STANDALONE_CONVERTER=1`。
- 在 `CALIBRE_STANDALONE_FORBID_QT=1` 时安装 import guard，禁止导入 `qt` 和
  `PyQt6`。
- 在调用 calibre 原始 conversion CLI 之前校验输入/输出扩展，只允许
  `epub/mobi/pdf/txt`。

### 插件剪裁

`src/calibre/customize/standalone_builtins.py` 定义 standalone 内置插件集合，只保留：

- EPUB/MOBI/PDF/TXT 的 metadata reader/writer。
- EPUB/MOBI/PDF/TXT 输入输出插件。
- 内部转换需要的 `HTMLInput`、`OEBOutput`。
- input/output profile。

`src/calibre/customize/ui.py` 在 standalone 环境下加载上述插件列表，并避免导入
device 插件。

`src/calibre/customize/builtins.py` 不作为 standalone 运行时的插件源。运行时插件集合
只以 `standalone_builtins.py` 为准，避免和完整 calibre 的默认插件列表产生漂移。

### PDF 输出

`src/calibre/ebooks/conversion/plugins/standalone_pdf_output.py` 提供一个小型 PDF 输出插件。

它不使用 QtWebEngine，也不追求像素级 HTML/CSS 还原。实现方式是从 OEB spine 中提取
文本，按页面尺寸和字体大小换行，然后直接写出一个简单 PDF。包内携带一个 standalone
CJK 字体，PDF 以 `CIDFontType2`/`Identity-H` 嵌入该字体，正文以 UTF-16BE hex
string 写入，并带 ToUnicode CMap，用于显示和抽取中文等非 Latin-1 文本。

这个选择的取舍是：

- 优点：无 Qt/PyQt 依赖，中文文本可显示和抽取，适合作为转换服务中的基础 PDF 输出。
- 代价：复杂排版、图片、CSS 视觉效果不会完整保留。

入口校验假设调用形态和 calibre CLI 一致：输入文件和输出文件位于命令行前两个位置，
即 `ebook-convert INPUT OUTPUT [options...]`。

### PDF 输入

standalone 插件列表中的 `StandalonePDFInput` 克隆 calibre PDF 输入插件选项，并将
`pdf_engine` 默认值设为 `pdftohtml`。这条路径依赖包内 Poppler helper，避免默认 PDF
解析路径在部分中文 PDF 上触发编码/XML 解析失败。

### MOBI 和图片处理

MOBI 相关改动主要为 no-Qt：

- `mobi_output.py` 在 standalone 环境下禁用 `SVGRasterizer`，避免导入 Qt rasterizer。
- `mobi6.py`、`mobi/utils.py`、`mobi/writer2/resources.py` 在 standalone 环境下使用
  `calibre.utils.standalone_img`。
- `standalone_img.py` 使用 Pillow 实现基础图片读取、缩放、格式转换、cover 保存、
  GIF/PNG/JPEG 处理。

SVG 处理的结论：

- standalone MOBI 输出不会因为缺少 Qt SVG rasterizer 直接崩溃。
- 但 SVG 不会被 rasterizer 转成位图，日志中会出现
  `SVG rasterizer unavailable, SVG will not be converted`。
- EPUB 中普通位图图片、MOBI 中常规图片处理正常；复杂 SVG 视觉保真不作为当前目标。

### 退出清理

`src/calibre/utils/safe_atexit.py` 在 standalone 环境下不再走 calibre 的外部清理进程，
而是直接用 Python `atexit` 注册临时文件/目录清理，避免引入额外 calibre command。

### 本地打包脚本

新增了两个开发打包脚本：

- `setup/build_standalone_ebook_convert_local.py`
- `setup/build_standalone_ebook_convert_linux_local.py`

macOS 脚本从本机已构建源码、Python framework、venv site-packages、native plugins 和
Poppler helper 组装 no-Qt 目录，并生成 `.tar.xz`。

Linux 脚本在 Debian 容器内运行，以 Debian calibre 包为底座：

- 复制 `/usr/bin/python3.13` 和 `/usr/lib/python3.13`。
- 复制 `/usr/lib/python3/dist-packages` 中 allowlist 的 Python 包。
- 复制 `/usr/lib/calibre` 中的 calibre、polyglot、css_selectors、tinycss、odf。
- 只复制 allowlist 中的 native calibre 插件。
- 从 `/usr/share/calibre` 复制必要资源，并解引用 Debian 字体 symlink。
- 用当前 checkout 中的 standalone 新文件覆盖到包中。
- 对 Debian 8.5 的 `customize/ui.py` 和 MOBI 相关文件做最小文本补丁，而不是整文件覆盖。
- 用 `ldd` 递归收集非 Qt、非核心 glibc 的 ELF 依赖。
- 用 `strip --strip-unneeded` 缩小 ELF。
- 生成 `.tgz`。

Linux 脚本中特别排除了 Debian 中依赖 Qt 的 native 插件，例如 `imageops.so`、
`libheadless.so`、`pictureflow.so`、`progress_indicator.so`、`rcc_backend.so`。

## 验证工具

`setup/standalone_ebook_convert_smoke.py` 做 package-level 和功能级 smoke：

- 检查包根目录只暴露预期 surface。
- 禁止 Qt/PyQt/QtWebEngine 文件和 `libQt*` 动态依赖。
- 禁止 GUI、server、device、scraper 等 calibre 代码面进入包。
- 禁止额外 calibre command 暴露。
- 校验归档安全，拒绝绝对路径、`..` 路径、危险 symlink。
- 运行 `epub/mobi/pdf/txt` 互转矩阵。
- 验证 unsupported `docx` 和 recipe 能力被拒绝。

`setup/standalone_ebook_convert_sample_matrix.py` 用真实样本目录做矩阵验证：

- `epub -> mobi`
- `epub -> pdf`
- `mobi -> epub`
- `mobi -> pdf`
- `pdf -> txt`
- `txt -> epub`
- `txt -> pdf`
- 所有 PDF 输出都会用 `pdftotext` 抽取正文，校验中文字符数量和 `?` 占位比例。
- 其它格式预期被 standalone 入口拒绝，返回码 `2`，且不生成输出。

## Debian 容器验证记录

验证容器：

```bash
docker exec -it calibre-linux-ebook-convert-test bash
```

容器镜像：

```text
debian:13-slim
```

挂载：

```text
/work -> /Users/bytedance/github/calibre  只读
/out  -> /private/tmp/calibre-linux-build-output  可写
```

容器内安装的关键包：

```text
python3
calibre
poppler-utils
rsync
xz-utils
file
binutils
```

Linux 构建命令：

```bash
python3 /work/setup/build_standalone_ebook_convert_linux_local.py \
  --output /out/calibre-ebook-convert-noqt-linux-arm64
```

基础 smoke：

```bash
/out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert --version
python3 /work/setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports \
  --max-package-mb 180 \
  --package-root /out/calibre-ebook-convert-noqt-linux-arm64
python3 /work/setup/standalone_ebook_convert_smoke.py \
  --archive /out/calibre-ebook-convert-noqt-linux-arm64.tgz \
  --max-archive-mb 80
python3 /work/setup/standalone_ebook_convert_smoke.py \
  --forbid-qt-imports \
  --max-package-mb 180 \
  --work-dir /out/linux-smoke \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert
```

真实样本验证：

```bash
python3 /work/setup/standalone_ebook_convert_sample_matrix.py \
  --timeout 900 \
  /out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert \
  /work/samples/ca-format-samples \
  /out/linux-sample-matrix
```

结果：

```text
Sample matrix: 29/29 ok
```

说明：

- 两个 EPUB 样本成功转换为 MOBI 和 PDF。
- 两个 MOBI 样本成功转换为 EPUB 和 PDF。
- 两个 PDF 样本成功转换为 TXT。
- 两个 TXT 样本成功转换为 EPUB 和 PDF。
- 所有样本 PDF 输出都经过 `pdftotext` 抽取校验，要求含有足量中文且不是 `?` 占位。
- 其余格式样本按 standalone 边界被拒绝，返回码为 `2`。
- 21MB 的大 MOBI 样本超过 240 秒默认超时，因此最终用 900 秒超时验证通过。

最终 Linux 产物：

```text
dist/calibre-ebook-convert-noqt-linux-arm64.tgz
size: 68.48 MB
sha256: 1989d4c6bb0ebdac7256f7d855418029780e0fa34194d8e3b42c895df98dc4e4
```

容器内保留：

```text
/out/calibre-ebook-convert-noqt-linux-arm64/
/out/calibre-ebook-convert-noqt-linux-arm64.tgz
/out/linux-build.log
/out/linux-smoke.log
/out/linux-sample-matrix.log
/out/linux-sample-matrix/sample-results.tsv
```

## macOS 本地验证记录

macOS 本地开发包产物：

```text
dist/calibre-ebook-convert-noqt-macos-arm64.tgz
size: 37.93 MB
sha256: 6c252fdcaa9ad6ced6b06d938f5577704cd42ffb2eaa2a524e5fc4b4f3d0bd40
```

本地 macOS 验证覆盖：

- 包结构和归档安全。
- 无 Qt/PyQt/`libQt` 依赖。
- `epub/mobi/pdf/txt` 互转 smoke。
- 真实 PDF 样本转换，使用 `pdftohtml` 路径修复中文 PDF 问题。
- Debian 容器内对 macOS tgz 做归档 surface 校验。

## 当前限制和后续方向

当前实现是一个可验证的 no-Qt standalone `ebook-convert` 子集，不是完整 calibre 的替代品。

已知限制：

- 只支持 `epub/mobi/pdf/txt` 作为用户可见格式。
- PDF 输出是轻量文本 PDF，保留 Unicode/CJK 文本，但不保证复杂 HTML/CSS/图片排版。
  当前实现为每个 PDF 嵌入完整 standalone CJK 字体，因此 PDF 输出文件会比纯文本内容大。
- MOBI 输出中的 SVG rasterizer 被禁用，SVG 不保证转换为位图。
- 通过 MOBI 中转做 `epub -> epub` 回环不能视为无损：嵌入字体、CSS 背景装饰图、
  透明度和布局都可能丢失。这是 MOBI 中间格式的固有限制，不是 standalone 特有问题。
- standalone 额外缺少 Qt SVG rasterizer；正文或封面里的 SVG 不会被栅格化为位图。
- 大书转换耗时明显。28MB、1415 章样本的 `epub -> mobi -> epub` 回环实测接近
  24 分钟，其中 `mobi -> epub` 的章节切分阶段最慢。
- Linux 本地验证脚本基于 Debian calibre 8.5 布局，适合作为验证和交付取样；正式 release
  仍应优先走 bypy 集成命令。
- 产物没有提交进 git；仓库只保存构建脚本、代码和验证工具。

后续可以考虑：

- 如果需要支持 `azw/azw3/prc`，需要重新评估入口格式限制和样本预期。
- 如果需要高保真 PDF 输出，需要引入一个非 Qt 的 HTML-to-PDF 引擎，并重新评估体积。
- 如果需要更小的 Linux 包，可以继续缩减 Python stdlib、字体资源和动态库 allowlist。
- 如果要发布多架构 Linux 包，应使用 bypy Linux 构建路径验证 x86_64 和 arm64，而不是只依赖
  当前 Debian arm64 容器。
