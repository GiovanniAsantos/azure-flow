#!/usr/bin/env python3
"""Azure DevOps CLI used by the azure-flow Claude Code plugin.

Standard library only (works on Linux, macOS and Windows with Python 3.8+).

Configuration (env vars; org/project/repo are auto-detected from the
`origin` remote of an Azure Repos checkout when not set):

  AZURE_DEVOPS_PAT        Personal Access Token (Work Items R/W, Code R/W)
                          If unset, falls back to AZURE_DEVOPS_TOKEN (Entra ID bearer)
                          and then to the Azure CLI (`az login`), which refreshes
                          tokens automatically - no manual expiry handling.
  AZURE_DEVOPS_ORG        organization name   (dev.azure.com/<org>)
  AZURE_DEVOPS_PROJECT    project name
  AZURE_DEVOPS_REPO       repository name
  AZURE_DEVOPS_AREA       default Area Path for new work items (optional)
  AZURE_DEVOPS_ITERATION  default Iteration Path for new work items (optional)

Every command prints JSON on stdout. Errors go to stderr with exit code 1.
"""
import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "7.1"
COMMENTS_API_VERSION = "7.1-preview.4"

# Agile process work item types (+ friendly aliases).
TYPE_ALIASES = {
    "epic": "Epic",
    "feature": "Feature",
    "story": "User Story",
    "user story": "User Story",
    "userstory": "User Story",
    "us": "User Story",
    "task": "Task",
    "bug": "Bug",
    "issue": "Issue",
}

# Agile process states.
AGILE_STATES = ["New", "Active", "Resolved", "Closed", "Removed"]

REMOTE_PATTERNS = [
    # https://dev.azure.com/org/project/_git/repo  (optionally user@)
    r"^https://(?:[^@/]+@)?dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/?#]+?)(?:\.git)?/?$",
    # git@ssh.dev.azure.com:v3/org/project/repo  |  ssh://git@ssh.dev.azure.com:22/v3/org/project/repo
    r"^(?:ssh://)?git@ssh\.dev\.azure\.com(?::22/|:|/)v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    # https://org.visualstudio.com/[DefaultCollection/]project/_git/repo
    r"^https://(?:[^@/]+@)?(?P<org>[^./]+)\.visualstudio\.com/(?:DefaultCollection/)?(?P<project>[^/]+)/_git/(?P<repo>[^/?#]+?)(?:\.git)?/?$",
    # org@vs-ssh.visualstudio.com:v3/org/project/repo
    r"^[^@]+@vs-ssh\.visualstudio\.com:v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
]

# First number after a "/" (or at the start) followed by "-" or end:
# feature/123-login-sso, fix/456, 789-hotfix
BRANCH_ID_RE = re.compile(r"(?:^|/)(\d+)(?=-|$)")


# --------------------------------------------------------------------------- helpers

def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def git(*args):
    try:
        res = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def q(value):
    return urllib.parse.quote(str(value), safe="")


def parse_remote(url):
    url = (url or "").strip()
    for pattern in REMOTE_PATTERNS:
        m = re.match(pattern, url)
        if m:
            return {k: urllib.parse.unquote(v) for k, v in m.groupdict().items()}
    return {}


def work_item_from_branch(branch):
    m = BRANCH_ID_RE.search(branch or "")
    return int(m.group(1)) if m else None


def slugify(text, max_len=40):
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "work"


def normalize_type(t):
    key = (t or "").strip().lower()
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    die(f"unknown work item type '{t}'. Use one of: Epic, Feature, User Story, Task, Bug")


def as_html(text):
    """Azure rich-text fields take HTML. Plain text gets escaped + <br>."""
    if text is None:
        return None
    if re.search(r"<[a-zA-Z/][^>]*>", text):
        return text
    return html.escape(text).replace("\n", "<br>")


def wiql_str(s):
    return "'" + str(s).replace("'", "''") + "'"


# --------------------------------------------------------------------------- context / http

class Ctx:
    def __init__(self):
        remote = parse_remote(git("remote", "get-url", "origin"))
        self.org = os.environ.get("AZURE_DEVOPS_ORG") or remote.get("org")
        self.project = os.environ.get("AZURE_DEVOPS_PROJECT") or remote.get("project")
        self.repo = os.environ.get("AZURE_DEVOPS_REPO") or remote.get("repo")
        self.pat = os.environ.get("AZURE_DEVOPS_PAT", "")
        self.bearer = os.environ.get("AZURE_DEVOPS_TOKEN", "")
        self.auth_source = "pat" if self.pat else ("token" if self.bearer else None)
        self.area = os.environ.get("AZURE_DEVOPS_AREA")
        self.iteration = os.environ.get("AZURE_DEVOPS_ITERATION")
        self._repo_info = None

    def require(self, repo=False):
        missing = []
        if not self.org:
            missing.append("AZURE_DEVOPS_ORG")
        if not self.project:
            missing.append("AZURE_DEVOPS_PROJECT")
        if repo and not self.repo:
            missing.append("AZURE_DEVOPS_REPO")
        if missing:
            die("missing config: " + ", ".join(missing)
                + " (set env vars or run inside an Azure Repos checkout)")
        if not self.pat and not self.bearer:
            self.bearer = az_cli_token()
            self.auth_source = "az-cli" if self.bearer else None
        if not self.pat and not self.bearer:
            die("no credentials: set AZURE_DEVOPS_PAT (Work Items R/W + Code R/W scopes) "
                "or sign in with the Azure CLI (`az login`).")

    @property
    def base(self):
        return f"https://dev.azure.com/{q(self.org)}"

    def web_item(self, wid):
        return f"{self.base}/{q(self.project)}/_workitems/edit/{wid}"

    def api_item(self, wid):
        return f"{self.base}/_apis/wit/workItems/{wid}"

    def request(self, method, path, body=None, *, project=True, params=None,
                content_type="application/json", api_version=API_VERSION):
        url = self.base + (f"/{q(self.project)}" if project else "") + f"/_apis/{path}"
        params = dict(params or {})
        params.setdefault("api-version", api_version)
        url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if self.pat:
            token = base64.b64encode(f":{self.pat}".encode()).decode()
            req.add_header("Authorization", f"Basic {token}")
        else:
            req.add_header("Authorization", f"Bearer {self.bearer}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if resp.status == 203:
                    die("authentication failed (HTTP 203): check AZURE_DEVOPS_PAT")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except ValueError:
                pass
            if e.code in (401, 403):
                detail += (" (credential expired or missing scope: renew/regenerate the PAT "
                           "or run `az login` again)")
            die(f"{method} {path} -> HTTP {e.code}: {detail[:800]}")
        except urllib.error.URLError as e:
            die(f"{method} {path} -> {e.reason}")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            die("unexpected non-JSON response (usually an invalid PAT / sign-in page)")

    def repo_info(self):
        if self._repo_info is None:
            self._repo_info = self.request("GET", f"git/repositories/{q(self.repo)}")
        return self._repo_info


AZURE_DEVOPS_RESOURCE = "499b84ac-1321-427f-aa17-267ca6b798bc"


def az_cli_token():
    """Entra ID token for Azure DevOps from the Azure CLI (auto-refreshed by az)."""
    for exe in ("az", "az.cmd"):
        try:
            res = subprocess.run(
                [exe, "account", "get-access-token", "--resource", AZURE_DEVOPS_RESOURCE,
                 "--query", "accessToken", "-o", "tsv"],
                capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return ""


def summarize(ctx, item):
    f = item.get("fields", {})
    assigned = f.get("System.AssignedTo")
    if isinstance(assigned, dict):
        assigned = assigned.get("displayName")
    res = {
        "id": item.get("id"),
        "type": f.get("System.WorkItemType"),
        "title": f.get("System.Title"),
        "state": f.get("System.State"),
        "assignedTo": assigned,
        "url": ctx.web_item(item.get("id")),
    }
    rels = item.get("relations")
    if rels is not None:
        def rid(r):
            return int(r["url"].rstrip("/").split("/")[-1])
        parent = [rid(r) for r in rels if r.get("rel") == "System.LinkTypes.Hierarchy-Reverse"]
        res["parent"] = parent[0] if parent else None
        res["children"] = [rid(r) for r in rels if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"]
        res["artifacts"] = [
            {"name": r.get("attributes", {}).get("name"), "url": r.get("url")}
            for r in rels if r.get("rel") == "ArtifactLink"
        ]
    return res


def fetch_items(ctx, ids):
    ids = [int(i) for i in ids]
    items = []
    fields = "System.Id,System.WorkItemType,System.Title,System.State,System.AssignedTo"
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        res = ctx.request("GET", "wit/workitems",
                          params={"ids": ",".join(map(str, chunk)), "fields": fields})
        items.extend(res.get("value", []))
    order = {wid: n for n, wid in enumerate(ids)}
    items.sort(key=lambda it: order.get(it["id"], 0))
    return [summarize(ctx, it) for it in items]


def get_item(ctx, wid):
    item = ctx.request("GET", f"wit/workitems/{int(wid)}", params={"$expand": "relations"})
    item.setdefault("relations", [])  # API omits the key when there are none
    return item


def field_op(path, value):
    return {"op": "add", "path": f"/fields/{path}", "value": value}


def add_artifact_link(ctx, wid, artifact_url, name):
    item = get_item(ctx, wid)
    for rel in item.get("relations") or []:
        if rel.get("url", "").lower() == artifact_url.lower():
            return {"id": wid, "linked": False, "reason": "already linked", "artifact": artifact_url}
    ops = [{"op": "add", "path": "/relations/-",
            "value": {"rel": "ArtifactLink", "url": artifact_url, "attributes": {"name": name}}}]
    ctx.request("PATCH", f"wit/workitems/{int(wid)}", ops,
                content_type="application/json-patch+json")
    return {"id": wid, "linked": True, "name": name, "artifact": artifact_url}


# --------------------------------------------------------------------------- commands

def cmd_config(ctx, a):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    out({
        "org": ctx.org, "project": ctx.project, "repo": ctx.repo,
        "auth": ctx.auth_source or "az-cli (resolved on first API call)", "area": ctx.area, "iteration": ctx.iteration,
        "branch": branch or None, "workItem": work_item_from_branch(branch),
    })


def cmd_check(ctx, a):
    ctx.require()
    proj = ctx.request("GET", f"projects/{q(ctx.project)}", project=False)
    res = {"ok": True, "auth": ctx.auth_source, "org": ctx.org, "project": proj.get("name"),
           "process": None, "repo": None}
    try:
        props = ctx.request("GET", f"projects/{proj['id']}/properties", project=False,
                            api_version="7.1-preview.1")
        for p in props.get("value", []):
            if p.get("name") == "System.Process Template":
                res["process"] = p.get("value")
    except SystemExit:
        pass
    if ctx.repo:
        info = ctx.repo_info()
        res["repo"] = {"name": info.get("name"), "defaultBranch": info.get("defaultBranch")}
    out(res)


def cmd_current(ctx, a):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    out({"branch": branch or None, "workItem": work_item_from_branch(branch)})


def cmd_slug(ctx, a):
    out({"slug": slugify(a.text, a.max)})


def cmd_create(ctx, a):
    wtype = normalize_type(a.type)
    ops = [field_op("System.Title", a.title)]
    if a.description:
        ops.append(field_op("System.Description", as_html(a.description)))
    if a.acceptance:
        ops.append(field_op("Microsoft.VSTS.Common.AcceptanceCriteria", as_html(a.acceptance)))
    if a.tags:
        ops.append(field_op("System.Tags", "; ".join(t.strip() for t in a.tags.split(",") if t.strip())))
    area = a.area or ctx.area
    if area:
        ops.append(field_op("System.AreaPath", area))
    iteration = a.iteration or ctx.iteration
    if iteration:
        ops.append(field_op("System.IterationPath", iteration))
    if a.points is not None:
        ops.append(field_op("Microsoft.VSTS.Scheduling.StoryPoints", a.points))
    if a.priority is not None:
        ops.append(field_op("Microsoft.VSTS.Common.Priority", a.priority))
    if a.assign:
        ops.append(field_op("System.AssignedTo", a.assign))
    for kv in a.field or []:
        k, _, v = kv.partition("=")
        ops.append(field_op(k.strip(), v))
    if a.parent:
        ops.append({"op": "add", "path": "/relations/-",
                    "value": {"rel": "System.LinkTypes.Hierarchy-Reverse",
                              "url": ctx.api_item(a.parent)}})
    if a.dry_run:
        out({"dryRun": True, "type": wtype, "operations": ops})
        return
    ctx.require()
    item = ctx.request("POST", f"wit/workitems/${q(wtype)}", ops,
                       content_type="application/json-patch+json")
    res = summarize(ctx, item)
    res["parent"] = a.parent
    out(res)


def cmd_get(ctx, a):
    ctx.require()
    item = get_item(ctx, a.id)
    if a.raw:
        out(item)
        return
    res = summarize(ctx, item)
    f = item.get("fields", {})
    res["description"] = f.get("System.Description")
    res["acceptanceCriteria"] = f.get("Microsoft.VSTS.Common.AcceptanceCriteria")
    res["tags"] = f.get("System.Tags")
    res["areaPath"] = f.get("System.AreaPath")
    res["iterationPath"] = f.get("System.IterationPath")
    out(res)


def cmd_list(ctx, a):
    ctx.require()
    clauses = ["[System.TeamProject] = @project"]
    if a.type:
        clauses.append(f"[System.WorkItemType] = {wiql_str(normalize_type(a.type))}")
    if not a.all_states:
        clauses.append("[System.State] NOT IN ('Closed', 'Removed')")
    if a.search:
        terms = [t.strip() for t in a.search.split("|") if t.strip()]
        op = "CONTAINS WORDS" if a.words else "CONTAINS"
        fields = ["[System.Title]"] + (["[System.Description]"] if a.in_description else [])
        ors = [f"{fld} {op} {wiql_str(t)}" for t in terms for fld in fields]
        clauses.append("(" + " OR ".join(ors) + ")")
    if a.no_parent:
        clauses.append("[System.Parent] = ''")
    if a.mine:
        clauses.append("[System.AssignedTo] = @me")
    wiql = ("SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses)
            + " ORDER BY [System.ChangedDate] DESC")
    res = ctx.request("POST", "wit/wiql", {"query": wiql}, params={"$top": a.top})
    ids = [w["id"] for w in res.get("workItems", [])]
    out(fetch_items(ctx, ids) if ids else [])


def cmd_children(ctx, a):
    ctx.require()
    item = summarize(ctx, get_item(ctx, a.id))
    out({"parent": {k: item[k] for k in ("id", "type", "title", "state")},
         "children": fetch_items(ctx, item["children"]) if item["children"] else []})


def cmd_tree(ctx, a):
    """Epic -> Feature -> Story tree under an item (default depth 2)."""
    ctx.require()

    def walk(wid, depth):
        node = summarize(ctx, get_item(ctx, wid))
        node = {k: node[k] for k in ("id", "type", "title", "state", "children")}
        if depth > 0 and node["children"]:
            node["children"] = [walk(c, depth - 1) for c in node["children"]]
        return node

    out(walk(a.id, a.depth))


def cmd_update(ctx, a):
    ctx.require()
    ops = []
    if a.state:
        ops.append(field_op("System.State", a.state))
    if a.title:
        ops.append(field_op("System.Title", a.title))
    if a.description:
        ops.append(field_op("System.Description", as_html(a.description)))
    if a.acceptance:
        ops.append(field_op("Microsoft.VSTS.Common.AcceptanceCriteria", as_html(a.acceptance)))
    if a.assign:
        ops.append(field_op("System.AssignedTo", a.assign))
    for kv in a.field or []:
        k, _, v = kv.partition("=")
        ops.append(field_op(k.strip(), v))
    if a.parent:
        ops.append({"op": "add", "path": "/relations/-",
                    "value": {"rel": "System.LinkTypes.Hierarchy-Reverse",
                              "url": ctx.api_item(a.parent)}})
    if not ops:
        die("nothing to update")
    item = ctx.request("PATCH", f"wit/workitems/{int(a.id)}", ops,
                       content_type="application/json-patch+json")
    out(summarize(ctx, item))


def cmd_comment(ctx, a):
    ctx.require()
    res = ctx.request("POST", f"wit/workItems/{int(a.id)}/comments",
                      {"text": as_html(a.text)}, api_version=COMMENTS_API_VERSION)
    out({"id": a.id, "commentId": res.get("id")})


def cmd_link_branch(ctx, a):
    ctx.require(repo=True)
    branch = a.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        die("could not determine branch")
    info = ctx.repo_info()
    url = (f"vstfs:///Git/Ref/{info['project']['id']}%2F{info['id']}%2FGB"
           + urllib.parse.quote(branch, safe=""))
    res = add_artifact_link(ctx, a.id, url, "Branch")
    res["branch"] = branch
    out(res)


def cmd_link_commit(ctx, a):
    ctx.require(repo=True)
    sha = git("rev-parse", a.sha) or a.sha
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        die(f"could not resolve commit '{a.sha}' to a full SHA")
    info = ctx.repo_info()
    url = f"vstfs:///Git/Commit/{info['project']['id']}%2F{info['id']}%2F{sha}"
    res = add_artifact_link(ctx, a.id, url, "Fixed in Commit")
    res["sha"] = sha
    out(res)


def cmd_commits(ctx, a):
    """Local commits of the current branch vs base, with their work item refs."""
    base = a.base
    if not base:
        head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        base = head or "origin/main"
    log = git("log", f"{base}..HEAD", "--format=%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%b%x1e",
              "--date=short")
    commits = []
    for rec in filter(None, (r.strip() for r in log.split("\x1e"))):
        full, short, author, date, subject, body = (rec.split("\x1f") + [""] * 6)[:6]
        refs = sorted({int(x) for x in re.findall(r"(?<![\w&])#(\d+)\b", subject + "\n" + body)})
        cc = re.match(r"^(\w+)(?:\(([^)]+)\))?(!)?: ", subject)
        commits.append({
            "sha": full, "short": short, "author": author, "date": date,
            "subject": subject, "type": cc.group(1) if cc else None,
            "scope": cc.group(2) if cc else None, "breaking": bool(cc and cc.group(3)),
            "workItems": refs,
        })
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    out({"branch": branch, "base": base, "workItem": work_item_from_branch(branch),
         "count": len(commits), "commits": commits})


def cmd_pr(ctx, a):
    ctx.require(repo=True)
    info = ctx.repo_info()
    source = a.source or git("rev-parse", "--abbrev-ref", "HEAD")
    target = a.target or (info.get("defaultBranch") or "refs/heads/main")
    if not target.startswith("refs/"):
        target = "refs/heads/" + target
    wids = a.work_item or ([work_item_from_branch(source)] if work_item_from_branch(source) else [])
    body = {
        "sourceRefName": source if source.startswith("refs/") else "refs/heads/" + source,
        "targetRefName": target,
        "title": a.title,
        "description": (a.description or "")[:4000],
        "isDraft": bool(a.draft),
        "workItemRefs": [{"id": str(w)} for w in wids],
    }
    pr = ctx.request("POST", f"git/repositories/{info['id']}/pullrequests", body)
    out({"id": pr.get("pullRequestId"), "status": pr.get("status"), "isDraft": pr.get("isDraft"),
         "source": body["sourceRefName"], "target": target, "workItems": wids,
         "url": f"{ctx.base}/{q(ctx.project)}/_git/{q(ctx.repo)}/pullrequest/{pr.get('pullRequestId')}"})


# --------------------------------------------------------------------------- cli

def build_parser():
    p = argparse.ArgumentParser(prog="ado", description="Azure DevOps helper for azure-flow")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("config", help="show resolved config (no network)").set_defaults(fn=cmd_config)
    sub.add_parser("check", help="verify PAT/org/project/repo access").set_defaults(fn=cmd_check)
    sub.add_parser("current", help="work item id from current branch").set_defaults(fn=cmd_current)

    s = sub.add_parser("slug", help="slugify text for branch names")
    s.add_argument("text")
    s.add_argument("--max", type=int, default=40)
    s.set_defaults(fn=cmd_slug)

    s = sub.add_parser("create", help="create a work item")
    s.add_argument("--type", required=True, help="Epic | Feature | User Story | Task | Bug")
    s.add_argument("--title", required=True)
    s.add_argument("--description")
    s.add_argument("--acceptance", help="acceptance criteria (HTML or plain text)")
    s.add_argument("--parent", type=int)
    s.add_argument("--tags", help="comma separated")
    s.add_argument("--area")
    s.add_argument("--iteration")
    s.add_argument("--points", type=float)
    s.add_argument("--priority", type=int, choices=[1, 2, 3, 4])
    s.add_argument("--assign", help="user email / display name")
    s.add_argument("--field", action="append", help="Ref.Name=value (repeatable)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_create)

    s = sub.add_parser("get", help="get a work item")
    s.add_argument("id", type=int)
    s.add_argument("--raw", action="store_true")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("list", help="query work items")
    s.add_argument("--type")
    s.add_argument("--search", help="title contains; several terms separated by |")
    s.add_argument("--words", action="store_true", help="match whole words (CONTAINS WORDS)")
    s.add_argument("--in-description", action="store_true", help="also search the description")
    s.add_argument("--no-parent", action="store_true", help="only items without a parent")
    s.add_argument("--all-states", action="store_true")
    s.add_argument("--mine", action="store_true")
    s.add_argument("--top", type=int, default=50)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("children", help="direct children of a work item")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_children)

    s = sub.add_parser("tree", help="hierarchy under a work item")
    s.add_argument("id", type=int)
    s.add_argument("--depth", type=int, default=2)
    s.set_defaults(fn=cmd_tree)

    s = sub.add_parser("update", help="update fields / state / parent")
    s.add_argument("id", type=int)
    s.add_argument("--state", help="Agile: " + ", ".join(AGILE_STATES))
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--acceptance")
    s.add_argument("--assign")
    s.add_argument("--parent", type=int)
    s.add_argument("--field", action="append", help="Ref.Name=value (repeatable)")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("comment", help="add a discussion comment")
    s.add_argument("id", type=int)
    s.add_argument("text")
    s.set_defaults(fn=cmd_comment)

    s = sub.add_parser("link-branch", help="link a branch to a work item")
    s.add_argument("id", type=int)
    s.add_argument("--branch", help="default: current branch")
    s.set_defaults(fn=cmd_link_branch)

    s = sub.add_parser("link-commit", help="link a commit to a work item")
    s.add_argument("id", type=int)
    s.add_argument("sha", nargs="?", default="HEAD")
    s.set_defaults(fn=cmd_link_commit)

    s = sub.add_parser("commits", help="commits on current branch (local, no network)")
    s.add_argument("--base", help="default: origin/HEAD or origin/main")
    s.set_defaults(fn=cmd_commits)

    s = sub.add_parser("pr", help="open a pull request linked to work items")
    s.add_argument("--title", required=True)
    s.add_argument("--description")
    s.add_argument("--source", help="default: current branch")
    s.add_argument("--target", help="default: repo default branch")
    s.add_argument("--work-item", type=int, action="append", help="default: id from branch")
    s.add_argument("--draft", action="store_true")
    s.set_defaults(fn=cmd_pr)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    args.fn(Ctx(), args)


if __name__ == "__main__":
    main()
