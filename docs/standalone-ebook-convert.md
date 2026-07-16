# Standalone ebook-convert 方案归档

本文记录 `slim-v8.5.0` 分支中将 calibre 剪裁为 Talebook 无 Qt 转换运行时的
调研、实现和验证过程。早期独立目录包的验证记录仍保留在后半部分；当前
`talebook-base` 镜像已改为 Debian 系统 Python 布局。

本分支的版本依据是目标 Debian 仓库，而不是 Calibre 官方最新版本。2026-07-16
查询 `debian:13-slim` 得到的候选包是 `8.5.0+ds-1+deb13u3`，因此源码与 API
兼容基线固定为 Calibre `v8.5.0`；Debian 后续提供更高版本时另开对应的
`slim-vX.Y.Z` 分支处理升级。

## 目标

目标是保留 Talebook 实际调用的 `ebook-convert` 与 `calibredb`，同时从最终镜像移除
Qt/PyQt/QtWebEngine。最终交付物不是完整 calibre，也不是单个静态 ELF，而是基于
`debian:13-slim` 的系统运行时：

- 使用 Debian `/usr/bin/python3`，并保留 `python3-pip` 供上层 Talebook 安装
  requirements；不再携带私有 Python 解释器或 `PYTHONHOME`。
- Calibre Python 代码位于 `/usr/lib/calibre`，资源位于 `/usr/share/calibre`。
- 必要 native 库和 Poppler helper 分别位于 `/usr/lib/talebook-calibre/lib` 与
  `/usr/lib/talebook-calibre/bin`。
- 公开 Calibre 命令为 `ebook-convert`、`calibredb`；不再暴露临时的独立 PDF 命令。
- `.pdf` 输出由入口路由到 WeasyPrint；轻量 Calibre 转换器不再注册 PDF 输出插件。

构建阶段只用 `apt-get --download-only` 获取 Debian 包；随后用 `dpkg-deb -x` 解包，
Qt/PyQt 包在进入取材树前被过滤。最终阶段从干净的 `debian:13-slim` 开始，只复制
白名单代码、资源、helper 和递归收集出的非 Qt ELF 依赖。
`Dockerfile.base` 会校验候选包仍属于 8.5.0；允许 Debian 安全修订升级，但如果
上游版本发生变化就直接终止构建，要求在新的 `slim-vX.Y.Z` 分支完成适配和验证。

## 调研结论

完整 calibre 体积和依赖主要来自几类能力：

- GUI、viewer、editor、server、device 集成、recipe/news 抓取、AI/store 插件。
- Qt/PyQt/QtWebEngine 及其 transitive 动态库。
- 大量输入/输出格式插件和平台集成命令。
- Python 运行时、第三方包、native calibre 插件、字体和资源。

`ebook-convert` 的核心转换链路可以从完整 calibre 中剥离出来，但有几个关键点：

- 插件系统默认会加载大量内置插件，需要提供 standalone 插件列表或运行时过滤。
- Calibre 原生 PDF 输出默认走 QtWebEngine 相关路径，不适合 no-Qt 镜像；公共 PDF
  输出改用 WeasyPrint。
- MOBI 输出中 SVG rasterizer 依赖 Qt；standalone 包中需要禁用这条路径。
- MOBI 读写和图片处理部分原本会导入 `calibre.utils.img`，该模块依赖 Qt native
  image 插件；standalone 包需要切换到 Pillow fallback。
- PDF 输入在部分中文 PDF 上使用默认解析路径会遇到 XML/编码问题，standalone 包中
  默认使用 `pdftohtml` 路径。
- Debian 打包版 calibre 带有发行版修订，Linux 本地验证脚本不能粗暴覆盖整棵源码，
  需要以 Debian 8.5 包内代码为运行时底座，并只应用经过测试的最小补丁。

## 支持范围

用户可直接使用的格式被限制为：

- 输入：`azw`、`azw3`、`docx`、`epub`、`mobi`、`original_epub`、`pdf`、`prc`、
  `txt`、`zip`
- 轻量输出：`azw3`、`epub`、`mobi`、`txt`
- 公共 PDF 输出：`ebook-convert INPUT.pdf-or-ebook OUTPUT.pdf` 由同一入口在内部交给
  WeasyPrint 后端，不进入轻量输出插件集合

入口层会拒绝其它扩展或输出格式，返回码为 `2`。例如 `doc`、`ebk3`、`png`、`wps`
仍不会进入转换管线。

这是一种有意的边界控制：减少隐式依赖、避免把完整 calibre 的插件面重新带回来。
本轮按照 `samples/ca-format-samples` 和原版 calibre 8.5.0 的实测结果，补入了原版可正常
处理且不需要 Qt 的样本输入格式：`azw/azw3/prc` 走 `MOBIInput`，`original_epub`
走 `EPUBInput`，`zip` 先由 calibre archive 预处理展开后再走真实输入插件，`docx`
走 `DOCXInput`。

## 核心实现

### 入口限制

`src/calibre/ebooks/conversion/standalone_binary.py` 是 standalone 入口。

它做三件事：

- 设置 `CALIBRE_STANDALONE_CONVERTER=1`。
- 在 `CALIBRE_STANDALONE_FORBID_QT=1` 时安装 import guard，禁止导入 `qt` 和
  `PyQt6`。
- 在调用 calibre 原始 conversion CLI 之前分开校验输入/输出扩展；输入允许
  `azw/azw3/docx/epub/mobi/original_epub/pdf/prc/txt/zip`，输出允许
  `azw3/epub/mobi/txt`。

镜像公开的 `/usr/bin/ebook-convert` 先由 `ebook_convert_router.py` 检查输出扩展：
`.pdf` 调用内部 `weasy_pdf.py` 后端，其它格式调用 `standalone_binary.py`。因此 PDF 是
公共命令能力，但不是轻量 Calibre 输出插件能力。

### 插件剪裁

`src/calibre/customize/standalone_builtins.py` 定义 standalone 内置插件集合，只保留：

- EPUB/MOBI/PDF/TXT/DOCX 的 metadata reader，EPUB/MOBI/PDF 的 metadata writer。
- EPUB/MOBI/PDF/TXT/DOCX 输入插件，EPUB/MOBI/TXT 输出插件。
- 内部转换需要的 `HTMLInput`、`OEBOutput`。
- input/output profile。

`src/calibre/customize/ui.py` 在 standalone 环境下加载上述插件列表，并避免导入
device 插件。

`src/calibre/customize/builtins.py` 不作为 standalone 运行时的插件源。运行时插件集合
只以 `standalone_builtins.py` 为准，避免和完整 calibre 的默认插件列表产生漂移。

### PDF 输出

`standalone_pdf_output.py` 已删除：上层 Talebook 从未直接调用这个轻量插件，而且公共
`ebook-convert` 早已把 `.pdf` 输出分流到内部 `weasy_pdf.py`。保留两套 PDF 实现只会
扩大维护面并让测试结果混淆。

当前 PDF 流程是 Calibre 输入插件先把源书规范化为 OEB，`weasy_pdf.py` 再按
spine 合并 XHTML、修正资源 URL、加载 CSS 与 CJK 字体，最后调用 WeasyPrint 写出
PDF。入口调用形态仍与 Calibre CLI 一致：
`ebook-convert INPUT OUTPUT.pdf [options...]`。

### PDF 输入

standalone 插件列表中的 `StandalonePDFInput` 克隆 calibre PDF 输入插件选项，并将
`pdf_engine` 默认值设为 `pdftohtml`。这条路径依赖包内 Poppler helper，避免默认 PDF
解析路径在部分中文 PDF 上触发编码/XML 解析失败。

### MOBI 和图片处理

MOBI 相关改动主要为 no-Qt：

- `mobi_output.py` 在 standalone 环境下禁用 `SVGRasterizer`，避免导入 Qt rasterizer。
- `mobi6.py`、`mobi/utils.py`、`mobi/writer2/resources.py`、`docx/images.py` 统一从
  `calibre.utils.img_shim` 导入图片辅助函数；该分发模块在 standalone 环境下重导出
  `calibre.utils.standalone_img`，否则重导出 Qt 版 `calibre.utils.img`，环境开关只
  存在于这一个文件中。
- `standalone_img.py` 使用 Pillow 实现基础图片读取、缩放、格式转换、cover 保存、
  GIF/PNG/JPEG 处理。
- Talebook 的封面缩略图仍调用历史接口 `calibre.utils.magick.draw.thumbnail()`。Debian
  运行时组装器对该函数做最小补丁：standalone 模式转发到 Pillow
  `standalone_img.thumbnail()`，完整 Calibre 模式继续使用原 Qt/ImageMagick 兼容实现。
- 镜像 smoke 使用真实 RGBA PNG 验证图片识别、透明背景转 JPEG、等比例缩放、
  PNG/GIF 往返和缩略图，并通过 `LibraryDatabase.import_book()` 后分别调用
  `set_cover()`、`set_metadata()`、`cover()` 验证 Talebook 实际书库封面链路。

SVG 处理的结论：

- standalone MOBI 输出不会因为缺少 Qt SVG rasterizer 直接崩溃。
- 但 SVG 不会被 rasterizer 转成位图，日志中会出现
  `SVG rasterizer unavailable, SVG will not be converted`。
- EPUB 中普通位图图片、MOBI 中常规图片处理正常；复杂 SVG 视觉保真不作为当前目标。

### 退出清理

`src/calibre/utils/safe_atexit.py` 在 standalone 环境下不再走 calibre 的外部清理进程，
而是直接用 Python `atexit` 注册临时文件/目录清理，避免引入额外 calibre command。

### 平台相关绕过

`src/calibre/utils/localization.py` 在 standalone 环境下跳过 macOS 的
`user_locale`/usbobserver 调用：usbobserver 扩展不在 standalone 包中，locale 直接走
环境变量路径。

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

两个脚本共享的常量清单（no-Qt 包名、禁入 calibre 目录、helper 二进制等）在
`setup/standalone_build_common.py` 中维护，平台差异项（CJK 字体候选、资源保留清单等）
留在各自脚本内。

### Talebook Debian 系统运行时

镜像构建把取材、编译和发布分开：

1. `packaging/extract-debian-packages.sh` 从 apt 下载缓存逐个读取包名，跳过
   `libqt*`、`qt*`、`pyqt*` 和 `python3-pyqt*`，仅用 `dpkg-deb -x` 解包其它包。
2. `packaging/build-system-runtime-from-debian.sh` 调用现有白名单/ELF 闭包构建器生成
   临时组合包，再把需要的代码、资源、helper 和 `.so` 投放到最终系统路径；临时包中的
   Python 解释器和标准库不会进入最终镜像。组装器会以最终 Debian 系统层为参照，删除
   45 份内容完全相同的 `.so` 副本，随后由最终镜像的全量 `ldd` smoke 验证依赖仍闭合。
3. `python-wheel-build` 独立安装 `build-essential` 和 `python3-dev`，只编译 Talebook
   `requirements.txt` 需要的 QuickJS wheel。最终层通过 BuildKit 只读 mount 安装 wheel，
   编译器、headers、wheel 文件本身及 builder apt 层都不会进入发布镜像。

`runtime-system` 基于 `debian:13-slim`，只通过 apt 安装系统 Python、pip 及 Talebook
服务运行依赖；最终层直接复用它并叠加上述裁剪结果。预装 QuickJS 后，上层原有
`pip install -r` 会把它识别为已满足；`PIP_BREAK_SYSTEM_PACKAGES=1` 保持旧 Talebook
镜像的安装行为。

2026-07-16 的本地 arm64 基线从 740,220,119 bytes（约 706 MiB）降到
356,153,818 bytes（约 340 MiB），减少 51.9%；`/usr` 从 701 MiB 降到 346 MiB。
`packaging/smoke-test.sh` 与双架构 CI 将 `/usr <= 400 MiB` 作为回归门禁，并拒绝最终
镜像出现 `build-essential`、`python3-dev`、`python3-venv` 或 `gcc`。

### 正式构建（bypy 集成）

正式 release 使用 bypy 集成命令，flavor 通过 `CALIBRE_LINUX_BINARY_FLAVOR` /
`CALIBRE_MACOS_BINARY_FLAVOR=ebook-convert` 传入：

- `./setup.py linux_ebook_convert`（及 `linux_ebook_convert64` /
  `linux_ebook_convertarm64`）构建 Linux standalone 包。
- `./setup.py osx_ebook_convert` 构建 macOS standalone app。

bypy 平台脚本（`bypy/linux/__main__.py`、`bypy/macos/__main__.py`）共享的 standalone
常量与裁剪/校验逻辑在 `bypy/standalone_common.py` 中维护。命令细节见
`bypy/README.rst`。

## 验证工具

`setup/standalone_ebook_convert_smoke.py` 做 package-level 和功能级 smoke：

- 检查包根目录只暴露预期 surface。
- 禁止 Qt/PyQt/QtWebEngine 文件和 `libQt*` 动态依赖。
- 禁止 GUI、server、device、scraper 等 calibre 代码面进入包。
- 禁止额外 calibre command 暴露。
- 校验归档安全，拒绝绝对路径、`..` 路径、危险 symlink。
- 运行 `epub/mobi/txt` 轻量互转矩阵，并确认直接轻量 PDF 输出被拒绝。
- 验证 unsupported `docx` 和 recipe 能力被拒绝。

`setup/standalone_ebook_convert_sample_matrix.py` 用真实样本目录做矩阵验证：

- `azw -> epub`
- `azw3 -> epub`
- `docx -> epub`
- `epub -> mobi`
- `mobi -> epub`
- `original_epub -> epub`
- `pdf -> txt`
- `prc -> epub`
- `txt -> epub`
- `zip -> epub`
- `doc`、`ebk3`、`png`、`wps` 等原版也无法在该样本集中成功转换的格式预期被
  standalone 入口拒绝，返回码 `2`，且不生成输出。

`setup/standalone_ebook_convert_reference_compare.py` 用同一批样本对比 standalone 和
reference `ebook-convert`：

- 对每个样本分别跑 reference 和 standalone。
- 对生成的 `txt` 直接读取；对 `pdf` 用 `pdftotext` 抽取；对 `epub/mobi` 再调用
  reference `ebook-convert` 转成 TXT 后比较正文。
- 比较正文长度比例、CJK 字符数量比例、相似度和文本 hash。
- 同时记录双方返回码、输出大小、首条日志，便于区分 standalone 缺口和 reference 环境问题。

### Talebook 图片路径审计与集成验证（2026-07-16）

Talebook 对 Calibre 图片 API 的直接调用只有
`webserver/handlers/files.py` 中的 `calibre.utils.magick.draw.thumbnail()`；原图响应直接
读取数据库 cover。其它图片处理均为 Talebook 自身的 Pillow 路径，包括验证码、网络
书源封面和元数据提供方。间接经过 Calibre 的路径为书籍导入、`set_cover()`、
`set_metadata()`、格式元数据读写以及电子书转换。

验收分三层完成：

- `packaging/smoke-test.sh` 覆盖 Pillow shim、公共缩略图接口、数据库封面写入/读取和
  EPUB→MOBI/AZW3/PDF 图片转换路径。
- Talebook 原失败 seam `tests/test_main.py::TestFile::test_get_thumb` 单独通过。
- 在新 `talebook/talebook-base:slim`（本地别名 `:8.5`）上运行 Talebook
  `make test`，结果为 `575 passed, 1 skipped`；上传、扫描、验证码、封面代理、网络书源
  和元数据提供方相关测试均包含在完整结果中。

## Debian 容器验证记录（历史独立包）

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

- 两个 AZW 样本成功转换为 EPUB。
- 两个 AZW3 样本成功转换为 EPUB。
- 两个 DOCX 样本成功转换为 EPUB。
- 两个 EPUB 样本成功转换为 MOBI 和 PDF。
- 两个 MOBI 样本成功转换为 EPUB 和 PDF。
- 一个 ORIGINAL_EPUB 样本成功转换为 EPUB。
- 两个 PDF 样本成功转换为 TXT。
- 两个 PRC 样本成功转换为 EPUB。
- 两个 TXT 样本成功转换为 EPUB 和 PDF。
- 一个 ZIP 样本成功展开并转换为 EPUB。
- 所有样本 PDF 输出都经过 `pdftotext` 抽取校验，要求含有足量中文且不是 `?` 占位。
- `doc/ebk3/png/wps` 样本按 standalone 边界被拒绝，返回码为 `2`。
- 21MB 的大 MOBI、PRC 和 ZIP 样本会明显拉长运行时间，因此最终用 900 秒超时验证通过。

Debian reference 对比：

```text
Reference comparison: ok=41, same_fail=16, standalone_extra=6
Report: /out/reference-compare-nonpdf-input-expansion/reference-compare.tsv
```

解释：

- `ok=41`：双方都成功，且抽取文本内容通过长度、CJK 字符数量和相似度校验。
- `same_fail=16`：双方都失败，覆盖 `doc/ebk3/png/wps` 等当前不支持样本。
- `standalone_extra=6`：均为 PDF 输入到 `epub/mobi/txt`。Debian 容器里的
  `/usr/bin/ebook-convert` 在这些 PDF 样本上返回 `1`，而 standalone 成功；这反映
  Debian reference 环境不适合作为 PDF parity 参考。PDF 输入能力已由 standalone
  sample matrix 和 smoke 单独验证。

Talebook reference 对比使用本地可信 `talebook/talebook:latest` 镜像，容器内
`/usr/bin/ebook-convert` 为 calibre 8.5.0。原版 PDF 输出在容器 root 环境下需要
`QTWEBENGINE_DISABLE_SANDBOX=1`。

PDF 输出对比：

```text
Reference comparison: ok=15, same_fail=5
Report: /tmp/reference-compare-talebook-pdf-final/reference-compare.tsv
```

说明：

- `ok=15`：双方 PDF 输出成功，`pdftotext` 抽取后的正文长度、CJK 字符数和 `?`
  占位比例通过校验。
- `same_fail=5`：双方都失败，覆盖 `doc/ebk3/png/wps` 等边界外样本。
- `MOBI/54... -> pdf` 在 talebook 原版 QtWebEngine 路径下返回失败且资源消耗很高；
  未作为 PDF parity 成功样本计入。

非 PDF 输出对比：

```text
Reference comparison: ok=41, same_fail=16, standalone_extra=6
Report: /tmp/reference-compare-talebook-nonpdf-final/reference-compare.tsv
```

说明：

- `ok=41`：双方都成功，文本抽取内容通过长度、CJK 字符数、相似度或 hash 校验。
- `same_fail=16`：双方都失败，覆盖边界外样本。
- `standalone_extra=6`：均为两个 PDF 样本输入到 `epub/mobi/txt`。talebook 原版
  `PDFInput` 默认 reflow XML 路径因非 UTF-8 字节触发 `lxml.etree.XMLSyntaxError`；
  standalone 默认使用 `pdftohtml`，所以转换成功。这是 standalone 额外修复能力，
  不是输出 parity 缺口。

最终 Linux 产物：

```text
dist/calibre-ebook-convert-noqt-linux-arm64.tgz
size: 68.49 MB
sha256: 8ec0253272a9ca7a56323cebbd7f694b471884697bbe4cf1b7b884ca63ac41ce
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

## macOS 本地验证记录（历史独立包）

macOS 本地开发包产物：

```text
dist/calibre-ebook-convert-noqt-macos-arm64.tgz
size: 37.93 MB
sha256: 6c252fdcaa9ad6ced6b06d938f5577704cd42ffb2eaa2a524e5fc4b4f3d0bd40
```

本地 macOS 验证覆盖：

- 包结构和归档安全。
- 无 Qt/PyQt/`libQt` 依赖。
- 当时的 `epub/mobi/pdf/txt` 互转 smoke；其中轻量 PDF 输出实现现已删除。
- 真实 PDF 样本转换，使用 `pdftohtml` 路径修复中文 PDF 问题。
- Debian 容器内对 macOS tgz 做归档 surface 校验。

## 当前限制和后续方向

当前实现是一个可验证的 no-Qt `ebook-convert`/`calibredb` 子集，不是完整 calibre 的替代品。

已知限制：

- 轻量输出格式只支持 `azw3/epub/mobi/txt`，公共 PDF 由 WeasyPrint 路由提供。输入格式按当前样本验证扩展到
  `azw/azw3/docx/epub/mobi/original_epub/pdf/prc/txt/zip`，但仍不是完整 calibre
  的全部输入插件集合。
- WeasyPrint PDF 不保证与 QtWebEngine 原版逐像素一致；扫描版/纯图片书籍需要继续用
  公共 PDF smoke 和样本矩阵守住行为。
- MOBI 输出中的 SVG rasterizer 被禁用，SVG 不保证转换为位图。
- 通过 MOBI 中转做 `epub -> epub` 回环不能视为无损：嵌入字体、CSS 背景装饰图、
  透明度和布局都可能丢失。这是 MOBI 中间格式的固有限制，不是 standalone 特有问题。
- standalone 额外缺少 Qt SVG rasterizer；正文或封面里的 SVG 不会被栅格化为位图。
- 大书转换耗时明显。28MB、1415 章样本的 `epub -> mobi -> epub` 回环实测接近
  24 分钟，其中 `mobi -> epub` 的章节切分阶段最慢。
- Linux 取材脚本和当前分支都以 Calibre v8.5.0 为 API 基线；Debian 的 `+ds`、
  `-1` 和 `+deb13u3` 修订仍由包内代码提供，覆盖文件时必须继续做兼容检查。
- 产物没有提交进 git；仓库只保存构建脚本、代码和验证工具。

后续可以考虑：

- 如果需要支持更多输入或输出格式，需要逐项确认插件依赖不会把 Qt 或 GUI surface 带回包中。
- 如果需要更高保真 PDF 输出，应继续改进现有 WeasyPrint 路径并重新评估体积。
- 如果需要更小的 Linux 包，可以继续缩减 Python stdlib、字体资源和动态库 allowlist。
- 如果要发布多架构 Linux 包，应使用 bypy Linux 构建路径验证 x86_64 和 arm64，而不是只依赖
  当前 Debian arm64 容器。
