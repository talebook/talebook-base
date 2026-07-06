# Standalone ebook-convert 整改任务书（给接手修改的 AI）

> 本文是给**另一个 AI**执行的修改指令。假设你冷启动、没有前序对话上下文。
> 完整审查证据见同目录 `2026-07-02-standalone-ebook-convert-qa.md`。
> 分支：`only-ebook-convert`。所有结论均来自**实跑真实产物**，不是读文档得来的。

## 0. 背景（30 秒）

`only-ebook-convert` 分支把 calibre 剪裁为一个无 Qt 的独立 `ebook-convert`，
运行时靠环境变量 `CALIBRE_STANDALONE_CONVERTER=1` 切换到精简插件集，只支持
`epub/mobi/pdf/txt` 互转。相关实现文件：
- `src/calibre/ebooks/conversion/standalone_binary.py`（入口 + 格式白名单）
- `src/calibre/customize/standalone_builtins.py`（运行时插件集，**真正生效的那份**）
- `src/calibre/customize/builtins.py`（含一个未生效的 restrict 函数）
- `src/calibre/ebooks/conversion/plugins/standalone_pdf_output.py`（无 Qt PDF 输出）
- `src/calibre/utils/standalone_img.py`（Pillow 版图片处理）
- `setup/standalone_ebook_convert_smoke.py` / `setup/standalone_ebook_convert_sample_matrix.py`（测试）
- 文档 `docs/standalone-ebook-convert.md`

已构建产物（可直接用来复现，无需重新打包）：
- macOS：`/tmp/calibre-ebook-convert-noqt-macos/ebook-convert`
- Linux：容器 `calibre-linux-ebook-convert-test` 内 `/out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert`

---

## 任务 1【P0，必须修】PDF 输出把中文（所有非 Latin-1 字符）变成 `?`

### 现象（已实测，macOS + Linux 均复现）
中文 txt/epub 转 pdf，`rc=0`、生成合法 PDF，但正文所有汉字（含中文标点）变 `?`，只有数字/ASCII 存活。

复现：
```bash
BIN=/tmp/calibre-ebook-convert-noqt-macos/ebook-convert
printf '这是中文测试 English 123。\n' > /tmp/zh.txt
"$BIN" /tmp/zh.txt /tmp/zh.pdf
python3 -c "import re;raw=open('/tmp/zh.pdf','rb').read();print([m.group(1) for m in re.finditer(rb'\((.*?)\)\s*Tj',raw,re.S)])"
# 实测输出: [b'??? ?? ?????? English 123?']
```

### 根因
`src/calibre/ebooks/conversion/plugins/standalone_pdf_output.py`：
- `pdf_text()`（约第 27-28 行）用 `.encode('latin-1', 'replace')`
- 内容流写出（`make_pdf_bytes`，约第 122-123 行）同样 latin-1
- 字体写死为内置 `Helvetica`（Type1，无 CJK 字形，约第 108 行）

latin-1 无法表示汉字 → `replace` 全变 `?`。

### 要求你做的修改（二选一，倾向方案 A）
**方案 A（推荐）：嵌入 CJK 字体，让 PDF 真正支持中文**
- 在包内内置一个开源 CJK 字体（如思源黑体 / Noto Sans CJK 的子集），
  PDF 里用 `/Type0` + `/Identity-H` 复合字体 + `CIDFontType2` + 嵌入字体流，
  并写 `ToUnicode` CMap 保证可复制。
- 文本按 UTF-16BE code point 写入（不再 latin-1）。
- 为控制体积，按实际用到的字符做子集化（可用 `fontTools.subset`，仓库已依赖 fontTools，
  见 `src/calibre/utils/fonts/subset.py`）。
- 打包脚本（`bypy/*`、`setup/build_standalone_ebook_convert_*_local.py`）需把该字体纳入资源。

**方案 B（保守）：从输出格式白名单移除 pdf**
- `standalone_binary.py` 把 `SUPPORTED_USER_FORMATS` 拆成 input/output 两套，output 去掉 `pdf`；
- `standalone_builtins.py` 的 `plugins` 列表移除 `StandalonePDFOutput`；
- 更新 `docs/standalone-ebook-convert.md`。
- 注意：PDF 作为**输入**没问题（走 poppler），只移除**输出**方向。

### 验收标准
- 方案 A：上面的复现命令抽取出的文本**不含 `?`**、能正常显示中文；且 `pdftotext` 能抽出正确中文。
- 方案 B：中文（及任意）文件转 pdf 被入口拒绝，`rc=2`，不产出文件；文档同步更新。

---

## 任务 2【P0，必须修】测试从不真实触发 PDF 输出，导致任务 1 无法被自动发现

### 证据
绿灯那次 "23/23 ok" 的实际结果文件（Linux）里，全部 `success` 行只有
`epub→mobi / mobi→epub / pdf→txt / txt→epub` 四个方向，**没有任何 `*→pdf`**。
- `setup/standalone_ebook_convert_sample_matrix.py:12-17` 的 `SUPPORTED_TARGETS`
  每种输入只映射一个输出，pdf 只作输入。
- `setup/standalone_ebook_convert_smoke.py`：种子由 `create_seed_txt()` 生成是**纯 ASCII**（约第 308 行），
  且只断言 `size>0`（约第 554 行），不校验内容。

### 要求你做的修改
- sample matrix 增加 `epub/txt/mobi → pdf` 方向；对 pdf 产物用 poppler `pdftotext` 抽取后做**内容断言**：
  “不含大量 `?`”且“包含预期中文子串”。
- smoke 的种子文本加入 CJK 字符，并对 pdf 产物做同样内容断言。
- **顺序要求**：先提交这些断言并确认它们在任务 1 修复前**必然失败**（先红），修完任务 1 后转绿。

### 验收标准
- 修任务 1 之前跑新测试：中文→pdf 用例**失败**。
- 修任务 1 之后跑新测试：全部通过。

---

## 任务 3【P2，建议修】builtins.py 里有一份未生效且会带回 Qt 的插件过滤逻辑

### 说明（已实测确认它运行时不生效）
`src/calibre/customize/builtins.py` 的 `restrict_plugins_for_standalone_converter()`
按 `file_type in {'pdf',...}` 保留输出插件，会保留**基于 Qt 的真实 `PDFOutput`**，与 no-Qt 目标矛盾。
但运行时 `customize/ui.py` 走的是 `standalone_builtins`（实测日志产出的是文本 PDF、无 Qt），
所以这个函数**根本没被用到**，是与 `standalone_builtins.plugins` 并行的第二套“真相来源”，易漂移、有误导。
`smoke.py:452-453` 还断言了它的内部字符串，把死逻辑固化了。

### 要求你做的修改
- 删除该函数及 `builtins.py` 末尾 `if os.environ.get('CALIBRE_STANDALONE_CONVERTER')...` 的调用，
  或保留但加显著注释说明“**非** standalone-runtime 插件源，勿依赖”。
- 同步删掉 `smoke.py` 里对其内部字符串的断言（第 452-453 行附近）。

### 验收标准
- standalone 运行时行为不变（仍只加载 `standalone_builtins`），smoke self-test 通过。

---

## 任务 4【P3，建议修】入口格式校验只按位置取参数

`standalone_binary.py` 的 `validate_args`（约第 54-55 行）直接把命令行第 2、3 个参数当
input/output。符合 calibre CLI 约定但脆弱。请至少在函数上方注释写明该假设，或做更稳健的解析。
（低优先，不阻塞发布。）

---

## 任务 5【文档，必须做】修正 docs 对能力的描述

`docs/standalone-ebook-convert.md` 目前只说 PDF 输出“复杂排版/图片不完整保留”，
**未披露“非拉丁文字（含全部中文）会丢失”**——属实质性误述。按任务 1 的最终方案修正该段。

另外把下述实测已知损耗补入“当前限制”：
- 走 MOBI 中转做 epub→epub **无法无损**：嵌入字体、CSS 背景装饰图、透明度、布局都会丢
  （这是 MOBI 格式固有，非 standalone 特有）。
- **standalone 特有的额外损失：SVG 不栅格化**（`SVGRasterizer` 被禁用），
  正文/封面中的 SVG 不会转成位图。
- 大书性能：28MB/1415 章的 epub↔mobi 回环实测接近 24 分钟（mobi→epub 的章节切分极慢）。

---

## 不需要改 / 已确认正常（避免你误改）
以下均已实测正常，**请勿动**：
- epub/mobi/txt 全链路中文内容无损（txt→epub、epub→txt、pdf→txt、epub→mobi→epub 回环，中文 100% 保留）。
- PDF **输入**（走 poppler `pdftohtml`）中文正常。
- Pillow 版 `standalone_img` 图片处理正常，产出图片合法未损坏。
- no-Qt 达成（产物树无 `libQt*`）。
- 不支持格式（azw/azw3/doc/docx/ebk3/original_epub/png/prc/wps/zip）正确拒绝，`rc=2` 且不产出。
- SVG rasterizer 禁用路径的 `except Unavailable` 已正确捕获，不崩溃。

## 建议修复顺序
1. 任务 2（先写会失败的中文→pdf 测试）→ 2. 任务 1（修 PDF 中文）→ 3. 任务 5（文档）→ 4. 任务 3 → 5. 任务 4。

## 每次改完的回归验证
```bash
# 自测（无需产物）
python3 setup/standalone_ebook_convert_smoke.py --self-test
# 功能 smoke（需产物）
python3 setup/standalone_ebook_convert_smoke.py --forbid-qt-imports \
  /tmp/calibre-ebook-convert-noqt-macos/ebook-convert
# 真实样本矩阵（含中文）
python3 setup/standalone_ebook_convert_sample_matrix.py \
  /tmp/calibre-ebook-convert-noqt-macos/ebook-convert \
  samples/ca-format-samples /tmp/sample-matrix-out
```
