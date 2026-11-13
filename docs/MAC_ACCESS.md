# Mac 微信自动采集：研究结论与适配器

核查日期：2026-11-14（香港时间）。结论：可以把现有本地数据库读取工具接到 demo；本轮完成协议适配与合成测试，尚未打通本机真实数据库。

## 本机实际检查

- Apple Silicon，macOS 27.0.1，微信 4.1.15；微信仍保留 Apple 签名和 Hardened Runtime。
- 使用仅查询权限、进程状态与控件类型的 Swift 探针，未查询窗口标题、聊天文字、联系人、控件值或截图。
- 获准在本机执行时，探针有辅助功能权限，微信正在运行。当前两个窗口共返回 10 个控件：2 个窗口、2 个容器、6 个按钮，没有聊天正文文本控件。这只说明当前窗口状态不能直接走文本控件采集，不能外推为所有微信页面都不可读。
- 受限执行环境中的同一探针曾报告无权限、应用未运行；该结果不能代表用户桌面的真实状态。
- 未安装第三方采集程序、未读取数据库或密钥、未重新签名微信、未退出登录、未修改系统保护。

## 路线判断

| 路线 | 已核对的证据 | 判断 |
|---|---|---|
| 辅助功能读取界面 | 本机当前窗口不暴露正文文本控件 | 暂不能作为稳定历史采集入口；指定群窗口状态仍需另测 |
| 截屏 / 滚动 + OCR | 本地 OCR 已可用，但时间、身份、重叠和历史边界都需核对 | 适合小范围补充，不承诺完整历史或展开所有转发 |
| GreenBubbles 本地数据库查询 | 开源，支持精确会话、时间范围、游标、消息 ID、覆盖状态；已有 Mac 初始化流程 | 当前最适合接统一证据格式的候选；需先验证 4.1.15 |
| wcdb-key-tool | 文档给出 macOS LLDB 与登录时密钥获取路线 | 是底层获取工具，不是完整采集接口；直接接入需额外实现数据库与媒体解析 |
| ExportWeChat CLI | 厂商提供 Mac CLI；文档要求 Apple Silicon、官网版微信，初始化会重启并重新登录 | 可作为另一候选；未安装、未审计、未验证当前 App Store 签名版本的支持情况 |
| 微信自带迁移与备份 | 苹果介绍支持设备间迁移与备份恢复 | 不等于提供可供本项目调用的结构化消息 API |

GreenBubbles 的查询路径只读，但首次密钥获取另有前提：管理员执行、对微信重新签名、退出并重新登录。维护者明确只记录了同一台 Mac、同一账号在 4.1.12 / 4.1.13 上的成功捕获；这不是 4.1.15 兼容性证明。当前不执行这些变更。

数据库密钥能打开对应账户的数据库副本，且不能像普通 API key 一样轮换。后续若采用此路线，应由独立初始化工具保存在仅当前用户可读的位置；MellonEater 不读取、打印或接收密钥文本，不把它送给模型。

## 已实现的接入代码

`chigua/wechat.py` 与 `scripts/capture-wechat.py` 对接 `greenbubbles messages list --json`，没有导入或执行第三方源码。

- 必须提供精确 `@chatroom` 群 ID、含时区的起止时间；每次不超过 31 天 / 2000 条 / 15 万字符，默认最多 500 条。
- 每页重复限定同一群及时间，逐条检查返回范围。越界、来源变化、重复消息内容变化、游标不前进都会停止。
- 使用原始不透明消息 ID 生成本地引用编号，保留原始 ID、来源标识、解码与截断状态。时间转换为明确的 UTC 时间，按来源顺序恢复先后。
- 分页上限、覆盖不足、工具告警都保留；“窗口查询结束”不能解释为“手机或服务器上的完整历史已拿到”。
- 当前只提取 Text / System / Revoke 文本。引用、合并转发和媒体保留为未解码占位，其完整载荷只存本机；不自动展开或读取文件路径。这是接入原型的明确缺口。
- 原始分页保存在被 Git 忽略的 `data/private/captures/`，案例进入现有工作台；新文件以当前用户私有权限创建。
- 采集不会启动任何模型调用。先在本地核对范围和原文，用户点击分析后才会发送所选案例到已配置模型。
- 不列举所有聊天，不自动搜索名字，不抓取全账户，不安装、不捕获密钥、不修改微信、不发送消息。

在**单独完成并验证工具初始化之后**，才使用下列入口；示例 ID 为合成占位：

```sh
python3 scripts/capture-wechat.py \
  --conversation 'synthetic@chatroom' \
  --start '2026-11-01T00:00:00+08:00' \
  --end '2026-11-01T23:59:59+08:00' \
  --limit 100 --title '指定群一天的材料'
```

成功后输出本机工作台链接。当前机器尚未具备已经验证的 GreenBubbles 初始化状态，不能把该命令当成已可用的真实采集演示。

## 下一步建议

1. 先在可恢复环境验证初始化对 4.1.15 的兼容性，以及签名、登录与更新后的行为。
2. 指定一个群的一天记录，最多 100 条；本地采集后与微信逐条核对发言者、时间、缺失情况，不发送给模型。
3. 补上引用与合并转发的内部消息、原始时间、媒体选择导入；禁止把未展开内容当成空消息。
4. 验收通过后再增加界面的群与时间选择，并考虑用户明确启动的增量同步。

## 来源与接口依据

- [GreenBubbles README](https://github.com/bojieli/greenbubbles/blob/main/README.md)：平台、查询入口与数据路径。
- [密钥获取及实测范围](https://github.com/bojieli/greenbubbles/blob/main/docs/PASSPHRASE_ACQUISITION.md)：签名、登录、权限与实际验证版本。
- [CLI 契约](https://github.com/bojieli/greenbubbles/blob/main/docs/CLI_REFERENCE.md)：JSONL 缺少原始 ID，完整 `--json` 才带来源与覆盖信息。
- [查询架构](https://github.com/bojieli/greenbubbles/blob/main/docs/ARCHITECTURE.md)：响应 envelope、游标和跨库一致性限制。
- [消息字段源码](https://github.com/bojieli/greenbubbles/blob/main/Native/GreenBubbles/src/live_query.rs)：MessageItem、content 枚举及解码状态。本次读取文件 blob SHA：`b67f93713703a79239f25388bfc5cda0536d41ac`。
- [wcdb-key-tool README](https://github.com/TANGandXUE/wcdb-key-tool/blob/main/README.md)：底层 macOS 获取路线；未复现其宣称的兼容性或账号安全结论。
- [ExportWeChat CLI](https://exportwechat.com/cli-usage)：厂商说明，未实测。
- [苹果对 Mac 微信的介绍](https://apps.apple.com/cn/mac/story/id1760592883)：迁移与备份能力。
