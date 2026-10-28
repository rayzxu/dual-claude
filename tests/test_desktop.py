"""Desktop profile checks with disposable homes and a fake app, no GUI/API calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import desktop_profiles as desktop
from dual_claude import ConfigError


class DesktopConfigs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.env = patch.dict(os.environ, {"HOME": self.temporary.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_new_or_official_profiles_are_accepted(self):
        desktop.validate_official()
        for file in desktop.official_configs():
            file.parent.mkdir(parents=True)
            file.write_text('{"deploymentMode":"1p"}')
        desktop.validate_official()

    def test_third_party_official_profile_is_refused_without_editing(self):
        file = desktop.official_configs()[0]
        file.parent.mkdir(parents=True)
        file.write_text('{"deploymentMode":"3p"}')
        before = file.read_bytes()
        with self.assertRaises(ConfigError):
            desktop.validate_official()
        self.assertEqual(before, file.read_bytes())

    def test_official_profile_cannot_alias_default(self):
        default = desktop.support() / "Claude"
        default.mkdir(parents=True)
        desktop.official_configs()[0].parent.symlink_to(default)
        with self.assertRaises(ConfigError):
            desktop.validate_official()


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"), "macOS clang required")
class NativeDesktopLauncher(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home [profile] with space"
        self.home.mkdir()
        self.fake = self.root / "fake-app"
        self.fake.write_text('#!' + sys.executable + '\nimport json,os,sys,time,pathlib\n'
                             'print(json.dumps({"args":sys.argv[1:],"routing_vars":[k for k in os.environ if k.startswith(("ANTHROPIC_","CLAUDE_CODE_")) or k=="CLAUDE_USER_DATA_DIR"]}),flush=True)\n'
                             'if os.environ.get("FAKE_SLEEP"): pathlib.Path(os.environ["READY_FILE"]).touch(); time.sleep(30)\n')
        self.fake.chmod(0o755)
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)

    def compile(self, profile, third_party=False):
        binary = self.root / (profile + "-launcher")
        subprocess.run(["clang", "-Wall", "-Wextra", "-Werror", "-O2",
                        '-DPROFILE_DIR=' + json.dumps(profile), '-DAPP_BINARY=' + json.dumps(str(self.fake)),
                        *(["-DTHIRD_PARTY_PROFILE=1"] if third_party else []),
                        "-o", str(binary), str(ROOT / "desktop/profile.c")], check=True, capture_output=True)
        return binary

    def start_fake_profile(self, name):
        ready = self.root / (name + ".ready")
        env = {**self.env, "FAKE_SLEEP": "1", "READY_FILE": str(ready)}
        argument = "--user-data-dir=" + str(self.home / "Library/Application Support" / name)
        process = subprocess.Popen([str(self.fake), argument], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.terminate(), process.wait(timeout=5)) if process.poll() is None else None)
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        self.assertTrue(ready.exists())
        return process

    def test_paths_and_arguments_preserved_and_environment_cleaned(self):
        launcher = self.compile("Claude-Official")
        env = {**self.env, "ANTHROPIC_AUTH_TOKEN": "test-only", "CLAUDE_USER_DATA_DIR": "/wrong", "CLAUDE_CODE_USE_VERTEX": "1"}
        result = subprocess.run([str(launcher), "argument with spaces"], env=env, capture_output=True, text=True, check=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["args"], ["--user-data-dir=" + str(self.home / "Library/Application Support/Claude-Official"), "argument with spaces"])
        self.assertEqual(value["routing_vars"], [])

    def test_duplicate_detection_distinguishes_profiles_and_catches_3p(self):
        official = self.start_fake_profile("Claude-Official")
        cc_launcher = self.compile("Claude", third_party=True)
        result = subprocess.run([str(cc_launcher)], env=self.env, capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(result.stdout)["args"][0].endswith("/Claude"))
        official_launcher = self.compile("Claude-Official")
        result = subprocess.run([str(official_launcher)], env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "")
        official.terminate()
        official.wait(timeout=5)
        self.start_fake_profile("Claude-3p")
        result = subprocess.run([str(cc_launcher)], env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
