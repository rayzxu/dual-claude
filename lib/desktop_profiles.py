"""Optional macOS Desktop launchers. No credentials or profiles are copied."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import urlsplit

from dual_claude import ConfigError, ROOT, load_json, private_dir, state_dir, write_private_json

NAMES = {"official": "Claude Official", "cc": "Claude CC"}
PREFIX = "io.github.dual-claude.desktop"


def require_macos():
    if sys.platform != "darwin":
        raise ConfigError("Desktop 启动器仅支持 macOS。")


def app_path():
    return Path(os.environ.get("DUAL_CLAUDE_DESKTOP_APP", "/Applications/Claude.app")).expanduser().resolve()


def support():
    return Path.home() / "Library/Application Support"


def official_configs():
    return [support() / name / "claude_desktop_config.json" for name in ("Claude-Official", "Claude-Official-3p")]


def validate_official():
    for path in official_configs():
        # Never modify an existing profile that has become third-party/managed.
        if path.parent.is_symlink():
            raise ConfigError("官方 Desktop Profile 目录不能是符号链接。")
        settings = load_json(path)
        if settings.get("deploymentMode") not in (None, "1p") or settings.get("managedConfig"):
            raise ConfigError("独立官方 Desktop Profile 含第三方或 managed 配置，请先人工检查。")


def read_info(path):
    try:
        info = plistlib.loads((path / "Contents/Info.plist").read_bytes())
        if not isinstance(info, dict):
            raise ValueError()
        return info
    except (OSError, ValueError, plistlib.InvalidFileException):
        raise ConfigError(f"无法读取应用 Info.plist：{path.name}") from None


def install():
    require_macos()
    tools = {name: shutil.which(name) for name in ("clang", "codesign")}
    if not all(tools.values()):
        raise ConfigError("缺少 clang 或 codesign；请先安装 Xcode Command Line Tools。")
    original = app_path()
    info = read_info(original)
    executable = original / "Contents/MacOS" / info.get("CFBundleExecutable", "Claude")
    if not executable.is_file():
        raise ConfigError("Claude Desktop 主程序不存在。")
    icon_name = info.get("CFBundleIconFile", "")
    icon = original / "Contents/Resources" / (icon_name if icon_name.endswith(".icns") else icon_name + ".icns")
    if not icon.is_file():
        raise ConfigError("Claude Desktop 图标不存在。")
    validate_official()
    destination = Path.home() / "Applications"
    # Validate every destination before compiling, seeding configs or replacing apps.
    for role, name in NAMES.items():
        app = destination / (name + ".app")
        if app.is_symlink():
            raise ConfigError(f"不覆盖应用符号链接：{name}")
        if app.exists():
            bundle = read_info(app).get("CFBundleIdentifier")
            allowed = {PREFIX + "." + role}
            if role == "official":
                allowed.add("io.github.jeroenwollaars.claude-dual-launcher.official")
            if bundle not in allowed:
                raise ConfigError(f"不覆盖其他应用：{name}")
    base = private_dir(state_dir() / "desktop")
    backup = base / ("install-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6])
    with tempfile.TemporaryDirectory(prefix="build-", dir=base) as temporary:
        staging = Path(temporary)
        for role, name in NAMES.items():
            app = staging / (name + ".app")
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/Resources").mkdir()
            profile = "Claude-Official" if role == "official" else "Claude"
            subprocess.run([tools["clang"], "-Wall", "-Wextra", "-Werror", "-O2",
                            *(["-DTHIRD_PARTY_PROFILE=1"] if role == "cc" else []),
                            '-DPROFILE_DIR=' + json.dumps(profile), '-DAPP_BINARY=' + json.dumps(str(executable)),
                            "-o", str(app / "Contents/MacOS/launcher"), str(ROOT / "desktop/profile.c")], check=True)
            shutil.copy2(icon, app / "Contents/Resources/AppIcon.icns")
            shutil.copy2(ROOT / "desktop/LICENSE", app / "Contents/Resources/launcher-LICENSE.txt")
            value = {"CFBundleName": name, "CFBundleDisplayName": name, "CFBundleIdentifier": PREFIX + "." + role,
                     "CFBundleIconFile": "AppIcon", "CFBundleExecutable": "launcher", "CFBundlePackageType": "APPL",
                     "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1", "LSMinimumSystemVersion": "12.0",
                     "LSUIElement": False, "NSHighResolutionCapable": True}
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(value))
            subprocess.run([tools["codesign"], "--force", "-s", "-", str(app)], capture_output=True, check=True)
        private_dir(backup)
        for path in official_configs():
            if path.exists():
                shutil.copy2(path, backup / (path.parent.name + ".json"))
                (backup / (path.parent.name + ".json")).chmod(0o600)
            else:
                write_private_json(path, {"deploymentMode": "1p"})
        destination.mkdir(parents=True, exist_ok=True)
        moved, installed = [], []
        try:
            for name in NAMES.values():
                target = destination / (name + ".app")
                if target.exists():
                    old = backup / target.name
                    shutil.move(str(target), old)
                    moved.append((old, target))
                shutil.move(str(staging / target.name), target)
                installed.append(target)
        except OSError:
            for target in installed:
                shutil.rmtree(target)
            for old, target in reversed(moved):
                shutil.move(str(old), target)
            raise
    registration = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    for name in NAMES.values():
        subprocess.run([registration, "-f", str(destination / (name + ".app"))], capture_output=True, check=True)
    print("已安装 ~/Applications/Claude Official.app 和 Claude CC.app。")
    print("原版 Claude.app、CLI 与登录启动项未修改。官方新 Profile 需自行登录。")
    print("Claude CC 使用默认 Desktop 的配置；请在 CC Switch 的 Claude Desktop 页面配置供应商。")
    print("备份目录：" + str(backup))
    return 0


def doctor():
    require_macos()
    report = {"ok": True, "apps": {}, "profiles": {}}
    report["desktop_version"] = read_info(app_path()).get("CFBundleShortVersionString")
    for role, name in NAMES.items():
        app = Path.home() / "Applications" / (name + ".app")
        installed = app.is_dir() and (app / "Contents/MacOS/launcher").is_file()
        report["apps"][role] = {"installed": installed, "path": str(app)}
        report["ok"] &= installed
    for name in ("Claude", "Claude-3p", "Claude-Official", "Claude-Official-3p"):
        settings = load_json(support() / name / "claude_desktop_config.json")
        mode = settings.get("deploymentMode")
        report["profiles"][name] = {"deploymentMode": mode}
        report["ok"] &= mode == ("1p" if name.startswith("Claude-Official") else "3p")
    validate_official()
    meta = load_json(support() / "Claude-3p/configLibrary/_meta.json")
    identifier = meta.get("appliedId", "")
    if not isinstance(identifier, str) or not identifier or Path(identifier).name != identifier:
        raise ConfigError("默认第三方 Profile 尚未应用网关配置。")
    gateway = load_json(support() / "Claude-3p/configLibrary" / (identifier + ".json"), required=True)
    endpoint = gateway.get("inferenceGatewayBaseUrl", "")
    try:
        url = urlsplit(endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError()
        host = "[" + url.hostname + "]" if ":" in url.hostname else url.hostname
        safe_url = url.scheme + "://" + host + (":" + str(url.port) if url.port else "") + url.path
    except (ValueError, TypeError):
        raise ConfigError("Desktop Gateway 地址无效。") from None
    report["gateway"] = {"endpoint": safe_url, "credentials_present": bool(gateway.get("inferenceGatewayApiKey"))}
    report["ok"] &= report["gateway"]["credentials_present"]
    report["note"] = "只检查配置，不代表已登录或模型请求成功。两个 GUI 实例需分别验证；不自动修改 CC Switch。"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def main(action):
    try:
        return install() if action == "install" else doctor()
    except subprocess.CalledProcessError:
        raise ConfigError("Desktop 启动器编译、签名或注册失败；检查 Xcode 工具和应用目录权限。") from None
