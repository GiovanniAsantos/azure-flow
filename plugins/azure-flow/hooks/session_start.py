#!/usr/bin/env python3
"""SessionStart hook: exposes the plugin path and the current work item to Claude."""
import json
import os
import re
import subprocess
import sys

root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ado = os.path.join(root, "scripts", "ado.py")

try:
    data = json.load(sys.stdin)
except ValueError:
    data = {}
cwd = data.get("cwd") or None

env_file = os.environ.get("CLAUDE_ENV_FILE")
if env_file:
    try:
        with open(env_file, "a", encoding="utf-8") as f:
            f.write(f'export AZURE_FLOW_ADO="{ado}"\n')
    except OSError:
        pass


def git(*args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


lines = [
    "azure-flow plugin active (Azure Boards + Azure Repos, Scrum, Conventional Commits).",
    f'Azure DevOps CLI: python3 "{ado}" <command>   (also in $AZURE_FLOW_ADO)',
]
remote = git("remote", "get-url", "origin")
if remote and not re.search(r"dev\.azure\.com|visualstudio\.com", remote):
    lines.append("Note: origin is not an Azure Repos remote; set AZURE_DEVOPS_ORG/PROJECT/REPO if needed.")
branch = git("rev-parse", "--abbrev-ref", "HEAD")
m = re.search(r"(?:^|/)(\d+)(?=-|$)", branch)
wid = m.group(1) if m else (git("config", "--get", f"branch.{branch}.azureworkitem") if branch else "")
if wid:
    lines.append(f"Current branch '{branch}' tracks work item #{wid}: every commit must "
                 f"follow Conventional Commits and carry the footer 'Refs: #{wid}'.")
if not os.environ.get("AZURE_DEVOPS_PAT") and not os.environ.get("AZURE_DEVOPS_TOKEN"):
    lines.append("No AZURE_DEVOPS_PAT/AZURE_DEVOPS_TOKEN set: ado.py will try the Azure CLI (`az login`).")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": "\n".join(lines)}}))
