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
        env = {k: v for k, v in os.environ.items() if not k.startswith("AZURE_DEVOPS_")}
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


class ListQuery(unittest.TestCase):
    def test_wiql_built(self):
        captured = {}

        class FakeCtx(ado.Ctx):
            def __init__(self):
                self.org, self.project, self.pat = "acme", "P", "x"

            def request(self, method, path, body=None, **kw):
                captured["q"] = body["query"]
                return {"workItems": []}

        args = ado.build_parser().parse_args(
            ["list", "--search", "agente|IA", "--words", "--in-description", "--no-parent"])
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            ado.cmd_list(FakeCtx(), args)
        q = captured["q"]
        self.assertIn("[System.Title] CONTAINS WORDS 'agente'", q)
        self.assertIn("[System.Description] CONTAINS WORDS 'IA'", q)
        self.assertIn("[System.Parent] = ''", q)


class BranchMapping(unittest.TestCase):
    def test_map_without_rename(self):
        with TempRepo() as d:
            sh("git", "switch", "-q", "-c", "feature/new-llm-aplication", cwd=d)
            env = dict(os.environ, AZURE_DEVOPS_PAT="")
            run = lambda *a: subprocess.run([sys.executable, ADO, *a], cwd=d, capture_output=True,
                                            text=True, env=env)
            self.assertIsNone(json.loads(run("current").stdout)["workItem"])
            r = run("map", "9939", "--no-link")
            self.assertEqual(r.returncode, 0, r.stderr)
            cur = json.loads(run("current").stdout)
            self.assertEqual((cur["workItem"], cur["source"]), (9939, "git-config"))
            payload = json.dumps({"tool_input": {"command": 'git commit -m "feat: x"'}, "cwd": d})
            hook = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True, text=True)
            self.assertEqual(hook.returncode, 2)
            self.assertIn("#9939", hook.stderr)
            run("unmap")
            self.assertIsNone(json.loads(run("current").stdout)["workItem"])


class Sprints(unittest.TestCase):
    def test_sprint_for_date(self):
        sprints = [{"path": "P\\Sprint 80", "start": "2026-11-02", "finish": "2026-11-06"},
                   {"path": "P\\Sprint 81", "start": "2026-11-09", "finish": "2026-11-13"}]
        self.assertEqual(ado.sprint_for_date(sprints, "2026-11-04"), "P\\Sprint 80")
        self.assertEqual(ado.sprint_for_date(sprints, "2026-11-08"), "P\\Sprint 80")  # weekend
        self.assertEqual(ado.sprint_for_date(sprints, "2026-11-09"), "P\\Sprint 81")
        self.assertIsNone(ado.sprint_for_date(sprints, "2026-12-01"))

    def test_iteration_path(self):
        class C: project = "ABA"
        self.assertEqual(ado.iteration_path(C, "80"), "ABA\\Sprint 80")
        self.assertEqual(ado.iteration_path(C, "Sprint 81"), "ABA\\Sprint 81")
        self.assertEqual(ado.iteration_path(C, "ABA\\Sprint 82"), "ABA\\Sprint 82")


class Tags(unittest.TestCase):
    def test_normalize(self):
        tags = ado.normalize_tags(["Retenção", "cloud", "Correção", "CLOUD", "Corda API"],
                                  existing=["Cloud", "Corda API"])
        self.assertEqual(tags, ["retencao", "Cloud", "correcao", "Corda API"])

    def test_module_tags(self):
        self.assertEqual(ado.module_tags("api-bpms"), ["BPMS"])
        self.assertEqual(ado.module_tags("api-corda-signature"), ["Signature", "Corda API"])
        self.assertEqual(ado.module_tags("api-novo-servico"), ["NovoServico"])

    def test_build_tags_merge(self):
        class FakeCtx(ado.Ctx):
            def __init__(self):
                self.org, self.project, self.pat, self.repo = "a", "P", "x", "api-cloud"
                self._tags = ["Cloud", "azure-flow"]
        ctx = FakeCtx()
        self.assertEqual(ctx.build_tags("lixeira, retenção", ["aba-frontend"], True),
                         ["lixeira", "retencao", "Frontend", "Cloud", "azure-flow"])
        self.assertEqual(ctx.build_tags("i18n", current="Cloud; old", remove="old"),
                         ["Cloud", "i18n", "azure-flow"])


class Relate(unittest.TestCase):
    def fake(self, relations):
        calls = []

        class FakeCtx(ado.Ctx):
            def __init__(self):
                self.org, self.project, self.pat = "acme", "P", "x"

            def request(self, method, path, body=None, **kw):
                calls.append((method, path, body))
                if method == "GET":
                    return {"id": 1, "rev": 7, "fields": {}, "relations": list(relations)}
                return {}
        return FakeCtx(), calls

    def run_cmd(self, ctx, argv):
        import contextlib, io
        buf = io.StringIO()
        args = ado.build_parser().parse_args(argv)
        with contextlib.redirect_stdout(buf):
            args.fn(ctx, args)
        return json.loads(buf.getvalue())

    def test_relate_skips_existing(self):
        existing = [{"rel": "System.LinkTypes.Related", "url": "https://dev.azure.com/acme/_apis/wit/workItems/5"}]
        ctx, calls = self.fake(existing)
        res = self.run_cmd(ctx, ["relate", "1", "5", "6", "--comment", "x"])
        self.assertEqual((res["linked"], res["alreadyLinked"]), ([6], [5]))
        ops = calls[-1][2]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["value"]["rel"], "System.LinkTypes.Related")
        self.assertTrue(ops[0]["value"]["url"].endswith("/workItems/6"))
        self.assertEqual(ops[0]["value"]["attributes"], {"comment": "x"})

    def test_relate_types(self):
        ctx, calls = self.fake([])
        self.run_cmd(ctx, ["relate", "1", "2", "--type", "predecessor"])
        self.assertEqual(calls[-1][2][0]["value"]["rel"], "System.LinkTypes.Dependency-Reverse")

    def test_unrelate(self):
        rels = [{"rel": "ArtifactLink", "url": "vstfs:///x"},
                {"rel": "System.LinkTypes.Related", "url": "https://dev.azure.com/acme/_apis/wit/workItems/5"}]
        ctx, calls = self.fake(rels)
        res = self.run_cmd(ctx, ["unrelate", "1", "5"])
        self.assertEqual(res["removed"], 1)
        ops = calls[-1][2]
        self.assertEqual(ops[0], {"op": "test", "path": "/rev", "value": 7})
        self.assertEqual(ops[1], {"op": "remove", "path": "/relations/1"})


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
