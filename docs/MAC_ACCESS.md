# Mac 微信接入：先验证手动导出，保留自动采集目标

核查日期：2026-11-14（香港时间）。当前选择：先用微信原生合并转发导出 ZIP，验证图文对应和本地报告流程，后续再接自动采集。用户指定的群、日期、记录、密钥和报告只保存在被 Git 忽略的本机目录。

## 路线比较

| 路线 | 已核对能力及限制 | 本项目判断 |
|---|---|---|
| [Dukou / 微信原生合并转发](https://github.com/qzz0518/Dukou) | 项目说明：Mac 微信 4.1.13 起可将多选记录导出为 TXT + 媒体 ZIP，提供离线查看；手动导出不读数据库、不改微信。自动多选依赖界面控件。 | 当前 MVP 首选。先试少量图文，再分批导出；已取得真实文本 ZIP；真实图片导出仍待验证。 |
| [GreenBubbles](https://github.com/bojieli/greenbubbles) | 精确群 ID、时间窗、分页、消息编号和媒体绑定；首次初始化涉及管理员权限、改签名及登录配合。维护者记录的密钥捕获实测版本为 4.1.12 / 4.1.13。 | 自动采集候选；适配及真实 CLI 的合成数据库测试已准备，不能视作本机真实采集通过。 |
| [Wechat-MCP](https://github.com/xerlxzx/Wechat-MCP) | 在微信副本上改签名，保留原安装；当前构建白名单仅 270102、270135。默认归档范围较广，WXGF 原图仍有缺口。 | 值得研究副本方式；本机 270115 不在支持范围，不能直接接入或绕过白名单。 |
| [wx-cli](https://github.com/pandorafuture/wx-cli) | 查询与媒体能力丰富；文档的 Mac 密钥获取路线要求关闭 SIP。GreenBubbles 使用其部分解析库。 | 不作为本次初始化入口；不为 demo 关闭系统保护。 |
| [WeChat Media Exporter](https://github.com/jasonqinzhou/wechat-media-exporter) | 通过微信界面保存媒体，不解密；针对 4.1.12 开发的早期测试版。 | 可研究补取媒体，不能单独保证文字与消息编号关联。 |
| [WechatExporter](https://github.com/BlueMatthew/WechatExporter) | 从手机备份制作离线记录，README 的验证环境较旧。 | 备用导入来源，不适合本轮 Mac 按群按时间增量采集。 |
| [chatlog 原项目](https://github.com/sjzar/chatlog) | README 为停止维护及移除代码的说明。 | 不作为新增依赖，也不采用未核验的分支二进制。 |

这是项目文档、源码与有限本机检查所得，不等于各工具在当前账户实测通过。

## 本机验证状态

- Apple Silicon、macOS 27.0.1、微信 4.1.15 build 270115。微信保留原签名及 Hardened Runtime；没有改签名、退出登录或关闭 SIP。
- 仅查询控件类型的探针返回 2 个窗口、10 个控件，没有正文文本控件。不能外推为所有页面永远不可读。Dukou 也记录了部分账户不暴露控件的限制，暂不能承诺其自动多选可用。
- 微信目录读取遭 macOS 拒绝，尚未读取真实群消息或密钥。手动 ZIP 路线不需要解除数据库目录限制。
- GreenBubbles v0.10.0 官方便携包已下载至忽略目录，SHA-256 与官方 Homebrew 配方一致，签名检查通过。仅运行版本检查、预检和合成数据库测试，没有初始化真实账户。
- Dukou v0.1.20 安装包 SHA-256 与[官方配方](https://github.com/qzz0518/homebrew-tap/blob/main/Casks/dukou.rb)一致，应用深度签名检查通过，macOS 公证评估返回 `accepted / Notarized Developer ID`。用户自行安装与启用暂存入口；未代用户发送聊天或启动同步。

## 手动导出流程

1. 安装 Dukou，只启用「暂存到渡口」等本地入口。默认配置可能启用 Codex / Claude 入口；本轮不选择这些入口，不添加附加 Prompt。
2. 在指定群先选少量文字和图片，合并转发 → 其他应用 → 暂存到渡口，将 ZIP 拖到本地文件夹。此操作不转发给其他联系人。
3. 工作台左侧点击「导入微信 ZIP」，选择文件并确认群名和日期，再点击「导入并查看材料」。本机已有范围会预填，可修改；每次 ZIP 总大小不超过 256 MB。也可继续使用终端入口。只导入，不自动分析。
4. 工作台核对发言人、分钟级时间和图片。小包通过后分批导出所需日期，核对各批首尾与重叠。完全相同 ZIP 在同次导入中跳过，其他重复文字保留。
5. 材料核对后再调用约定模型。模型分析会把所选案例的文字和图片发送给该模型服务，不能将「存本机」理解为「模型分析也不出本机」。

## ZIP 导入边界

实现：`chigua/wechat_zip.py`、`scripts/import-wechat-zip.py`。

- 只解析已核对的中文原生 `聊天记录.txt`：发言人、年月日和分钟时间、正文。支持 Dukou 合并包的 `batches/0001/聊天记录.txt`，不重复读取根目录汇总。
- 保留原 ZIP、SHA-256、条目位置、文本行号与附件引用；没有服务端消息编号。群名由用户指定，时间按香港时区解释，不虚构秒级精度或核实身份。
- 图片按同批次唯一文件名或相对路径绑定。重名歧义、缺图、损坏或过大图均为缺口，不按相邻时间猜配。原始字节本机留档，动态图预览首帧；不声称原始分辨率已获证明。
- 不运行 ZIP 内 HTML 或脚本、不加载外部链接、不按包内任意路径解压。拒绝路径越界、符号链接、重复或别名条目及不支持的压缩；限制展开大小、文件数与像素数。
- 时间窗外条目不进入案例，收到的 ZIP 仅作本机留档。单包超过 2000 条或 15 万字符拆成多案例，原条目与附图不拆开。每次最多 100 个 ZIP、2 万条材料。
- 手动选取一律不声明完整时间窗覆盖。未解析的语音、视频、文件、转发保留文字标记，不能视为内容已完整阅读。

格式依据为 Dukou 的 `WeChatForward.swift`、`WeChatAttachmentKind.swift`、`WeChatNativeArchive.swift`，检查时源码提交 `8c43324ae00d32c7cfb13a18b559ae0fc6db6d43`。这是本项目独立解析器，没有导入或执行这些源码。

## 自动采集接口与后续验收

`chigua/wechat.py`、`wechat_io.py`、`wechat_media.py` 对接 GreenBubbles v0.10.0 完整 JSON。`scripts/capture-wechat.py` 接受精确群 ID、时间、私有凭据文件和数据库目录，不安装、提取密钥或改签名。

- 逐页校验群、时间、来源、游标、重复消息变化及覆盖状态；每次最多 2000 条、15 万字符，有剩余页必须标记。
- 凭据由仅本人可读的普通文件直接接到工具标准输入，不读进 Python 字符串、不放进参数或模型请求；拒绝符号链接及宽权限文件。
- 按精确消息编号查询和提取图片，验证附件编号、字节数及 SHA-256 后关联；缺图和上限明确记录。
- 私有分页、图片、案例和预览均被 Git 忽略，不自动调用模型。V2 图片解码还会读取本地账户配置派生媒体密钥，配置内容不传给模型。

后续：验证当前构建初始化可恢复性 → 用户配合权限及必要登录步骤 → 指定群小时间窗实读 → 与微信逐条核对 → 增量游标和断点恢复 → 三天覆盖与缺图验收。改签名、退出或重新登录前仍须先告知用户，不能因本次选了手动导出而擅自继续初始化。

协议依据：[CLI](https://github.com/bojieli/greenbubbles/blob/v0.10.0/docs/CLI_REFERENCE.md)、[密钥获取约束](https://github.com/bojieli/greenbubbles/blob/v0.10.0/docs/PASSPHRASE_ACQUISITION.md)、[媒体绑定源码](https://github.com/bojieli/greenbubbles/blob/v0.10.0/Native/GreenBubbles/src/live_attachment.rs)、[Wechat-MCP 构建白名单](https://github.com/xerlxzx/Wechat-MCP/blob/main/src/wechat_bridge/adapters/wechat_4_1.py)。
## ZIP 缺图与工作流接入（2026-11-14）

渡口导出已经接入本地导入流程，但稳定的自动历史采集尚未完成。完整步骤及能力边界见 [采集验收说明](../skills/chigua-analysis/references/wechat-acquisition.md)。

可先运行 `python scripts/inspect-wechat-zip.py <ZIP>`，只看数量、不输出聊天正文。图片标记与图片文件必须分开核验；只有 TXT 的包不能恢复图片。网页现会持续显示本包缺图数，PDF/HTML 阅读报告带有文中引用的完整原文附录，含原始显示名，仅适合私下核对。
