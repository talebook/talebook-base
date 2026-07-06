# Standalone ebook-convert QA 审查记录

- 日期：2026-07-02
- 分支：`only-ebook-convert`
- 审查对象：commit `5e5e653bcd`（打包）+ `b4461feaba`（文档），docs/standalone-ebook-convert.md
- 审查方式：静态代码审查 + **实跑真实产物**（不依赖文档结论）
- 被测产物：
  - macOS：`/tmp/calibre-ebook-convert-noqt-macos/ebook-convert`（= `dist/calibre-ebook-convert-noqt-macos-arm64.tgz`）
  - Linux：容器 `calibre-linux-ebook-convert-test` 内 `/out/calibre-ebook-convert-noqt-linux-arm64/ebook-convert`（= 66M `dist/...linux-arm64.tgz`）
  - 样本：`samples/ca-format-samples/`（真实中文电子书）

---

## 结论摘要

整体方案自洽、可交付：运行时用 `CALIBRE_STANDALONE_CONVERTER` 切换到 `standalone_builtins`，
屏蔽 Qt 导入、Pillow 替换图片处理、无 Qt PDF 输出；no-Qt 目标实测达成。

**但存在 1 个致命功能缺陷 + 1 个测试盲区，二者互为因果。** 必须修。

除 PDF 输出外，其它所有格式（含中文）转换内容均正常。问题被精确锁定在单一插件
`StandalonePDFOutput`。

---

## 🔴 P0-1：PDF 输出把中文（所有非 Latin-1 字符）全部变成 `?`

### 根因
`src/calibre/ebooks/conversion/plugins/standalone_pdf_output.py`
- `pdf_text()`（第 27-28 行）：`.encode('latin-1', 'replace')`
- `make_pdf_bytes()` 内容流（第 122-123 行）：同样 latin-1
- 字体固定为内置 `Helvetica`（Type1，无 CJK 字形，第 108 行）

`latin-1 + replace` 导致任何汉字/中文标点被替换为 `?`。

### 实测证据（rc 均为 0，产物是合法 PDF，但正文中文全灭）
| 场景 | 平台 | PDF 内 Tj 文本流实际字节 |
|---|---|---|
| 合成中文 txt→pdf | macOS | `??? ... PDF ...English mixed 123. ...` |
| 真实中文 EPUB→pdf（`33-Shi Jian Jian Shi....epub`）| macOS | `????(???) ... 1988 ... 40 ... 1000 ...`（仅数字/ASCII 存活）|
| 合成中文 txt→pdf | Linux 66M 产物 | `??? ?? ?????? English 123?`（连 `。` 也变 `?`）|

复现命令（macOS）：
```bash
BIN=/tmp/calibre-ebook-convert-noqt-macos/ebook-convert
printf '这是中文测试 English 123。\n' > /tmp/zh.txt
"$BIN" /tmp/zh.txt /tmp/zh.pdf
python3 -c "import re;raw=open('/tmp/zh.pdf','rb').read();print([m.group(1) for m in re.finditer(rb'\((.*?)\)\s*Tj',raw,re.S)])"
```

### 影响
交付物面向中文电子书，PDF 输出等于内容归零，且 `rc=0` 会让上层误判为成功。
文档 docs/standalone-ebook-convert.md:98 仅称"复杂排版/图片不保留"，**未披露"中文内容归零"**，
属对交付能力的实质性误述。

### 建议修法（二选一，交由实现方决策）
1. **嵌入 CJK TrueType 字体**（如思源黑体子集）+ 用 `Identity-H` + CMap/ToUnicode 写文本，
   使中文真正可渲染、可复制。代价：产物体积增加（可做子集化控制）。
2. **从 standalone 输出格式白名单里移除 `pdf`**：
   - `src/calibre/ebooks/conversion/standalone_binary.py` 的 `SUPPORTED_USER_FORMATS`
     区分输入/输出，输出去掉 `pdf`；
   - 相应从 `standalone_builtins.plugins` 移除 `StandalonePDFOutput`；
   - 更新 docs。
   代价：不再提供 PDF 输出（但当前的 PDF 输出对中文无意义）。

> 注：PDF 作为**输入**没有问题（走 poppler `pdftohtml`，见下方实测），本缺陷仅限 PDF **输出**。

---

## 🔴 P0-2：样本矩阵"23/23 ok"从未真实触发 PDF 输出（P0-1 的根因）

### 证据（实读绿灯那次的结果文件）
`/private/tmp/calibre-linux-build-output/linux-sample-matrix/sample-results.tsv`
中全部 `success` 行只有 4 个方向：
```
epub → mobi   (×2)
mobi → epub   (×2)
pdf  → txt    (×2)
txt  → epub   (×2)
```
**无任何 `* → pdf` 行**（所有 reject 行目标也都是 epub）。

根因在 `setup/standalone_ebook_convert_sample_matrix.py:12-17`：`SUPPORTED_TARGETS`
每种输入只映射一个输出方向，PDF 只作为被转换的输入（`pdf→txt`），从不作为输出目标。

smoke（`setup/standalone_ebook_convert_smoke.py`）虽有 `txt→pdf` 等方向，但：
- 种子由 `create_seed_txt()` 生成，是**纯 ASCII**（第 308 行）；
- 只断言 `os.path.getsize(output) > 0`（第 554 行），不校验内容。

因此两层测试都测不到中文乱码 —— 这就是 P0-1 潜伏至今的原因。

### 建议修法
- sample matrix 增加 `epub/txt/mobi → pdf` 方向，并对产物做**内容断言**：
  用 poppler `pdftotext` 抽取后，断言"不含大量 `?`"或"包含预期中文子串"。
- smoke 的种子文本加入 CJK 字符，且对 PDF 产物做同样的内容断言。
- 目标：让上述断言在 P0-1 修复前**必然失败**（先红后绿）。

---

## 🟡 P2：`builtins.py` 的 standalone 过滤函数与 no-Qt 目标不一致且未被使用

`src/calibre/customize/builtins.py` 的 `restrict_plugins_for_standalone_converter()`
按 `file_type in {'pdf',...}` 保留输出插件，会保留**基于 Qt 的真实 `PDFOutput`**，
与 no-Qt 目标矛盾。

实测运行时走的是 `standalone_builtins`（日志 `Creating PDF Output...` 产出的是文本 PDF、
无 Qt），即该 restrict 函数在运行时**根本没被使用**，是与 `standalone_builtins.plugins`
并行的第二套插件真相来源。

风险：冗余、易漂移；若将来有人误当它是 standalone 插件源，会静默把 Qt 拉回来。
`smoke.py:452-453` 还断言了它的内部字符串，等于固化了这套死逻辑。

建议：删除该函数，或加明确注释说明它**不是** standalone-runtime 的插件源。

---

## 🟡 P3：入口格式校验只按位置取 `args[1]/args[2]`

`standalone_binary.py` 的 `validate_args`（第 54-55 行）直接把第 2、3 个命令行参数当
input/output。符合 calibre CLI "input output 在前两位"的约定，但对非常规排列是脆弱的，
不是稳健的参数解析。当前用法问题不大，属健壮性隐患。建议至少在 doc 写明入口的调用形态假设。

---

## ✅ 已实测确认正常的部分（文档说法属实，且中文内容 OK）

除 PDF 输出外，所有格式的中文内容均正确保留：

| 转换 | 实测结果 |
|---|---|
| txt→epub | ✓ xhtml 含真中文（`因为懂得所以慈悲…`）|
| epub→txt | ✓ 93969 个中文字符 |
| pdf→txt | ✓ 99268 个中文字符（PDF **输入**走 poppler，中文正常）|
| epub→mobi→epub 回环 | ✓ 末端 epub 含 94173 个中文字符（MOBI 读写 + Pillow 图片路径正常）|

其它：
- reject 路径：azw/azw3/doc/docx/ebk3/original_epub/png/prc/wps/zip 全部 `rc=2`、
  `output_size=0`（tsv 实证）。
- no-Qt：Linux 产物树 `find -name 'libQt*'` 无结果。
- SVG rasterizer 禁用路径：`mobi_output.py:248` 的 `except Unavailable` 正确捕获，不崩溃。
- `os` 导入、`safe_atexit` 辅助函数（`run_program`/`unlink`/`remove_dir`）均核对存在。

> 小观察（非本次缺陷）：某个 pdf→txt 样本抽取出的中文有个别 poppler 识别噪声
> （如"东野圭吾"→"东野圭吼"），属 poppler 输入侧行为，与 standalone 改动无关。

---

## 交给实现方的最小整改清单（按优先级）

1. **P0-1**：决定 PDF 输出方向 —— 嵌 CJK 字体真正可用，或从输出白名单移除 `pdf`。
2. **P0-2**：sample matrix / smoke 增加 `*→pdf` 且带中文内容断言（先让它红）。
3. **P2**：清理 `builtins.py` 未使用且会带回 Qt 的 restrict 逻辑（或加注释）。
4. **P3**：入口参数解析健壮化或在 doc 声明假设。
5. 修复后同步更新 docs/standalone-ebook-convert.md 中对 PDF 输出能力的描述。

---

## 附：特殊排版书 epub→mobi→epub2 无损性实测（诡秘之主.epub）

- 样本：`samples/诡秘之主.epub`（注意：仓库里是**解压后的目录**，测试前需重新打包成 zip epub）
- 特征：28MB / 1415 章 / 4 个嵌入 TTF 字体 / 10 条 @font-face / 6 处 CSS background 装饰图 / 封面为 SVG（Cover.xhtml）
- 命令：`epub → mobi`（2m43s），`mobi → epub2`（约 **21 分钟**）
- 结论：**MOBI 中间格式无法无损**；正文文字完好，字体/装饰背景/布局有损。

### 逐项对比（src epub vs epub2）
| 项目 | 源 epub | epub2 | 结论 |
|---|---|---|---|
| 正文中文字符数 | 3,837,231 | 3,856,376 | ✅ 100% 保留（略增=mobi→epub 重复插入标题/TOC）|
| `<img>` 标签数 | 1405 | 1405 | ✅ 引用全部保留，**0 坏链** |
| 图片文件数 | 11 | 4 | ⚠️ 丢 7 张 |
| 嵌入字体(TTF) | 4 | 0 | ❌ 全丢，10 条 @font-face 失效 |
| CSS 文件 | 2 | 2（被重写）| ⚠️ font-size flatten 等重排 |
| 封面 | cover.png（SVG 包裹）| calibre 重新生成的 calibre_cover.jpg | ⚠️ 被替换 |
| 存活图片格式 | PNG×10 + JPG×1 | 全部 JPG（合法、尺寸正常，Pillow 路径无损坏）| ⚠️ PNG→JPG，透明度丢失 |

### 丢失归因（关键：区分格式固有 vs standalone 特有）
**A. MOBI 格式固有损耗（全量 calibre 同样会发生，非 standalone bug）：**
1. 嵌入字体丢失 —— 根因：`mobi_output.py` 默认 `mobi_file_type='old'`（MOBI6），
   `create_kf8=False` → `add_fonts=False`（resources.py:151），MOBI6 不支持字体嵌入。
   MOBI 中间产物实测 0 个 FONT 记录。
2. CSS background 装饰图（6 张：part-back / chapter-head-text-back / description-back /
   part-title-back / introduction-bottom / back.png）—— MOBI 不支持 CSS 背景，转换后 unreferenced
   被 "Trimming ... from manifest" 裁掉。
3. PNG→JPG，透明通道丢失。
4. 原封面被 calibre 重新生成的 cover.jpg 替换。
5. 章节按 page-break 重新切分（"Split into 1415 parts"），结构变化。

**B. standalone 特有的额外损失：**
1. **SVG 不栅格化** —— `SVGRasterizer` 被禁用（mobi_output.py），日志实测
   `SVG rasterizer unavailable, SVG will not be converted`。本书封面 Cover.xhtml 是 SVG；
   全量 calibre 会把 SVG 转成位图，standalone 不会。正文若含 SVG 插图，在 standalone 下同样不会转位图。
   （本例封面恰被 calibre 另生成 jpg 掩盖了影响，但机制上是真实回归。）

**C. 性能观察（实测）：**
- `mobi → epub2` 约 21 分钟，长时间卡在 "Splitting markup on page breaks"。
- 28MB/1415 章的书回环一次接近 24 分钟。对转换服务是明显的性能风险，需关注大书场景。

### 对"无损"期望的回应
通过 MOBI 中间格式做 epub→epub **本质上不可能无损**（字体/CSS 背景/布局/透明度都会掉），
这与 standalone 无关；standalone 仅额外多丢"SVG 栅格化"一项。
若目标是尽量保真的 epub→epub，应避免走 MOBI 中转（epub 直接输出，或用支持字体的 KF8：`--mobi-file-type both`），
但即便如此 CSS 背景图与 SVG（standalone）仍会丢。
