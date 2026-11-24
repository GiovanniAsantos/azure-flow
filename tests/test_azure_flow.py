"""Offline tests: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", "azure-flow")
ADO = os.path.join(ROOT, "scripts", "ado.py")
HOOK = os.path.join(ROOT, "hooks", "check_commit.py")
SESSION = os.path.join(ROOT, "hooks", "session_start.py")

spec = importlib.util.spec_from_file_location("ado", ADO)
ado = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ado)


def sh(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class TempRepo:
    def __enter__(self):
        self.dir = tempfile.mkdtemp()
        sh("git", "init", "-q", "-b", "main", cwd=self.dir)
        sh("git", "config", "user.email", "t@t", cwd=self.dir)
        sh("git", "config", "user.name", "t", cwd=self.dir)
        sh("git", "remote", "add", "origin", "https://acme@dev.azure.com/acme/My%20Proj/_git/api", cwd=self.dir)
        sh("git", "commit", "-q", "--allow-empty", "-m", "chore: init", cwd=self.dir)
        return self.dir

    def __exit__(self, *exc):
        subprocess.run(["rm", "-rf", self.dir])


class RemoteParsing(unittest.TestCase):
    def test_variants(self):
        cases = {
            "https://dev.azure.com/acme/Proj/_git/api": ("acme", "Proj", "api"),
            "https://acme@dev.azure.com/acme/My%20Proj/_git/api.git": ("acme", "My Proj", "api"),
            "git@ssh.dev.azure.com:v3/acme/Proj/api": ("acme", "Proj", "api"),
            "ssh://git@ssh.dev.azure.com:22/v3/acme/Proj/api": ("acme", "Proj", "api"),
            "https://acme.visualstudio.com/DefaultCollection/Proj/_git/api": ("acme", "Proj", "api"),
            "https://acme.visualstudio.com/Proj/_git/api": ("acme", "Proj", "api"),
            "acme@vs-ssh.visualstudio.com:v3/acme/Proj/api": ("acme", "Proj", "api"),
        }
        for url, (org, proj, repo) in cases.items():
            r = ado.parse_remote(url)
            self.assertEqual((r.get("org"), r.get("project"), r.get("repo")), (org, proj, repo), url)
        self.assertEqual(ado.parse_remote("https://github.com/a/b.git"), {})


class Helpers(unittest.TestCase):
    def test_branch_id(self):
        self.assertEqual(ado.work_item_from_branch("feature/1234-login-sso"), 1234)
        self.assertEqual(ado.work_item_from_branch("fix/77"), 77)
        self.assertEqual(ado.work_item_from_branch("users/gio/feature/55-x"), 55)
        self.assertIsNone(ado.work_item_from_branch("main"))
        self.assertIsNone(ado.work_item_from_branch("release/v2.1"))

    def test_slug(self):
        self.assertEqual(ado.slugify("Login com SSO (Entra ID) — Ação!"), "login-com-sso-entra-id-acao")

    def test_types(self):
        self.assertEqual(ado.normalize_type("story"), "User Story")
        self.assertEqual(ado.normalize_type("EPIC"), "Epic")

    def test_html(self):
        self.assertEqual(ado.as_html("a < b\nc"), "a &lt; b<br>c")
        self.assertEqual(ado.as_html("<ul><li>x</li></ul>"), "<ul><li>x</li></ul>")


class Cli(unittest.TestCase):
    def run_ado(self, *args, cwd):
        env = dict(os.environ, AZURE_DEVOPS_PAT="")
        res = subprocess.run([sys.executable, ADO, *args], cwd=cwd, capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_config_and_dry_run(self):
        with TempRepo() as d:
            cfg = self.run_ado("config", cwd=d)
            self.assertEqual((cfg["org"], cfg["project"], cfg["repo"]), ("acme", "My Proj", "api"))
            dry = self.run_ado("create", "--type", "story", "--title", "Login", "--parent", "10",
                               "--acceptance", "Dado X", "--tags", "a, b", "--dry-run", cwd=d)
            self.assertEqual(dry["type"], "User Story")
            paths = [o["path"] for o in dry["operations"]]
            self.assertIn("/fields/Microsoft.VSTS.Common.AcceptanceCriteria", paths)
            self.assertIn("/relations/-", paths)
            rel = dry["operations"][-1]["value"]
            self.assertEqual(rel["url"], "https://dev.azure.com/acme/_apis/wit/workItems/10")

    def test_commits(self):
        with TempRepo() as d:
            sh("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=d)
            sh("git", "switch", "-q", "-c", "feature/42-login", cwd=d)
            sh("git", "commit", "-q", "--allow-empty", "-m", "feat(auth): add sso", "-m", "Refs: #42", cwd=d)
            sh("git", "commit", "-q", "--allow-empty", "-m", "oops", cwd=d)
            res = self.run_ado("commits", "--base", "origin/main", cwd=d)
            self.assertEqual(res["workItem"], 42)
            self.assertEqual(res["count"], 2)
            oops, feat = res["commits"]
            self.assertEqual((feat["type"], feat["scope"], feat["workItems"]), ("feat", "auth", [42]))
            self.assertEqual((oops["type"], oops["workItems"]), (None, []))


class CommitHook(unittest.TestCase):
    def hook(self, command, cwd):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
        return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)

    def test_hook(self):
        with TempRepo() as d:
            # main branch: no enforcement
            self.assertEqual(self.hook('git commit -m "whatever"', d).returncode, 0)
            sh("git", "switch", "-q", "-c", "feature/42-login", cwd=d)
            ok = [
                'git commit -m "feat(auth): add sso" -m "Refs: #42"',
                "git add -A && git commit -m 'fix: bug' -m 'Refs: #42'",
                'git commit -m "$(cat <<\'EOF\'\nfeat(api)!: new route\n\nRefs: #42\nEOF\n)"',
                "git commit --amend --no-edit",
                "git commit -F msg.txt",
                "git status",
                "echo git commit",
            ]
            for c in ok:
                r = self.hook(c, d)
                self.assertEqual(r.returncode, 0, f"{c!r}: {r.stderr}")
            bad = [
                'git commit -m "feat(auth): add sso"',          # no ref
                'git commit -m "added stuff" -m "Refs: #42"',   # not CC
                'git commit -m "feat: x" -m "Refs: #421"',      # wrong id
                'git commit -m "feat: x AB#42"',                # AB# is GitHub syntax
            ]
            for c in bad:
                r = self.hook(c, d)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn("azure-flow", r.stderr)


class SessionHook(unittest.TestCase):
    def test_context(self):
        with TempRepo() as d:
            sh("git", "switch", "-q", "-c", "feature/9-x", cwd=d)
            env_file = os.path.join(d, "env.sh")
            env = dict(os.environ, CLAUDE_ENV_FILE=env_file, CLAUDE_PLUGIN_ROOT=ROOT)
            r = subprocess.run([sys.executable, SESSION], input=json.dumps({"cwd": d}),
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("#9", ctx)
            with open(env_file) as f:
                self.assertIn("AZURE_FLOW_ADO", f.read())


if __name__ == "__main__":
    unittest.main()
