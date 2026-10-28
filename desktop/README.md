# Claude Desktop 图形双实例（macOS）

在 CLI 方案之外，可选安装两个图形入口，复用已安装的原版 Claude Desktop，无需 Docker 或 ImageMagick。

## 安装

需要 macOS、Claude Desktop，以及 Xcode Command Line Tools 提供的 `clang`、`codesign`。在工程根目录执行：

```sh
./dual-claude desktop install
./dual-claude desktop doctor
```

原版应用默认位于 `/Applications/Claude.app`。自定义安装位置时，安装和检查使用相同变量：

```sh
DUAL_CLAUDE_DESKTOP_APP="$HOME/Applications/Claude.app" ./dual-claude desktop install
```

安装会编译原生启动器，复制原版图标、执行本地签名，并创建：

| 入口 | 用途 | 用户数据目录 |
| --- | --- | --- |
| `~/Applications/Claude Official.app` | 独立官方实例 | `~/Library/Application Support/Claude-Official` |
| `~/Applications/Claude CC.app` | CC Switch 第三方实例 | 默认 Desktop 的 `Claude` / `Claude-3p` 目录 |

安装器不修改原版应用、不添加登录启动项、不复制已有账户 token、Cookies、聊天或 MCP 配置。新官方 Profile 需要自行登录。官方 Profile 的 `deploymentMode` 初始化为 `1p`；已有 Profile 若配置为第三方或 managed 模式，安装器停止并保留文件。

重复安装只替换本工程标识的启动器，也允许迁移 `claude-dual-launcher` 的标准 Official 启动器。被替换的启动器和相关官方配置会备份到 `~/.local/state/dual-claude/desktop/`，不覆盖其他应用或应用符号链接。

## 配置 CC Switch

在 CC Switch 中选择 **Claude Desktop**，不要改动 Claude Code 页面。给默认 Desktop 配置供应商；若实际模型名称不属于 Desktop 支持的 Claude 角色 ID，选择“模型映射”，填写供应商支持的模型，并保持 CC Switch 本地路由运行。

这里不要求 CC Switch 支持自定义 Desktop 目录：它继续管理默认的 `Claude` 和 `Claude-3p`，官方实例使用独立的 `Claude-Official` 与 `Claude-Official-3p`。`desktop doctor` 检查四个目录的模式和第三方 Gateway 配置，不修改 CC Switch。

模型的 1M 上下文声明应与供应商能力一致。切换供应商或改变映射后，退出并重启第三方 Desktop 实例。

新环境可按以下顺序配置：先安装启动器，再配置 CC Switch 的 Desktop 供应商与模型映射，最后启动两个入口、完成官方登录并运行 `desktop doctor`。如果检查提示缺少第三方 Profile，应先在 CC Switch 中启用供应商，再检查一次。

## 启动与验证

在 Finder 的个人 Applications 文件夹中双击两个入口，或运行：

```sh
open "$HOME/Applications/Claude Official.app"
open "$HOME/Applications/Claude CC.app"
```

不要同时打开原版默认实例和 Claude CC 的同一数据目录。启动器检查已运行的 Profile，避免重复启动到同一目录；会清理继承的 Claude/Anthropic 路由环境变量，Desktop 的 Gateway 仍从自己的目录读取。

验证步骤：

1. 官方入口完成官方账户登录；第三方入口应显示对应 Gateway 和映射模型。
2. 在第三方空白会话中只要求返回测试标记，检查 CC Switch 日志中的上游模型与 HTTP 状态。
3. 官方入口单独发送测试请求，确认使用官方账户，不进入第三方网关日志。
4. 在 CC Switch 中切换默认 Desktop 供应商并恢复，检查独立官方 Profile 的模式与配置未变。

`desktop doctor` 不发模型请求，成功仅代表配置检查通过，不能替代 GUI 请求验证。第三方 Gateway 功能取决于 Desktop 版本，可能显示 Cowork/Code，不应将其视为官方云端 Chat 功能的完整替代。

此机制依赖 Desktop 对 `--user-data-dir` 和配置模式的实际处理。更新后应重新检查目录和路由，不能仅凭双窗口运行就认定认证、Keychain 或所有后台功能均已隔离。

隔离针对本地 Profile。官方云端聊天历史和项目仍属于登录账户，同一账户在不同 Profile 中可能显示相同的云端数据。

## 已验证范围

验证覆盖 macOS、CC Switch `3.20.3`，以及下表列出的 Desktop 版本。结果只记录功能与固定测试标记，不包含账户、供应商凭据、个人目录或原始聊天内容。

| 检查 | 结果 |
| --- | --- |
| 独立官方 Profile 登录 | Desktop `4.29.0`：官方 Pro 登录成功，进入官方普通聊天界面 |
| 官方 GUI 请求 | Desktop `4.29.0`：返回 `OFFICIALGUIOK`；测试期间第三方 Desktop 网关无新增请求 |
| 第三方 GUI 请求 | Desktop `1.46388.4`：返回 `DESKTOP_CC_OK`；CC Switch 日志记录实际映射模型及 HTTP 200 |
| 更新后第三方启动 | Desktop `4.29.0`：重新打开第三方入口，Gateway 与模型映射加载正常；未在该版本重发第三方模型测试请求 |
| 双实例运行 | 官方与第三方主进程同时存在，分别使用独立官方目录和默认第三方目录 |
| 供应商切换 | 默认 Desktop 在官方与第三方供应商间切换并恢复，独立官方配置未被改写 |
| 模式检查 | `Claude` / `Claude-3p` 为 `3p`，`Claude-Official` / `Claude-Official-3p` 为 `1p` |
| 回归检查 | CLI 环境清理与参数转发、Profile 路径检查、原生启动器重复检测等 19 项测试通过 |

应用启动后可能写入偏好设置；“供应商切换未改写官方配置”不意味着官方应用自身不会更新文件。此验证没有证明所有 Desktop 版本、Keychain 项、后台功能或第三方模型均完全隔离。CLI 和 Docker 的官方请求需要各自验证，不能用 GUI 成功替代。

## 回退

退出对应实例，在 Finder 中删除两个启动器即可；原版 Claude Desktop 和 CLI 不受影响。保留 Profile 目录可保留各自的登录与会话。不要将备份或账户数据放进源码仓库。

恢复默认 Desktop 的官方模式时，在 CC Switch 的 Claude Desktop 页面切回官方供应商并重启默认实例，此操作不应修改独立官方 Profile。

## 来源与许可

启动器基于 [jeroenwollaars/claude-dual-launcher](https://github.com/jeroenwollaars/claude-dual-launcher) 的 Profile 启动思路，改用无 shell 插值的进程检查，增加路径边界和默认第三方目录的重复运行检测。组件许可见 [LICENSE](LICENSE)，编译后也会放入启动器资源目录。

CC Switch 默认目录行为参考其 [Desktop 配置实现](https://github.com/farion1231/cc-switch/blob/v3.20.3/src-tauri/src/claude_desktop_config.rs)。
