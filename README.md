# Dual Claude

在同一台 Mac 同时使用官方 Claude 与 CC Switch 第三方供应商，支持终端 CLI、Claude Desktop 图形双实例，以及可选 Docker 隔离环境。

| 使用方式 | 官方入口 | 第三方入口 | 详细说明 |
| --- | --- | --- | --- |
| 终端 CLI | 原生 `claude` | `claude-cc` | 下方快速开始 |
| Desktop GUI | `Claude Official.app` | `Claude CC.app` | [图形版安装与验证](desktop/README.md) |
| Docker | `./dual-claude docker run official` | `./dual-claude docker run cc` | 下方 Docker 章节 |

管理脚本只依赖 Python 3.9+ 标准库。CLI 方案需要已安装 `claude`；GUI 方案需要 macOS、Claude Desktop 和 Xcode Command Line Tools；Docker 方案需要 Docker Desktop 与 Compose v2。三种方式可按需选择，GUI 不需要先安装 CLI 或 Docker。

完整设计、配置目录和验收范围见 [plan.md](plan.md)。

## 直接使用

```sh
# 在工程根目录执行
./dual-claude install
```

随后按下方“配置规则”设置 CC Switch 的 **Claude Code** 目录及供应商，运行 `./dual-claude doctor` 检查，再打开两个终端分别运行：

```sh
# 终端 A：官方账户，保留原有 macOS Keychain 登录
claude
```

```sh
# 终端 B：CC Switch 第三方配置
claude-cc
```

`claude` 保持原生行为，`claude-cc` 在当前工作目录启动并原样传递 Claude 参数，例如 `claude-cc --model sonnet`。安装可重复执行；只在 `~/.local/bin` 创建 `claude-cc` 和管理工具 `dual-claude` 的链接，不接管原生 `claude`，不修改 shell 文件、CC Switch 数据库或账户认证。工程目录须保留；移动前先卸载，移动后再安装。

不安装到 PATH 也可以使用统一入口；管理参数放在 profile **之前**，Claude 参数放在 `--` **之后**：

```sh
./dual-claude run cc -- --model sonnet
./dual-claude run --workdir ../my-project cc -- --model sonnet
```

`--workdir` 必须指向已存在目录。两个实例同时修改代码时，使用不同项目目录或 git worktree。

## 配置规则

| 实例 | 配置 | 登录与路由 |
| --- | --- | --- |
| 原生 `claude` | 默认 `~/.claude` | 按 Claude 原生规则读取环境与配置，保留已有官方登录 |
| cc | `~/.claude-cc` | 清除继承的路由变量，再读取 CC Switch 写入的第三方配置 |

在 CC Switch → 设置 → 高级 → 配置文件目录，将 **Claude Code 配置目录** 设置为当前用户的 `~/.claude-cc` 对应的绝对路径，保存并启用第三方供应商。可以执行以下命令获取应填入的路径：

```sh
printf '%s\n' "$HOME/.claude-cc"
```

脚本不会自动移动登录信息或修改运行中的 CC Switch。第三方缺少有效 endpoint/认证，或其目录指向官方目录时会停止；不会静默退回官方账户。管理器诊断和验证官方配置时，若发现用户 settings 含路由或认证覆盖，也会停止并提示检查。报错不会输出设置文件内容或 token。

原生 `claude` 不经过本工程的环境清理。为保持它使用官方账户，不要全局设置第三方 endpoint/token 或 `CLAUDE_CONFIG_DIR`，并检查项目 settings 中是否有供应商覆盖。第三方配置只交给 CC Switch 的独立目录管理。

`claude-cc` 默认只加载 `--setting-sources user`，因此项目/local settings 中的 hooks、权限等也不自动加载；原生 `claude` 保持自己的配置加载规则。需要第三方入口加载项目配置时先审查路由，再显式运行：

```sh
claude-cc --setting-sources user,project,local
```

显式 Claude 参数可以覆盖默认行为。这是防止误配的启动器，不是安全沙箱；系统 managed settings、共享文件及进程权限仍可能影响运行。切换供应商后新建会话；Skills/MCP/插件按需独立配置。

第三方 settings 已有 `model` 时保持其选择；否则若配置了 Sonnet 模型槽位，默认使用 `--model sonnet`。具体模型由供应商配置中的槽位映射决定。

## 诊断与真实请求验证

```sh
# 只检查 CLI、配置和认证状态，不发送模型提示
./dual-claude doctor
./dual-claude doctor --docker

# 会产生少量模型用量：并发检查两路，默认每路超时 60 秒
./dual-claude smoke

# 单独验证第三方，或容器第三方
./dual-claude smoke --profile cc
./dual-claude smoke --docker --profile cc --timeout 60 --budget 0.10
```

验证在临时空目录中发送固定标记，禁用工具、自定义 hooks 和 MCP，不读取现有业务项目。超时会终止本次进程组，并清理本次命名的临时容器；Ctrl+C 也会触发清理。

`--budget` 是每路 Claude CLI 的 USD 估算预算，**不是第三方服务端硬扣费上限**。仅保存结果摘要，不保存原始调试日志；报告位于 `~/.local/state/dual-claude/reports/`，权限 `0600`。

退出码：`0` 表示所选检查全部通过，`1` 表示诊断/请求未通过，`2` 表示配置或依赖错误，`130` 表示用户中断。`doctor` 的已登录状态不能代替 `smoke` 的请求成功结果。

## Claude Desktop 图形界面（macOS，可选）

```sh
./dual-claude desktop install
./dual-claude desktop doctor
open "$HOME/Applications/Claude Official.app"
open "$HOME/Applications/Claude CC.app"
```

会创建个人 Applications 目录中的 `Claude Official.app` 和 `Claude CC.app`。官方使用独立 Profile，CC Switch 继续管理默认 Desktop 第三方配置；原生 CLI 命令不变。首次官方登录需自行完成，第三方模型映射在 CC Switch 的 **Claude Desktop** 页面配置。安装、验证和回退说明见 [desktop/README.md](desktop/README.md)。

已验证官方 GUI 和第三方 GUI 均可返回测试标记，两进程同时运行，官方测试期间第三方网关无新增请求。该结论适用于已验证的版本与配置，具体范围见图形版说明；不代表 CLI 或 Docker 的官方认证已一并验证。

## Docker

```sh
./dual-claude docker build

# 两个终端分别启动，默认使用 docker/project-official 和 project-cc
./dual-claude docker run official
./dual-claude docker run cc

# 官方容器独立登录，交互授权由用户完成
./dual-claude docker login official

# 挂载已有项目：管理参数仍放在 profile 之前
./dual-claude docker run --workdir ../my-project cc -- --model sonnet
./dual-claude docker status
```

官方与第三方使用独立 named volume，登录和会话跨容器保留；`run --rm` 退出只删除容器。未挂载宿主机官方 Keychain，官方容器需单独登录。默认非 root 运行，不发布端口，不开启跳过权限确认。

第三方配置只读挂载，启动时复制 settings 至容器自己的卷，不回写宿主机；CC Switch 切换后重新创建第三方容器。依赖宿主机路径的 apiKeyHelper、hooks、MCP 需要适配容器路径。

Docker 默认固定 Claude Code `2.1.311`，Compose 默认使用 `node:22-alpine`。如需更换基础镜像或版本，可通过环境变量覆盖：

```sh
DUAL_CLAUDE_NODE_IMAGE=node:22-bookworm-slim ./dual-claude docker build
DUAL_CLAUDE_VERSION=2.1.311 ./dual-claude docker build
```

构建和运行须使用同一版本变量；两个 Docker 服务共享构建出的镜像。

CC Switch 接管代理若使用 `127.0.0.1`，容器会停止并提示。确认监听与容器可达性后可显式覆盖：

```sh
CC_PROXY_BASE_URL=http://host.docker.internal:15721 ./dual-claude docker run cc
```

使用直连供应商地址时不需要该变量。使用宿主机代理时，应先检查代理监听地址及容器可达性。

## 可选环境变量

| 变量 | 默认值 / 用途 |
| --- | --- |
| `DUAL_CLAUDE_CC_CONFIG_DIR` | `~/.claude-cc`，须与 CC Switch 目录一致 |
| `DUAL_CLAUDE_STATE_DIR` | `~/.local/state/dual-claude`，报告与安装记录 |
| `DUAL_CLAUDE_BINARY` | PATH 中的 `claude`，可指定其他已安装 CLI |
| `DUAL_CLAUDE_DESKTOP_APP` | Desktop 原版应用，默认 `/Applications/Claude.app` |
| `DUAL_CLAUDE_VERSION` | Docker CLI 版本 `2.1.311` |
| `DUAL_CLAUDE_NODE_IMAGE` | Compose 默认 `node:22-alpine` |
| `DUAL_CLAUDE_OFFICIAL_WORKDIR` | Docker 官方工作目录，可被 `--workdir` 覆盖 |
| `DUAL_CLAUDE_CC_WORKDIR` | Docker 第三方工作目录，可被 `--workdir` 覆盖 |
| `CC_PROXY_BASE_URL` | Docker 访问宿主机 CC Switch 代理时的可达 URL |

配置通过进程环境传入；Python 入口不自动加载 `.env`。不要将 API key/token 放入这些管理变量、脚本或仓库，继续由 CC Switch 管理。

## 卸载与验证脚本

```sh
./dual-claude uninstall

# 无外部模型请求，使用临时目录和假 CLI
python3 -m unittest discover -s tests -v
```

卸载只移除仍指向本工程的命令链接；不删除配置、会话、报告、Docker 镜像或卷。安装或卸载时会清理本工程旧版安装的官方别名，保留用户自己的同名文件或链接。自定义安装目录时，对 install/uninstall 使用相同的 `--bin-dir "$HOME/bin"`。若需要恢复 CC Switch 原目录，参见 [plan.md](plan.md) 的回退步骤。

## 验证与故障定位

使用 `doctor` 检查配置与认证，再用 `smoke` 验证实际请求。成功请求应返回所选实例对应的固定标记；任一路失败时，整体检查返回非零退出码。遇到官方 `403 Request not allowed` 时，应结合原生 CLI 请求、账户权限和网络情况排查；“已登录”不代表请求一定可用。脚本不会自动退出现有账户或更改网络。设计说明、验收标准和回退步骤见 [plan.md](plan.md)。
