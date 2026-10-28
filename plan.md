# 官方 Claude Code 与 CC Switch 第三方源双实例方案

## 目标与适用范围

在同一台电脑同时运行两个 Claude Code CLI 实例：一个使用官方账户，另一个使用 CC Switch 管理的第三方供应商。CLI 是可多进程运行的客户端，不需要部署两个监听端口的服务。

日常使用优先选择独立配置目录；需要进一步隔离依赖和代码执行环境时使用 Docker。Claude Desktop 和 IDE 扩展有各自的配置体系，不属于本工程自动配置的范围。

## 工程入口

在工程根目录执行：

```sh
./dual-claude install
./dual-claude doctor --docker
```

安装器使用当前用户的 Home 和工程所在目录生成命令链接，不包含开发者电脑的绝对路径。完整示例见 [README.md](README.md)。

| 功能 | 命令 |
| --- | --- |
| 安装命令 | `./dual-claude install` |
| 配置与认证诊断 | `./dual-claude doctor` |
| 本机官方实例 | 原生 `claude` |
| 本机第三方实例 | `claude-cc`，或 `./dual-claude run cc` |
| 真实请求验证 | `./dual-claude smoke` |
| 构建 Docker 镜像 | `./dual-claude docker build` |
| 启动容器 | `./dual-claude docker run official` 或 `cc` |
| 官方容器登录 | `./dual-claude docker login official` |
| 卸载命令链接 | `./dual-claude uninstall` |

## 本机隔离设计

| 实例 | 配置目录 | 认证与路由 |
| --- | --- | --- |
| 官方：原生 `claude` | 默认 `~/.claude` | 保持原生环境与配置加载规则，保留默认账户登录 |
| 第三方 | `~/.claude-cc`，可通过环境变量覆盖 | 读取 CC Switch 写入的 endpoint、认证和模型设置 |

只为第三方新增 `claude-cc` 启动命令，`dual-claude` 用于安装、诊断和容器管理，不接管原生 `claude`。安装会清理本工程旧版安装的官方别名，不删除用户自己的同名文件或链接。

`claude-cc` 会清理继承的 `ANTHROPIC_*`、`CLAUDE_CODE_USE_*`、`CLAUDE_CODE_OAUTH_*` 等路由或认证变量，再读取独立配置。管理器内部诊断和验证官方配置时也使用环境清理，但直接运行原生 `claude` 不经过此逻辑。

为保留原生 `claude` 的官方登录，不要在全局环境设置第三方 endpoint/token 或 `CLAUDE_CONFIG_DIR`，并检查项目配置中的路由覆盖。不要把官方认证目录整体复制到第三方目录。

配置检查采用以下规则：

- 第三方目录不能与官方目录相同，包括通过符号链接指向同一目录。
- 第三方必须配置有效的非官方 HTTP(S) endpoint，以及 token、API key 或 apiKeyHelper，避免静默退回官方来源。
- 管理器诊断和验证官方配置时，若用户 settings 包含认证或路由覆盖，停止检查并提示用户审查，不自动覆盖原文件。
- 不在工程、测试报告或报错中输出真实 API token。

第三方启动器及管理器内部检查默认只加载 `--setting-sources user`，排除项目和 local settings，防止它们覆盖路由。项目 settings 中的权限、hooks 等也不会自动加载；原生 `claude` 保持原生加载规则。审查后可以显式启用第三方的项目配置：

```sh
claude-cc --setting-sources user,project,local
```

显式 CLI 参数可以覆盖启动器默认值。该机制不构成完整沙箱，CLAUDE.md、MCP、系统 managed settings、共享文件和操作系统权限仍需按使用场景管理。

## 配置 CC Switch

在 CC Switch → 设置 → 高级 → 配置文件目录，将 Claude Code 配置目录设为当前用户的 `~/.claude-cc` 对应的绝对路径，保存并启用第三方供应商。可执行以下命令取得路径：

```sh
printf '%s\n' "$HOME/.claude-cc"
```

自定义目录时，启动脚本的 `DUAL_CLAUDE_CC_CONFIG_DIR` 必须与 CC Switch 中的目录一致。安装器不修改运行中的 CC Switch、数据库或账户登录。

切换供应商后建议新建第三方会话：从 settings 删除的环境变量可能仍保留在旧进程中。不要把 CC Switch 的管理目录改回官方目录后继续切换第三方。

第三方 settings 已设置 `model` 时保留其选择；否则若存在 Sonnet 槽位映射，默认传入 `--model sonnet`。可以通过 CLI 显式选择其他模型。

## 文件与执行环境

本机方案隔离配置、认证和会话存储，不隔离工作文件或操作系统权限。两个 Agent 同时修改仓库时，使用不同项目目录或 git worktree。Skills、插件和 MCP 按需独立配置。

脚本从自身位置定位工程，通过 `Path.home()` 获取用户目录，支持相对工作目录和包含空格的参数。安装使用符号链接，工程目录需要保留；移动工程前先卸载，移动后重新安装。

## Docker 设计

文件：`docker/Dockerfile`、`docker/compose.yaml`、`docker/entrypoint.cjs`。

- 官方与第三方使用独立配置卷和独立默认工作目录。
- 非 root 用户运行，不启用跳过权限确认，不发布端口。
- 第三方配置只读挂载，启动时仅复制 settings 到容器自己的配置卷，不回写宿主机。
- 不挂载整个 Home、SSH、Docker socket 或宿主机官方 Keychain。
- 官方容器需要独立登录；named volume 在容器退出后保留认证和会话。
- 容器启动时读取供应商配置，切换供应商后重新创建容器。
- 使用宿主机绝对路径的 hooks、MCP 或 apiKeyHelper，需要适配 Linux 容器路径。

Compose 默认使用 `node:22-alpine`，Claude Code 默认固定为 `2.1.311`。可以通过 `DUAL_CLAUDE_NODE_IMAGE` 和 `DUAL_CLAUDE_VERSION` 覆盖。构建和运行应使用一致的版本变量。

`/home/node/.claude` 和 `/workspace` 是镜像内的固定路径，与宿主机用户名及工程位置无关。

宿主机 CC Switch 接管代理若配置为 `127.0.0.1`，容器无法直接照搬。入口脚本会停止并提示；检查代理监听和容器可达性后，可以显式设置：

```sh
CC_PROXY_BASE_URL=http://host.docker.internal:15721 ./dual-claude docker run cc
```

仅替换地址不保证代理可达。使用直连供应商地址时无需该变量，也不应为方便访问而直接将代理开放到局域网。

## 验收标准

| 检查 | 预期结果 |
| --- | --- |
| 重复安装 | 不覆盖无关文件，允许重复执行 |
| 官方认证 | 原生 `claude` 保持已有登录与配置行为，全局及项目配置应指向预期的官方来源 |
| 第三方认证 | 使用独立目录的供应商配置，不静默退回官方来源 |
| 配置异常 | 无效 JSON、目录冲突或认证缺失时明确报错，不输出密钥 |
| 参数传递 | 保留用户显式传入的 Claude 参数及包含空格的值 |
| 本机真实请求 | 所选实例返回对应固定标记 |
| 容器真实请求 | 所选容器返回对应固定标记，官方容器先完成独立登录 |
| 超时或中断 | 终止本次进程组并清理本次临时容器 |
| 报告权限 | 摘要报告权限为 `0600`，不保存原始调试日志 |
| 卸载 | 只移除仍指向本工程的命令链接，保留配置与会话 |

自动化测试不请求模型 API：

```sh
python3 -m unittest discover -s tests -v
```

真实请求验证会产生少量用量：

```sh
./dual-claude smoke
./dual-claude smoke --docker --profile cc
```

验证使用临时空目录、固定标记提示，并禁用工具、自定义 hooks 和 MCP。`--budget` 是 CLI 估算预算，不是第三方服务端硬扣费上限。

报告默认位于 `~/.local/state/dual-claude/reports/`，可通过 `DUAL_CLAUDE_STATE_DIR` 覆盖。报告应由使用者在各自环境中生成，不将开发者电脑的运行记录作为通用配置的一部分。

## 故障定位

`doctor` 只检查配置与认证，不保证模型请求一定成功。第三方 `auth status` 中的认证标签也不能单独证明实际请求来源，应结合 settings 与 `smoke` 返回结果判断。

官方请求出现 `403 Request not allowed` 时，对照原生 CLI 请求，检查账户订阅、角色权限、认证和代理链路。脚本不自动退出账户或更改网络设置。[官方排查说明](https://code.claude.com/docs/en/troubleshoot-install#403-forbidden-after-login) 列出了相关检查项。

Docker 构建失败时，检查基础镜像、npm registry、网络与镜像站配置，不自动修改全局 Docker 设置。

## 其他方案

| 方案 | 适用情况 |
| --- | --- |
| 独立配置目录与启动命令 | 日常双来源使用，资源占用较低 |
| Docker / Dev Container | 需要隔离依赖与代码执行环境 |
| 临时环境变量 | 临时调用固定供应商，仍需独立目录隔离认证和会话 |
| 两个操作系统用户 | 需要独立系统账户、Keychain 和文件权限 |

## 回退

执行 `./dual-claude uninstall` 移除本工程安装的命令链接。自定义安装目录时，使用与安装一致的 `--bin-dir`。

若需恢复 CC Switch 原先的默认目录，先关闭第三方会话，在界面中恢复当前用户的 `~/.claude` 绝对路径并保存，然后切回官方供应商。不要在官方目录中启用第三方供应商。

卸载不删除配置、账户登录、会话、报告、备份、Docker 镜像或卷。已有其他会话运行时，不要整体覆盖官方配置文件或 CC Switch 数据库。

Docker 使用 `--rm` 删除退出后的容器，配置卷继续保留。仅在确定要删除容器登录与会话时才使用 `down -v`。

## 来源

- [Claude Code 多账户与 Keychain](https://code.claude.com/docs/en/authentication)
- [环境变量及运行时更新](https://code.claude.com/docs/en/env-vars)
- [settings 范围和优先级](https://code.claude.com/docs/en/settings)
- [官方 Dev Container](https://code.claude.com/docs/en/devcontainer)
- [CC Switch 配置目录源码](https://github.com/farion1231/cc-switch/blob/v3.20.3/src-tauri/src/config.rs)
- [Docker Desktop 网络说明](https://docs.docker.com/desktop/features/networking/)
