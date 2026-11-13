# MellonEater · 知瓜

把聊天里的事件、各方说法、证据和未知项放在一起，生成可以回查原文的争议分析报告。

当前为 **macOS 本地 MVP**：上传或粘贴材料 → 本地规范化与截图 OCR → Codex / DeepSeek 分析 → 证据工作台 → HTML / PDF。微信历史自动读取仍在接入调研阶段。

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

1. 点击“导入聊天记录”。可粘贴 `【甲】：……` 格式文字，导入 TXT、JSON、JSONL，或上传 PNG/JPEG。
2. 检查“全部材料”。程序保留材料编号、来源、图片和未知时间，不把段落当成原始微信消息。
3. 在“模型与接入设置”中选择入口，点击“生成分析报告”。四阶段流程通常比单次提示更慢。
4. 点击材料编号查看原文；“证据清单”按支持状态筛选；“运行记录”保留不同方法的结果。
5. 导出 PDF、含内嵌图片的独立 HTML 或 JSON。新报告先展示事件主线与阶段转折，再展开故事、解释支线作用，最后给出判断和待解问题；时间顺序的依据单独标记，完整判断清单与原图留在工作台。

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

小规模行为检查可先运行 `python scripts/prepare-variants.py`，再运行 `python scripts/run-smoke.py --provider codex --method B1`。该操作会实际调用模型四次；预期行为和输出索引保存于被忽略的 `data/private/`，不把预期答案传给模型。验证记录见 [验收说明](docs/VALIDATION.md)。
