# MellonEater · 知瓜

把聊天里的事件、各方说法、证据和未知项放在一起，生成可以回查原文的争议分析报告。

当前为 **macOS 本地 MVP**：上传、粘贴或本地导入微信原生 ZIP → 本地规范化与截图 OCR → Codex / DeepSeek 分析 → 主线提纲 → 阅读稿 → 审稿与自动返修 → 证据工作台 / HTML / PDF。微信 ZIP 导入已通过合成测试，真实导出格式待用户小包验证；数据库自动采集仍待本机兼容性验证。

## 启动

在 Mac 上双击 `start.command`，浏览器打开 `http://127.0.0.1:8765`。关闭终端会停止服务。

脚本优先使用本机 Codex 随附的 Python；其他环境可以：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[pdf]'
.venv/bin/python -m chigua.server
```

核心服务只使用 Python 标准库；PDF 导出需要 ReportLab 和可用的中文字体。当前 Mac 使用宋体正文、黑体标题与说明、粗宋体引文，并把使用的字形嵌入 PDF；字体文件不随仓库分发。缺失时回退到 Arial Unicode，Windows 字体适配待完成。

首次启动无本地案例时会载入一个**明确标注的合成案例**。真实记录、截图、运行结果和密钥均被 Git 忽略，不随仓库分发。

## 使用

微信原生 ZIP：在微信中手动多选 → 合并转发 → 其他应用 → 通过 [Dukou](https://github.com/qzz0518/Dukou)「暂存到渡口」保存到本机，再在工作台左侧点击「导入微信 ZIP」，选择压缩包、填写群名和起止日期，点击「导入并查看材料」。无需解压。原来的「导入聊天记录」窗口中也有 ZIP 入口。不要选直接发送给模型的入口。网页会预填本机已保存的群名和日期，导入前仍可修改。每次 ZIP 总大小不超过 256 MB。终端入口 `import-wechat.command` 仍可用；新环境命令行使用下面的显式参数。导入不会自动调用模型，不需要微信数据库权限。当前只解析已核对的中文 TXT 格式；分批 ZIP 可一起导入，图片只按同批次文件引用关联，手动选择范围不代表完整历史。详见 [Mac 接入与路线比较](docs/MAC_ACCESS.md)。

```sh
python3 -m pip install -e '.[wechat]'
python3 scripts/import-wechat-zip.py '/本地/聊天记录.zip' \
  --group '所选群名' --start '2026-11-01T00:00:00+08:00' \
  --end '2026-11-01T23:59:59+08:00'
```

1. 点击“导入聊天记录”。可粘贴 `【甲】：……` 格式文字，导入 TXT、JSON、JSONL，或上传 PNG/JPEG。
2. 检查“全部材料”。程序保留材料编号、来源、图片和未知时间，不把段落当成原始微信消息。
3. 在“模型与接入设置”中选择入口，点击“生成分析报告”。所有方法均自动完成阅读稿编辑；页面显示主线提炼、审稿和返修进度。
4. 点击材料编号查看原文；“证据清单”按支持状态筛选；“运行记录”保留不同方法的结果。
5. 导出 PDF、含内嵌图片的独立 HTML 或 JSON。新报告先展示事件主线与阶段转折，再展开故事、解释支线作用，最后给出判断和待解问题；时间顺序的依据单独标记，完整判断清单与原图留在工作台。

自动编辑先区分单一事件、并行事件和残缺片段，再写故事。审稿在新上下文中对照原材料，检查主线、时间、因果、反证、结局和隐私；程序检查引用、原话和首页排版。发现问题最多自动返修两轮，仍未通过就保留候选稿并报告失败。无需每次要求助手手工改写，也不会将未通过的稿件发布为完成报告。

正常情况额外需要 3 次编辑调用，返修最多再加 4 次；提纲结构异常还可修复 1 次。耗时与模型用量会增加，分析与编辑分别记账。PDF 依赖或中文字体不可用时明确记录排版未检查，仍可生成 HTML；模型自审通过不等于现实事实已获认证。

编辑规则由程序与 [项目 skill](skills/chigua-analysis/SKILL.md) 共用。旧报告也可以运行 `python scripts/reader-edition.py <run_id>` 自动重编；成功后才替换阅读版，原始分析和旧版留档。

## 模型切换

### Codex

先在本机完成 `codex login`。默认复用登录状态，不读取或复制登录凭据。程序通过 `codex exec` 使用只读执行模式、新上下文和结构化输出；不允许分析流程通过材料中的指令调用工具。各次模型输出和调用记录留存在 `data/runs/`。

### DeepSeek

可在页面中填写接口、模型、密钥；设置仅保留到服务重启。也可复制 `.env.example` 为 `.env`：

```dotenv
CHIGUA_PROVIDER=deepseek
CHIGUA_BASE_URL=https://api.deepseek.com
CHIGUA_MODEL=deepseek-flash
CHIGUA_API_KEY=填入自己的密钥
```

DeepSeek 使用 `json_object`，其他兼容接口默认使用 JSON Schema。空输出、截断输出和无效引用会作为失败记录，不会伪装成完成。支持按所选模型能力传入原图；换用不支持视觉的模型时需先改为纯文字材料。

材料保存在本机，但使用云端模型时，**当前案例的文字与图片会发送给相应模型服务**。接口密钥不会写入报告、实验请求文件或 Git。

## 截图识别

Mac 本地 OCR 使用 Apple Vision，需安装 Xcode Command Line Tools：

```sh
mkdir -p tmp
swiftc scripts/ocr.swift -o tmp/ocr -module-cache-path tmp/swift-cache
```

OCR 不联网，保留原图、识别文字、坐标和置信度。识别失败时明确标注，并保留图片；不能当作没有信息。截图中的发言者与时间仍需要结合原图分析。

## 数据与可复现运行

Mac 自动采集已准备好 GreenBubbles 完整 JSON 的受限适配器，**尚未在本机真实数据库上验证**。它只接收精确群 ID 和明确时间窗口，分页结果先保存本地，不自动调用模型。首次获取数据库访问能力涉及微信签名和登录状态变更，demo 不执行这一步。入口与限制见 [Mac 接入调研](docs/MAC_ACCESS.md)。

- `data/cases/`：不可变的输入材料包。
- `data/uploads/`：上传原图。
- `data/runs/<id>/`：输入快照、提示、模型结果、耗时、用量和失败记录。
- `data/runs/<id>/analysis_report.json`：原始分析，供实验评分；`editorial/` 单独保存提纲、审稿、返修与排版检查，不能把润色后结果冒充原方法输出。
- `data/samples/demo.json`：仓库自带的合成样例。
- `skills/chigua-analysis/`：可复用的分析操作说明。

```sh
python3 -m chigua.cli seed-demo
python3 -m chigua.cli analyze syntheticdemo --provider codex --method B2
python3 -m chigua.cli export syntheticdemo --format pdf --output output/demo.pdf
python3 -m unittest discover -s tests -v
```

JSON 可使用 `{"messages":[{"id":"M1","speaker":"甲","text":"原文","timestamp":null,"children":[]}]}`。`children` 保存合并转发内部材料，`parent_id` 关联外层，`source_root` 只在有依据时填写。同样的文字不会被自动当作独立佐证，也不会仅凭内容相同就删除。

## 当前边界

- 已有 B0 普通提示、B1 详细提示、B2 证据工作流、A1 自由笔记流程的运行入口。
- A1 是机制检查的初步实现，正式实验仍需固定各阶段预算和评分规则。
- 引用校验只验证编号和结构；不证明事实正确、归责合理或模型客观。
- 当前材料量上限为 2000 单元 / 15 万字符，未实现超长群聊的分批检索与跨批事件合并。
- 没有稳定的 Mac / Windows 微信自动历史采集；没有语音、视频转写或外网调查。
- 没有完成 20 个真实案例、独立标注及留出集实验；demo 不是研究结果。

实施范围和接入路线见 [计划](docs/PLAN.md) 与 [Mac 接入调研](docs/MAC_ACCESS.md)。

小规模行为检查可先运行 `python scripts/prepare-variants.py`，再运行 `python scripts/run-smoke.py --provider codex --method B1`。该操作会运行四个案例，每例包括分析与自动编辑；预期行为和输出索引保存于被忽略的 `data/private/`，不把预期答案传给模型。自动编辑跨案例检查运行 `python scripts/eval-editorial.py --provider codex`，使用三份完全虚构的新材料，结果和 PDF 仅留本地。验证记录见 [验收说明](docs/VALIDATION.md)。
