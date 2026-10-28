"""Dual Claude CLI management. Python standard library only; no stored secrets."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("official", "cc")
AUTH_FIELDS = ("loggedIn", "authMethod", "apiProvider", "configDirectory", "subscriptionType")
ROUTING_KEYS = {
    "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS",
    "CLAUDE_CODE_API_KEY_HELPER", "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_BASE_URL",
}


class ConfigError(Exception):
    pass


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def state_dir():
    return Path(os.environ.get("DUAL_CLAUDE_STATE_DIR", str(Path.home() / ".local/state/dual-claude"))).expanduser().resolve()


def config_dir(profile):
    if profile == "official":
        return Path.home() / ".claude"
    return Path(os.environ.get("DUAL_CLAUDE_CC_CONFIG_DIR", str(Path.home() / ".claude-cc"))).expanduser().resolve()


def load_json(path, required=False):
    if not path.exists():
        if required:
            raise ConfigError(f"缺少 {path}。请在 CC Switch 中设置此配置目录并启用第三方供应商。")
        return {}
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        raise ConfigError(f"无法读取有效 JSON：{path}（内容未输出）。") from None
    if not isinstance(value, dict):
        raise ConfigError(f"JSON 顶层必须是对象：{path}")
    return value


def is_routing_key(key):
    return key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_OAUTH_")) or key in ROUTING_KEYS


def clean_env():
    return {k: v for k, v in os.environ.items() if not is_routing_key(k)}


def validate_profile(profile):
    config = config_dir(profile)
    if profile == "cc" and config == config_dir("official").resolve():
        raise ConfigError("第三方配置目录不能与官方目录相同。")
    settings = load_json(config / "settings.json", required=profile == "cc")
    env = settings.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ConfigError(f"{config}/settings.json 的 env 必须是字符串键值对象。")
    if profile == "official":
        if any(v and is_routing_key(k) for k, v in env.items()) or settings.get("apiKeyHelper"):
            raise ConfigError("官方 settings 包含认证或路由覆盖，请先检查 ~/.claude/settings.json；脚本不会覆盖它。")
    else:
        try:
            endpoint = urlsplit(env.get("ANTHROPIC_BASE_URL", ""))
            port = endpoint.port
        except ValueError:
            raise ConfigError("第三方 ANTHROPIC_BASE_URL 格式无效。") from None
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
            raise ConfigError("第三方配置必须包含有效 ANTHROPIC_BASE_URL，避免退回官方来源。")
        if endpoint.hostname.lower().rstrip(".") == "api.anthropic.com":
            raise ConfigError("第三方配置当前指向官方 API，请在 CC Switch 中启用第三方供应商。")
        if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ConfigError("请勿在 endpoint 的用户信息、query 或 fragment 中放置认证信息。")
        if not (env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or settings.get("apiKeyHelper")):
            raise ConfigError("第三方配置缺少 token、API key 或 apiKeyHelper。")
    return settings


def binary():
    value = os.environ.get("DUAL_CLAUDE_BINARY", "claude")
    found = shutil.which(value)
    if not found:
        raise ConfigError("未找到 Claude CLI；请先安装 claude，或设置 DUAL_CLAUDE_BINARY。")
    return found


def native_command(profile, args):
    settings = validate_profile(profile)
    env = clean_env()
    options = ["--setting-sources", "user"]
    if profile == "cc":
        env["CLAUDE_CONFIG_DIR"] = str(config_dir(profile))
        if not settings.get("model") and settings.get("env", {}).get("ANTHROPIC_DEFAULT_SONNET_MODEL"):
            options += ["--model", "sonnet"]
    # Official: leave CLAUDE_CONFIG_DIR unset to retain the default Keychain login.
    return [binary(), *options, *args], env


def claude_args(args):
    return args[1:] if args[:1] == ["--"] else args


def workdir(value):
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"工作目录不存在：{path}")
    return path


def write_private_json(path, value):
    private_dir(path.parent)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def owned_links(bin_dir):
    return {
        bin_dir / "dual-claude": ROOT / "dual-claude",
        bin_dir / "claude-cc": ROOT / "bin/claude-cc",
    }


def remove_legacy_official_link(bin_dir):
    """Remove only the old alias installed by this project, including broken links."""
    link = bin_dir / "claude-official"
    if not link.is_symlink():
        return
    target = link.readlink()
    if not target.is_absolute():
        target = link.parent / target
    if target.name == "claude-official" and target.parent.is_dir() and target.parent.samefile(ROOT / "bin"):
        link.unlink()
        print("已移除旧官方别名；官方账户请直接使用原生 claude 命令。")


def install(args):
    binary()
    if config_dir("cc") == config_dir("official").resolve():
        raise ConfigError("第三方配置目录不能与官方目录相同。")
    destination = Path(args.bin_dir).expanduser().resolve()
    links = owned_links(destination)
    # Preflight all paths before creating anything; never replace unrelated files.
    for link, target in links.items():
        if os.path.lexists(link) and (not link.is_symlink() or link.resolve() != target.resolve()):
            raise ConfigError(f"安装冲突，保留原文件：{link}")
    destination.mkdir(parents=True, exist_ok=True)
    private_dir(config_dir("cc"))
    private_dir(state_dir())
    created = []
    try:
        for link, target in links.items():
            if not os.path.lexists(link):
                link.symlink_to(target)
                created.append(link)
        write_private_json(state_dir() / "install.json", {"root": str(ROOT), "bin_dir": str(destination)})
    except OSError:
        for link in created:
            link.unlink()
        raise
    remove_legacy_official_link(destination)
    print(f"已安装：{destination}/dual-claude、claude-cc（重复执行安全）。官方账户使用原生 claude。")
    if str(destination) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f'请将 {destination} 加入 PATH；当前仍可直接执行 {ROOT}/dual-claude。')
    print(f"CC Switch → 设置 → 高级 → Claude Code 配置目录：{config_dir('cc')}")
    print("安装器不更改 CC Switch、账户登录或 shell 配置。运行 ./dual-claude doctor 检查。")
    return 0


def uninstall(args):
    destination = Path(args.bin_dir).expanduser().resolve()
    remove_legacy_official_link(destination)
    for link, target in owned_links(destination).items():
        if link.is_symlink() and link.resolve() == target.resolve():
            link.unlink()
            print(f"已移除：{link}")
    print("保留 Claude/CC Switch 配置、会话、备份、Docker 镜像和卷。")
    return 0


def checked_output(command, env=None, cwd=None, timeout=15):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return result


def doctor(args):
    report = {"ok": True, "profiles": {}}
    try:
        report["claude_version"] = checked_output([binary(), "--version"]).stdout.strip()
    except (ConfigError, subprocess.TimeoutExpired) as exc:
        report.update(ok=False, cli_error=str(exc) if isinstance(exc, ConfigError) else "Claude 版本检查超时")
    for profile in PROFILES:
        item = {"configDirectory": str(config_dir(profile))}
        try:
            validate_profile(profile)
            cmd, env = native_command(profile, ["auth", "status"])
            # Empty temporary cwd avoids loading repository-level customizations.
            with tempfile.TemporaryDirectory(prefix="dual-claude-doctor-") as directory:
                result = checked_output(cmd, env, directory)
            auth = json.loads(result.stdout)
            if not isinstance(auth, dict):
                raise ValueError("Invalid auth result")
            item.update({key: auth[key] for key in AUTH_FIELDS if key in auth})
            item["ok"] = result.returncode == 0 and auth.get("loggedIn") is True
        except (ConfigError, ValueError, subprocess.TimeoutExpired) as exc:
            item.update(ok=False, error=str(exc) if isinstance(exc, ConfigError) else "认证状态检查超时或返回了无效 JSON")
        report["profiles"][profile] = item
        report["ok"] &= item["ok"]
    try:
        cc = load_json(Path.home() / ".cc-switch/settings.json")
        target = Path(cc.get("claudeConfigDir") or str(config_dir("official"))).expanduser().resolve()
        report["cc_switch"] = {"target": str(target), "ok": target == config_dir("cc")}
    except (ConfigError, TypeError):
        report["cc_switch"] = {"ok": False, "error": "无法读取 CC Switch 配置目录"}
    report["ok"] &= report["cc_switch"]["ok"]
    if args.docker:
        try:
            docker_base()
            daemon = checked_output(["docker", "info", "--format", "{{.ServerVersion}}"])
            image = checked_output(["docker", "image", "inspect", image_name(), "--format", "{{.Id}}"])
            report["docker"] = {"ok": daemon.returncode == 0 and image.returncode == 0,
                                "version": daemon.stdout.strip(), "image": image_name(), "image_present": image.returncode == 0}
        except (ConfigError, subprocess.TimeoutExpired):
            report["docker"] = {"ok": False, "error": "Docker/Compose 不可用或检查超时"}
        report["ok"] &= report["docker"]["ok"]
    report["note"] = "诊断不发起模型请求；loggedIn 不保证 API 请求成功。默认排除项目/local settings，不构成操作系统沙箱。"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def image_name():
    return "dual-claude:" + os.environ.get("DUAL_CLAUDE_VERSION", "2.1.311")


def docker_base():
    if not shutil.which("docker"):
        raise ConfigError("未找到 Docker，请先启动 Docker Desktop。")
    result = checked_output(["docker", "compose", "version", "--short"])
    if result.returncode:
        raise ConfigError("Docker Compose v2 不可用。")
    return ["docker", "compose", "-f", str(ROOT / "docker/compose.yaml")]


def docker_env(profile=None, directory=None):
    env = clean_env()
    env["DUAL_CLAUDE_CC_CONFIG_DIR"] = str(config_dir("cc"))
    for name in PROFILES:
        default = ROOT / "docker" / ("project-" + name)
        configured = env.get("DUAL_CLAUDE_" + name.upper() + "_WORKDIR")
        target = workdir(configured) if configured else default
        if directory is not None and profile == name:
            target = directory
        if target == default:
            target.mkdir(parents=True, exist_ok=True)
        env["DUAL_CLAUDE_" + name.upper() + "_WORKDIR"] = str(target)
    return env


def docker_run_command(profile, args, directory=None, interactive=True, name=None):
    validate_profile(profile)
    command = [*docker_base(), "run", "--rm", "--no-deps", "--pull", "never"]
    if not interactive:
        command.append("-T")
    if name:
        command += ["--name", name]
    return [*command, profile, *args], docker_env(profile, directory)


def smoke_one(profile, args):
    marker = ("DOCKER_" if args.docker else "") + profile.upper() + "_OK"
    settings = validate_profile(profile)
    secrets = [v for k, v in settings.get("env", {}).items() if any(word in k.upper() for word in ("TOKEN", "KEY", "SECRET")) and v]
    options = ["--safe-mode", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--tools", "", "--no-session-persistence", "--output-format", "json",
               "--max-budget-usd", str(args.budget), "--effort", "low",
               "--system-prompt", "You are a connectivity check. Reply only with the requested marker."]
    if profile == "official":
        options += ["--model", "haiku"]
    options += ["-p", "Reply exactly " + marker]
    started = time.monotonic()
    container = "dual-claude-smoke-" + uuid.uuid4().hex[:12] if args.docker else None
    result = {"profile": profile, "backend": "docker" if args.docker else "native", "ok": False}
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=private_dir(state_dir() / "workspaces")) as directory:
        cmd, env = docker_run_command(profile, options, Path(directory), False, container) if args.docker else native_command(profile, options)
        process = subprocess.Popen(cmd, env=env, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + args.timeout
            while True:
                if args.cancel.is_set():
                    result.update(error="验证已中断", exit_code=130)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, args.timeout)
                try:
                    stdout, _ = process.communicate(timeout=min(0.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if args.cancel.is_set():
                return result
            try:
                data = json.loads(stdout)
            except ValueError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            message = str(data.get("result", "CLI 未返回有效结果 JSON；请检查配置、镜像和登录状态。"))[:2000]
            for secret in secrets:
                message = message.replace(secret, "<redacted>")
            result.update(exit_code=process.returncode, result=message,
                          models=list(data.get("modelUsage", {})), estimated_cost_usd=data.get("total_cost_usd"),
                          ok=process.returncode == 0 and not data.get("is_error", True) and message.strip() == marker)
        except subprocess.TimeoutExpired:
            result.update(error="模型请求超时", exit_code=124)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
            if container:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return result


def smoke(args):
    args.cancel = threading.Event()
    profiles = PROFILES if args.profile == "all" else (args.profile,)
    def run(profile):
        try:
            return smoke_one(profile, args)
        except (ConfigError, OSError, subprocess.TimeoutExpired) as exc:
            return {"profile": profile, "ok": False, "error": str(exc) if isinstance(exc, ConfigError) else "无法启动或清理验证进程"}
    executor = ThreadPoolExecutor(max_workers=len(profiles))
    try:
        results = list(executor.map(run, profiles))
    except KeyboardInterrupt:
        args.cancel.set()
        print("正在终止本次验证进程及临时容器……", file=sys.stderr)
        return 130
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    report = {"ok": all(row["ok"] for row in results), "results": results,
              "note": "固定标记请求；禁用工具/hooks/MCP。成本是 CLI 估算，不代表第三方账单。"}
    filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6] + ".json"
    path = state_dir() / "reports" / filename
    write_private_json(path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"报告：{path}")
    return 0 if report["ok"] else 1


def positive(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("数值必须是有限正数")
    return number


def parser():
    result = argparse.ArgumentParser(description="官方 Claude Code 与 CC Switch 双实例管理（无第三方 Python 依赖）。")
    commands = result.add_subparsers(dest="command", required=True)
    for name, help_text in [("install", "安装命令链接，不改账户或 CC Switch 配置"), ("uninstall", "仅移除本工程的命令链接")]:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--bin-dir", default=str(Path.home() / ".local/bin"))
    diag = commands.add_parser("doctor", help="检查配置和认证，不发模型请求")
    diag.add_argument("--docker", action="store_true", help="额外检查 Docker 与已构建镜像")
    run = commands.add_parser("run", help="本机启动；Claude 参数放在 -- 后")
    run.add_argument("--workdir", default=os.getcwd())
    run.add_argument("profile", choices=PROFILES)
    run.add_argument("claude_args", nargs=argparse.REMAINDER)
    check = commands.add_parser("smoke", help="发送最小模型请求（会产生少量用量）")
    check.add_argument("--profile", choices=("all", *PROFILES), default="all")
    check.add_argument("--docker", action="store_true")
    check.add_argument("--timeout", type=positive, default=60)
    check.add_argument("--budget", type=positive, default=0.10, help="每路 CLI 估算预算 USD，默认 0.10")
    docker = commands.add_parser("docker", help="容器构建、启动和登录")
    docker_commands = docker.add_subparsers(dest="action", required=True)
    docker_commands.add_parser("build")
    docker_commands.add_parser("status")
    for action in ("run", "login"):
        sub = docker_commands.add_parser(action)
        sub.add_argument("--workdir")
        sub.add_argument("profile", choices=PROFILES)
        sub.add_argument("claude_args", nargs=argparse.REMAINDER)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "install":
            return install(args)
        if args.command == "uninstall":
            return uninstall(args)
        if args.command == "doctor":
            return doctor(args)
        if args.command == "smoke":
            return smoke(args)
        if args.command == "run":
            cmd, env = native_command(args.profile, claude_args(args.claude_args))
            os.chdir(workdir(args.workdir))
            os.execvpe(cmd[0], cmd, env)
        if args.command == "docker":
            if args.action in {"build", "status"}:
                cmd = [*docker_base(), *( ["build", "official"] if args.action == "build" else ["ps", "-a"])]
                return subprocess.call(cmd, env=docker_env())
            options = claude_args(args.claude_args)
            if args.action == "login":
                options = ["auth", "login", *options]
            cmd, env = docker_run_command(args.profile, options, workdir(args.workdir) if args.workdir else None)
            os.execvpe(cmd[0], cmd, env)
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print("错误：外部命令超时。", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"错误：{exc.strerror or '文件或进程操作失败'}。", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
