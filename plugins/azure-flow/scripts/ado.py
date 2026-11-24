#!/usr/bin/env python3
"""Azure DevOps CLI used by the azure-flow Claude Code plugin.

Standard library only (works on Linux, macOS and Windows with Python 3.8+).

Configuration: org/project/repo come from the `origin` remote of an Azure
Repos checkout; the env vars below are the fallback when there is no such remote.

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

# Work item types of the Agile and Scrum templates (+ friendly aliases).
TYPE_ALIASES = {
    "epic": "Epic",
    "feature": "Feature",
    "story": "User Story",
    "user story": "User Story",
    "userstory": "User Story",
    "us": "User Story",
    "pbi": "Product Backlog Item",
    "product backlog item": "Product Backlog Item",
    "backlog item": "Product Backlog Item",
    "impediment": "Impediment",
    "task": "Task",
    "bug": "Bug",
    "issue": "Issue",
}

# Module tags per repository (matches the project's existing tag vocabulary).
# Override/extend with `.azure-flow.json` at the repo root: {"modules": {"<repo>": ["Tag", ...]}}
# or with the AZURE_FLOW_MODULES env var holding the same JSON object.
MODULE_TAGS = {
    "api-bpms": ["BPMS"],
    "api-signature": ["Signature"],
    "api-corda-signature": ["Signature", "Corda API"],
    "api-cordapp-signature": ["Signature", "Corda API"],
    "api-account": ["Account"],
    "api-cloud": ["Cloud"],
    "api-email": ["Email"],
    "api-orchestrator": ["Orchestrator"],
    "api-orchestrator-corda-agent": ["Orchestrator", "Corda API"],
    "api-orchestrator-corda-node-api": ["Orchestrator", "Corda API"],
    "aba-frontend": ["Frontend"],
    "aba-frontend-lib": ["Frontend"],
    "aba-gateway": ["Gateway"],
    "aba-ai-agent": ["AgentIA"],
    "aba-ai-model": ["AgentIA"],
    "aba-infra-banco": ["InfraBanco"],
    "aba-keycloak": ["Keycloak"],
    "aba-observability": ["Observabilidade"],
    "aba-dev-provisioner": ["Provisioner"],
    "aba-zot-registry": ["Registry"],
    "aba-landingpage": ["LandingPage"],
    "obras-frontend": ["Obras", "Frontend"],
    "obras-backend": ["Obras"],
    "aba-obras": ["Obras"],
    "licitacerto": ["Licitacerto"],
    "redmine": ["Redmine"],
}
PLUGIN_TAG = "azure-flow"

# Work item link types: friendly name -> (reference name, label).
RELATION_TYPES = {
    "related": ("System.LinkTypes.Related", "Related"),
    "parent": ("System.LinkTypes.Hierarchy-Reverse", "Parent"),
    "child": ("System.LinkTypes.Hierarchy-Forward", "Child"),
    "predecessor": ("System.LinkTypes.Dependency-Reverse", "Predecessor"),
    "successor": ("System.LinkTypes.Dependency-Forward", "Successor"),
    "duplicate": ("System.LinkTypes.Duplicate-Forward", "Duplicate"),
    "duplicate-of": ("System.LinkTypes.Duplicate-Reverse", "Duplicate Of"),
    "tests": ("Microsoft.VSTS.Common.TestedBy-Reverse", "Tests"),
    "tested-by": ("Microsoft.VSTS.Common.TestedBy-Forward", "Tested By"),
}
RELATION_LABELS = {ref: label for ref, label in RELATION_TYPES.values()}

# Common states (User Story / Product Backlog Item).
AGILE_STATES = ["New", "Active", "Resolved", "Closed", "Removed"]
SCRUM_STATES = ["New", "Approved", "Committed", "Done", "Removed"]

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


MAP_KEY = "azureworkitem"  # git config branch.<name>.azureworkitem=<id>


def mapped_work_item(branch):
    val = git("config", "--get", f"branch.{branch}.{MAP_KEY}") if branch else ""
    return int(val) if val.isdigit() else None


def branch_work_item(branch):
    """Work item for a branch: id in the name, else the local git config mapping."""
    return work_item_from_branch(branch) or mapped_work_item(branch)


def iteration_path(ctx, value):
    """'80' or 'Sprint 80' -> '<Project>\\Sprint 80'; full paths pass through."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        v = f"Sprint {v}"
    if not v.startswith(ctx.project + "\\"):
        v = f"{ctx.project}\\{v}"
    return v


def module_map():
    mapping = dict(MODULE_TAGS)
    root = git("rev-parse", "--show-toplevel")
    sources = [os.environ.get("AZURE_FLOW_MODULES", "")]
    if root and os.path.exists(os.path.join(root, ".azure-flow.json")):
        with open(os.path.join(root, ".azure-flow.json"), encoding="utf-8") as f:
            sources.append(f.read())
    for raw in sources:
        if raw.strip():
            try:
                mapping.update(json.loads(raw).get("modules", {}))
            except (ValueError, AttributeError):
                print("warning: ignoring invalid module mapping JSON", file=sys.stderr)
    return mapping


def module_tags(repo):
    """Module tags for a repo name; unknown repos fall back to a name without api-/aba-."""
    if not repo:
        return []
    mapping = module_map()
    if repo in mapping:
        return list(mapping[repo])
    base = re.sub(r"^(api|aba)-", "", repo)
    return [base.replace("-", " ").title().replace(" ", "")] if base else []


def kebab(text):
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()


def normalize_tags(tags, existing=(), canonical=()):
    """Reuse the spelling of existing/canonical tags (case/accent-insensitive);
    anything new becomes kebab-case ascii. Order kept, duplicates dropped."""
    known = {}
    for t in list(canonical) + list(existing):
        known.setdefault(kebab(t), t)
    res, seen = [], set()
    for t in tags:
        t = (t or "").strip()
        if not t:
            continue
        key = kebab(t)
        name = known.get(key, key)
        if key and key not in seen:
            seen.add(key)
            res.append(name)
    return res


def split_tags(value):
    if not value:
        return []
    return [t.strip() for t in re.split(r"[;,]", value) if t.strip()]


def slugify(text, max_len=40):
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "work"


def normalize_type(t):
    key = (t or "").strip().lower()
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    die(f"unknown work item type '{t}'. Use one of: Epic, Feature, User Story, "
        "Product Backlog Item, Task, Bug, Impediment")


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
        # The Azure Repos remote of the current checkout wins; env vars are the fallback
        # (outside a checkout, or when origin is not on Azure Repos).
        self.org = remote.get("org") or os.environ.get("AZURE_DEVOPS_ORG")
        self.project = remote.get("project") or os.environ.get("AZURE_DEVOPS_PROJECT")
        self.repo = remote.get("repo") or os.environ.get("AZURE_DEVOPS_REPO")
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
                content_type="application/json", api_version=API_VERSION, team=None):
        url = (self.base + (f"/{q(self.project)}" if project else "")
               + (f"/{q(team)}" if team else "") + f"/_apis/{path}")
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

    def project_tags(self):
        if getattr(self, "_tags", None) is None:
            try:
                res = self.request("GET", "wit/tags", api_version="7.1-preview.1")
                self._tags = [t["name"] for t in res.get("value", [])]
            except SystemExit:
                self._tags = []
        return self._tags

    def build_tags(self, raw=None, modules=(), auto_module=False, current=None, remove=None):
        canonical = [x for v in module_map().values() for x in v] + [PLUGIN_TAG]
        wanted = split_tags(current) + split_tags(raw)
        for m in modules or []:
            wanted += module_tags(m) if (m in module_map() or "-" in m) else [m]
        if auto_module:
            wanted += module_tags(self.repo)
        wanted.append(PLUGIN_TAG)
        tags = normalize_tags(wanted, self.project_tags(), canonical)
        drop = {kebab(t) for t in split_tags(remove)}
        return [t for t in tags if kebab(t) not in drop]

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
        res["links"] = [
            {"type": RELATION_LABELS[r["rel"]], "id": rid(r),
             "comment": (r.get("attributes") or {}).get("comment")}
            for r in rels if r.get("rel") in RELATION_LABELS
            and r["rel"] not in ("System.LinkTypes.Hierarchy-Reverse", "System.LinkTypes.Hierarchy-Forward")
        ]
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


def add_artifact_links(ctx, wid, links):
    """links: [(artifact_url, name)]. Skips ones already linked. One PATCH for all."""
    item = get_item(ctx, wid)
    existing = {r.get("url", "").lower() for r in item.get("relations") or []}
    new = [(u, n) for u, n in links if u.lower() not in existing]
    if new:
        ops = [{"op": "add", "path": "/relations/-",
                "value": {"rel": "ArtifactLink", "url": u, "attributes": {"name": n}}}
               for u, n in new]
        ctx.request("PATCH", f"wit/workitems/{int(wid)}", ops,
                    content_type="application/json-patch+json")
    return {"id": wid, "linked": len(new), "alreadyLinked": len(links) - len(new)}


def add_artifact_link(ctx, wid, artifact_url, name):
    res = add_artifact_links(ctx, wid, [(artifact_url, name)])
    return {"id": wid, "linked": bool(res["linked"]), "name": name, "artifact": artifact_url}


def branch_artifact(info, branch):
    return (f"vstfs:///Git/Ref/{info['project']['id']}%2F{info['id']}%2FGB"
            + urllib.parse.quote(branch, safe=""))


def commit_artifact(info, sha):
    return f"vstfs:///Git/Commit/{info['project']['id']}%2F{info['id']}%2F{sha}"


def default_base():
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for cand in ("origin/main", "origin/master", "origin/dev", "origin/develop"):
        if git("rev-parse", "-q", "--verify", cand):
            return cand
    return "origin/main"


# --------------------------------------------------------------------------- commands

def cmd_config(ctx, a):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    out({
        "org": ctx.org, "project": ctx.project, "repo": ctx.repo,
        "auth": ctx.auth_source or "az-cli (resolved on first API call)", "area": ctx.area, "iteration": ctx.iteration,
        "branch": branch or None, "workItem": branch_work_item(branch),
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


def cmd_types(ctx, a):
    ctx.require()
    res = []
    for t in ctx.request("GET", "wit/workitemtypes").get("value", []):
        if t.get("isDisabled"):
            continue
        name = t["name"]
        if name not in {"Epic", "Feature", "User Story", "Product Backlog Item", "Task", "Bug",
                        "Issue", "Impediment"}:
            continue
        states = ctx.request("GET", f"wit/workitemtypes/{q(name)}/states").get("value", [])
        res.append({"type": name, "states": [s["name"] for s in states]})
    names = {r["type"] for r in res}
    backlog = "Product Backlog Item" if "Product Backlog Item" in names else (
        "User Story" if "User Story" in names else None)
    out({"backlogItemType": backlog, "types": res})


def cmd_sprints(ctx, a):
    ctx.require()
    root = ctx.request("GET", "wit/classificationnodes/iterations", params={"$depth": 5})
    res = []

    def walk(node, path):
        attrs = node.get("attributes") or {}
        if path != ctx.project:
            res.append({"path": path, "start": (attrs.get("startDate") or "")[:10] or None,
                        "finish": (attrs.get("finishDate") or "")[:10] or None})
        for ch in node.get("children") or []:
            walk(ch, f"{path}\\{ch['name']}")

    walk(root, ctx.project)
    res.sort(key=lambda x: (x["start"] or "", x["path"]))
    out(res[-a.last:] if a.last else res)


def cmd_sprint_create(ctx, a):
    """Create an iteration (sprint) and add it to a team's sprints. Needs project/team admin rights."""
    ctx.require()
    body = {"name": a.name, "attributes": {"startDate": f"{a.start}T00:00:00Z",
                                           "finishDate": f"{a.finish}T00:00:00Z"}}
    if a.dry_run:
        out({"dryRun": True, "iteration": body, "team": a.team})
        return
    node = ctx.request("POST", "wit/classificationnodes/iterations", body)
    res = {"path": node.get("path"), "identifier": node.get("identifier"), "team": None}
    if a.team:
        try:
            ctx.request("POST", "work/teamsettings/iterations", {"id": node["identifier"]}, team=a.team)
            res["team"] = a.team
        except SystemExit:
            res["teamError"] = "sprint created, but adding it to the team failed: do it in Team settings"
    out(res)


def cmd_tags(ctx, a):
    ctx.require()
    tags = sorted(ctx.project_tags(), key=str.lower)
    if a.search:
        tags = [t for t in tags if kebab(a.search) in kebab(t)]
    out({"count": len(tags), "tags": tags})


def cmd_module(ctx, a):
    repo = a.repo or ctx.repo
    out({"repo": repo, "moduleTags": module_tags(repo)})


def cmd_current(ctx, a):
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    wid = work_item_from_branch(branch)
    source = "branch-name" if wid else None
    if not wid:
        wid = mapped_work_item(branch)
        source = "git-config" if wid else None
    out({"branch": branch or None, "workItem": wid, "source": source})


def cmd_slug(ctx, a):
    out({"slug": slugify(a.text, a.max)})


def cmd_create(ctx, a):
    wtype = normalize_type(a.type)
    ops = [field_op("System.Title", a.title)]
    if a.description:
        ops.append(field_op("System.Description", as_html(a.description)))
    if a.acceptance:
        ops.append(field_op("Microsoft.VSTS.Common.AcceptanceCriteria", as_html(a.acceptance)))
    if a.dry_run and not ctx.pat and not ctx.bearer:
        ctx._tags = []  # offline dry-run: skip fetching existing tags
    tags = ctx.build_tags(a.tags, a.module, a.auto_module)
    ops.append(field_op("System.Tags", "; ".join(tags)))
    area = a.area or ctx.area
    if area:
        ops.append(field_op("System.AreaPath", area))
    iteration = iteration_path(ctx, a.iteration or ctx.iteration)
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
    if a.sprint:
        ops.append(field_op("System.IterationPath", iteration_path(ctx, a.sprint)))
    if a.add_tags or a.remove_tags or a.module:
        current = get_item(ctx, a.id)["fields"].get("System.Tags", "")
        tags = ctx.build_tags(a.add_tags, a.module, False, current=current, remove=a.remove_tags)
        ops.append(field_op("System.Tags", "; ".join(tags)))
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


def cmd_relate(ctx, a):
    """Link one work item to others (related, predecessor/successor, duplicate...)."""
    ref, label = RELATION_TYPES[a.type]
    targets = [t for t in a.targets if t != a.id]
    if not targets:
        die("nothing to link (target equals source)")
    if a.dry_run:
        out({"dryRun": True, "id": a.id, "type": label, "targets": targets, "comment": a.comment})
        return
    ctx.require()
    item = get_item(ctx, a.id)
    existing = {(r.get("rel"), r.get("url", "").rstrip("/").split("/")[-1])
                for r in item.get("relations") or []}
    new = [t for t in targets if (ref, str(t)) not in existing]
    if a.type == "parent" and (len(new) > 1 or any(r.get("rel") == ref for r in item["relations"])):
        die("a work item can have only one parent: remove the current one first (unrelate --type parent)")
    if new:
        attrs = {"comment": a.comment} if a.comment else {}
        ops = [{"op": "add", "path": "/relations/-",
                "value": {"rel": ref, "url": ctx.api_item(t), "attributes": attrs}} for t in new]
        ctx.request("PATCH", f"wit/workitems/{a.id}", ops, content_type="application/json-patch+json")
    out({"id": a.id, "type": label, "linked": new,
         "alreadyLinked": [t for t in targets if t not in new]})


def cmd_unrelate(ctx, a):
    ctx.require()
    item = get_item(ctx, a.id)
    refs = [RELATION_TYPES[a.type][0]] if a.type else list(RELATION_LABELS)
    idx = [i for i, r in enumerate(item["relations"])
           if r.get("rel") in refs and r.get("url", "").rstrip("/").split("/")[-1] in map(str, a.targets)]
    if not idx:
        out({"id": a.id, "removed": 0})
        return
    ops = [{"op": "test", "path": "/rev", "value": item["rev"]}]
    ops += [{"op": "remove", "path": f"/relations/{i}"} for i in sorted(idx, reverse=True)]
    ctx.request("PATCH", f"wit/workitems/{a.id}", ops, content_type="application/json-patch+json")
    out({"id": a.id, "removed": len(idx)})


def cmd_link_branch(ctx, a):
    ctx.require(repo=True)
    branch = a.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        die("could not determine branch")
    info = ctx.repo_info()
    res = add_artifact_link(ctx, a.id, branch_artifact(info, branch), "Branch")
    res["branch"] = branch
    out(res)


def cmd_link_commit(ctx, a):
    if a.repo:
        ctx.repo, ctx._repo_info = a.repo, None
    ctx.require(repo=True)
    sha = a.sha if re.fullmatch(r"[0-9a-f]{40}", a.sha) else (git("rev-parse", a.sha) or a.sha)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        die(f"could not resolve commit '{a.sha}' to a full SHA")
    info = ctx.repo_info()
    res = add_artifact_link(ctx, a.id, commit_artifact(info, sha), "Fixed in Commit")
    res["sha"] = sha
    out(res)


def cmd_map(ctx, a):
    """Associate an existing branch (no id in its name) with a work item, without renaming."""
    branch = a.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        die("could not determine branch")
    if subprocess.run(["git", "config", f"branch.{branch}.{MAP_KEY}", str(a.id)]).returncode:
        die("git config failed (not a git repository?)")
    res = {"branch": branch, "workItem": a.id, "mapped": True, "branchLinked": None}
    if not a.no_link:
        ctx.require(repo=True)
        res["branchLinked"] = add_artifact_link(ctx, a.id, branch_artifact(ctx.repo_info(), branch),
                                                "Branch")["linked"]
    out(res)


def cmd_unmap(ctx, a):
    branch = a.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    subprocess.run(["git", "config", "--unset", f"branch.{branch}.{MAP_KEY}"])
    out({"branch": branch, "mapped": False})


def cmd_link_commits(ctx, a):
    """Link every pushed commit of the branch (vs base) to the work item. No history rewrite."""
    ctx.require(repo=True)
    branch = a.branch or git("rev-parse", "--abbrev-ref", "HEAD")
    wid = a.id or branch_work_item(branch)
    if not wid:
        die(f"no work item for branch '{branch}': pass an id or run `map <id>` first")
    base = a.base or default_base()
    remote_ref = f"origin/{branch}"
    if not git("rev-parse", "-q", "--verify", remote_ref):
        die(f"{remote_ref} not found: push the branch first (only pushed commits can be linked)")
    rev_args = ["rev-list"] + ([] if a.include_merges else ["--no-merges"]) + [f"{base}..{remote_ref}"]
    shas = git(*rev_args).split()
    if a.dry_run:
        out({"workItem": wid, "branch": branch, "base": base, "commits": len(shas), "dryRun": True})
        return
    info = ctx.repo_info()
    res = add_artifact_links(ctx, wid, [(commit_artifact(info, x), "Fixed in Commit") for x in shas])
    res.update(branch=branch, base=base, commits=len(shas))
    out(res)


def cmd_commits(ctx, a):
    """Local commits of the current branch vs base, with their work item refs."""
    base = a.base or default_base()
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
    out({"branch": branch, "base": base, "workItem": branch_work_item(branch),
         "count": len(commits), "commits": commits})


def cmd_pr(ctx, a):
    ctx.require(repo=True)
    info = ctx.repo_info()
    source = a.source or git("rev-parse", "--abbrev-ref", "HEAD")
    target = a.target or (info.get("defaultBranch") or "refs/heads/main")
    if not target.startswith("refs/"):
        target = "refs/heads/" + target
    wids = a.work_item or ([branch_work_item(source)] if branch_work_item(source) else [])
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
    sub.add_parser("types", help="work item types and states of the project").set_defaults(fn=cmd_types)

    s = sub.add_parser("sprints", help="iterations (sprints) of the project with dates")
    s.add_argument("--last", type=int, default=10, help="only the last N (0 = all)")
    s.set_defaults(fn=cmd_sprints)

    s = sub.add_parser("sprint-create", help="create a sprint and add it to a team (admin rights)")
    s.add_argument("--name", required=True, help='e.g. "Sprint 80"')
    s.add_argument("--start", required=True, help="YYYY-MM-DD")
    s.add_argument("--finish", required=True, help="YYYY-MM-DD")
    s.add_argument("--team", help='e.g. "ABA Team"')
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_sprint_create)

    s = sub.add_parser("tags", help="tags already used in the project (reuse their spelling)")
    s.add_argument("--search")
    s.set_defaults(fn=cmd_tags)

    s = sub.add_parser("module", help="module tags of a repository (default: current repo)")
    s.add_argument("--repo")
    s.set_defaults(fn=cmd_module)

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
    s.add_argument("--tags", help="comma separated: feature/topic + nature, e.g. 'retencao,i18n,reteste-qa'")
    s.add_argument("--module", action="append",
                   help="repo name or module tag to tag the item with (repeatable), e.g. api-bpms")
    s.add_argument("--auto-module", action="store_true", help="add the module tags of the current repo")
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
    s.add_argument("--state", help="User Story: " + ", ".join(AGILE_STATES)
                   + " | PBI: " + ", ".join(SCRUM_STATES))
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--acceptance")
    s.add_argument("--assign")
    s.add_argument("--parent", type=int)
    s.add_argument("--sprint", help='move to a sprint: "80", "Sprint 80" or full iteration path')
    s.add_argument("--add-tags", help="comma separated, merged with the current tags")
    s.add_argument("--remove-tags", help="comma separated")
    s.add_argument("--module", action="append", help="repo name or module tag to add (repeatable)")
    s.add_argument("--field", action="append", help="Ref.Name=value (repeatable)")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("comment", help="add a discussion comment")
    s.add_argument("id", type=int)
    s.add_argument("text")
    s.set_defaults(fn=cmd_comment)

    s = sub.add_parser("relate", help="link work items to each other (default: related)")
    s.add_argument("id", type=int, help="source work item")
    s.add_argument("targets", type=int, nargs="+", help="one or more work items to link")
    s.add_argument("--type", default="related", choices=list(RELATION_TYPES),
                   help="link type, read as '<targets> is the <type> of <id>' (default: related)")
    s.add_argument("--comment", help="comment shown on the link")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_relate)

    s = sub.add_parser("unrelate", help="remove links between work items")
    s.add_argument("id", type=int)
    s.add_argument("targets", type=int, nargs="+")
    s.add_argument("--type", choices=list(RELATION_TYPES), help="default: any link type")
    s.set_defaults(fn=cmd_unrelate)

    s = sub.add_parser("link-branch", help="link a branch to a work item")
    s.add_argument("id", type=int)
    s.add_argument("--branch", help="default: current branch")
    s.set_defaults(fn=cmd_link_branch)

    s = sub.add_parser("link-commit", help="link a commit to a work item")
    s.add_argument("id", type=int)
    s.add_argument("sha", nargs="?", default="HEAD", help="full SHA (any repo) or ref of the local clone")
    s.add_argument("--repo", help="Azure repo name (default: origin of the current clone)")
    s.set_defaults(fn=cmd_link_commit)

    s = sub.add_parser("map", help="map an existing branch to a work item (git config) + link it")
    s.add_argument("id", type=int)
    s.add_argument("--branch", help="default: current branch")
    s.add_argument("--no-link", action="store_true", help="only local mapping, no board link")
    s.set_defaults(fn=cmd_map)

    s = sub.add_parser("unmap", help="remove a branch mapping")
    s.add_argument("--branch")
    s.set_defaults(fn=cmd_unmap)

    s = sub.add_parser("link-commits", help="link all pushed commits of a branch to its work item")
    s.add_argument("id", type=int, nargs="?", help="default: work item of the branch")
    s.add_argument("--branch")
    s.add_argument("--base", help="default: origin/HEAD, main, master, dev or develop")
    s.add_argument("--include-merges", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_link_commits)

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
