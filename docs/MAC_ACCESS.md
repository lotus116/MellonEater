# Mac 微信聊天记录获取路线

调研日期：2026-11-14（香港时间）。

## 本机证据

- 已从应用元数据确认微信版本为 4.1.15。
- 当前执行环境列举微信容器 Documents 目录返回 `Operation not permitted`。具体是操作系统隐私权限还是执行环境限制，尚未定位；不能据此断言数据库不存在。
- 用户此前提供的独立截图可读取。Apple Vision 本地 OCR 已在获得执行权限的本机进程中识别出文字，受限运行环境中曾失败。
- 未读取、解密微信数据库，未修改微信安装或签名。

## 路线比较

| 路线 | 当前证据 | 本项目安排 |
|---|---|---|
| 粘贴文字 / 导入已保存材料 | 本地流程已实现 | 当前 MVP 默认入口 |
| 上传截图 + 本地 OCR | 保留原图、识别行与坐标；已实测独立截图 | 当前 MVP 图片入口，身份与时间需原图复核 |
| macOS 辅助功能读取微信界面 | 尚未检查本机可访问树与滚动行为 | 后续选择指定窗口、小范围只读验证；不能先承诺完整历史 |
| GreenBubbles 本地数据库读取 | 官方仓库声明支持 Apple Silicon、macOS 14+，属于 research alpha | 候选适配器；首次设置会获取账户数据库密钥并重新签名微信，需要单独评估后才能执行 |
| 微信备份文件 | 未验证本机格式与可读性 | 不把“可以备份”当成“可以读到结构化消息” |

## GreenBubbles 已核对的接口

仓库 README 声明其读取本机已有数据库，首次初始化需要管理员权限并重新签名微信。当前没有安装或运行该初始化，也没有验证其对本机 4.1.15 的实际兼容性。

文档中的消息列表输出为 JSON Lines：首行为分页信息，后续消息含 `from`、`self`、`at`、`text`，可用媒体可能有 `file`。分页使用 `hasMore`、`nextCursor`，时间范围使用 `since`、`until`。默认排序为 newest；导入器需要恢复时间顺序并保留未知时区。

后续适配必须先固定一个群和时间范围，记录覆盖与失败，不自动读取所有聊天。外部导出中的文件路径只应作为待选择的附件提示，不直接通过路径读取任意本地文件。合并转发是否完整还需原始样本实测。

## 建议顺序

1. 先用真实文字和截图验证分析价值，保留统一输入格式。
2. 小范围检查 Mac 微信界面可访问性，判断能否稳定读取所选消息。
3. 如需数据库路线，先审查并在独立可恢复环境评估工具兼容性；对微信安装或系统权限的变更另行决定。
4. Windows 采集器接入相同格式，重复同一套完整性测试。

## 来源

- [GreenBubbles README](https://github.com/bojieli/greenbubbles/blob/main/README.md)：平台、初始化及能力范围。
- [GreenBubbles CLI reference](https://github.com/bojieli/greenbubbles/blob/main/docs/CLI_REFERENCE.md)：消息字段、分页和时间范围。
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)：JSON 返回格式与空输出情况。
- [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/)：所选模型的图片输入形式。

第三方仓库文档是可行性线索，不是本机已接入的证明。
