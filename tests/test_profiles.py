"""Behavior checks with disposable homes and a fake CLI; no API calls."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import dual_claude as dc


class Profiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "HOME": str(self.home),
            "DUAL_CLAUDE_CC_CONFIG_DIR": str(self.home / ".claude-cc"),
            "DUAL_CLAUDE_STATE_DIR": str(self.home / "state"),
            "DUAL_CLAUDE_BINARY": str(self.home / "fake-claude"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fake = self.home / "fake-claude"
        self.fake.write_text('#!' + sys.executable + '\nprint("fake")\n')
        self.fake.chmod(0o755)
        self.cc_settings = {"env": {"ANTHROPIC_BASE_URL": "https://provider.example",
                                     "ANTHROPIC_AUTH_TOKEN": "test-secret", "ANTHROPIC_DEFAULT_SONNET_MODEL": "third-party-model"}}
        self.write("cc", self.cc_settings)

    def write(self, profile, value):
        directory = dc.config_dir(profile)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text(json.dumps(value))

    def call(self, args):
        with redirect_stdout(io.StringIO()) as output:
            result = dc.main(args)
        return result, output.getvalue()

    def test_inherited_routes_removed_and_default_keychain_preserved(self):
        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "global-secret", "ANTHROPIC_BASE_URL": "http://wrong",
                                    "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_OAUTH_TOKEN": "wrong",
                                    "CLAUDE_CONFIG_DIR": "/wrong", "KEEP_ME": "yes"}):
            command, env = dc.native_command("official", ["--version"])
            self.assertNotIn("CLAUDE_CONFIG_DIR", env)
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertNotIn("CLAUDE_CODE_USE_VERTEX", env)
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
            self.assertEqual(env["KEEP_ME"], "yes")
            command, env = dc.native_command("cc", ["--version"])
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(dc.config_dir("cc")))
            self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def test_official_route_override_refused_without_modification(self):
        self.write("official", self.cc_settings)
        before = (dc.config_dir("official") / "settings.json").read_bytes()
        with self.assertRaises(dc.ConfigError):
            dc.native_command("official", [])
        self.assertEqual(before, (dc.config_dir("official") / "settings.json").read_bytes())

    def test_cc_does_not_fall_back_to_official(self):
        for settings in ({}, {"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", "ANTHROPIC_AUTH_TOKEN": "x"}},
                         {"env": {"ANTHROPIC_BASE_URL": "https://provider.example"}}):
            self.write("cc", settings)
            with self.assertRaises(dc.ConfigError):
                dc.native_command("cc", [])

    def test_same_directory_and_symlink_alias_refused(self):
        official = dc.config_dir("official")
        official.mkdir()
        alias = self.home / "alias"
        alias.symlink_to(official)
        with patch.dict(os.environ, {"DUAL_CLAUDE_CC_CONFIG_DIR": str(alias)}):
            with self.assertRaises(dc.ConfigError):
                dc.validate_profile("cc")

    def test_invalid_json_error_does_not_echo_credentials(self):
        (dc.config_dir("cc") / "settings.json").write_text('{"token":"TOP-SECRET", broken')
        with self.assertRaises(dc.ConfigError) as raised:
            dc.validate_profile("cc")
        self.assertNotIn("TOP-SECRET", str(raised.exception))

    def test_install_is_idempotent_and_uninstall_keeps_user_files(self):
        destination = self.home / "bin"
        args = ["install", "--bin-dir", str(destination)]
        self.assertEqual(self.call(args)[0], 0)
        self.assertEqual(self.call(args)[0], 0)
        self.assertTrue((destination / "claude-cc").is_symlink())
        self.assertFalse(os.path.lexists(destination / "claude-official"))
        # Replace one owned link with a user file: uninstall must preserve it.
        (destination / "claude-cc").unlink()
        (destination / "claude-cc").write_text("keep this")
        self.assertEqual(self.call(["uninstall", "--bin-dir", str(destination)])[0], 0)
        self.assertEqual((destination / "claude-cc").read_text(), "keep this")
        self.assertTrue((dc.config_dir("cc") / "settings.json").exists())

    def test_install_migrates_owned_official_alias_and_keeps_native_claude(self):
        destination = self.home / "bin"
        destination.mkdir()
        old_alias = destination / "claude-official"
        old_alias.symlink_to(ROOT / "bin/claude-official")
        native = destination / "claude"
        native.write_text("existing native command")
        self.assertEqual(self.call(["install", "--bin-dir", str(destination)])[0], 0)
        self.assertFalse(os.path.lexists(old_alias))
        self.assertEqual(native.read_text(), "existing native command")

    def test_migration_preserves_unrelated_official_alias(self):
        destination = self.home / "bin"
        destination.mkdir()
        alias = destination / "claude-official"
        alias.write_text("user command")
        self.assertEqual(self.call(["install", "--bin-dir", str(destination)])[0], 0)
        self.assertEqual(alias.read_text(), "user command")
        alias.unlink()
        target = self.home / "custom-command"
        target.write_text("user command")
        alias.symlink_to(target)
        self.assertEqual(self.call(["uninstall", "--bin-dir", str(destination)])[0], 0)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), target.resolve())

    def test_install_conflict_causes_no_partial_install(self):
        destination = self.home / "bin"
        destination.mkdir()
        (destination / "claude-cc").write_text("user command")
        with self.assertRaises(dc.ConfigError):
            dc.install(type("Args", (), {"bin_dir": str(destination)})())
        self.assertFalse((destination / "dual-claude").exists())

    def test_claude_arguments_forwarded_verbatim_with_spaces(self):
        self.fake.write_text('#!' + sys.executable + '\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        result = subprocess.run([str(ROOT / "dual-claude"), "run", "--workdir", str(self.home), "cc", "--", "-p", "a prompt with spaces"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)[-2:], ["-p", "a prompt with spaces"])

    def test_provider_model_is_respected(self):
        self.cc_settings["model"] = "custom-model"
        self.write("cc", self.cc_settings)
        command, _ = dc.native_command("cc", [])
        self.assertNotIn("--model", command)

    def test_smoke_failure_is_redacted_and_returns_nonzero(self):
        self.fake.write_text('#!' + sys.executable + '\nimport json\nprint(json.dumps({"result":"403 test-secret", "is_error": True}))\n')
        code, output = self.call(["smoke", "--profile", "cc"])
        self.assertEqual(code, 1)
        self.assertIn("403 <redacted>", output)
        self.assertNotIn("test-secret", output)
        report = next((self.home / "state/reports").glob("*.json"))
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)

    def test_smoke_timeout_terminates_owned_process(self):
        self.fake.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(30)\n')
        code, output = self.call(["smoke", "--profile", "cc", "--timeout", "0.1"])
        self.assertEqual(code, 1)
        self.assertIn('"exit_code": 124', output)

    def test_ctrl_c_cleans_up_smoke_child(self):
        pidfile = self.home / "child.pid"
        self.fake.write_text('#!' + sys.executable + '\nimport os,time,pathlib\npathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
        process = subprocess.Popen([str(ROOT / "dual-claude"), "smoke", "--profile", "cc"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.025)
            self.assertTrue(pidfile.exists())
            child = int(pidfile.read_text())
            process.send_signal(signal.SIGINT)
            process.communicate(timeout=8)
            self.assertEqual(process.returncode, 130)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
