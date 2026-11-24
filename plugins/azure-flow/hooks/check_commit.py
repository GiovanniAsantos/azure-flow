#!/usr/bin/env python3
"""PreToolUse hook (Bash): enforce Conventional Commits + work item reference.

On a branch like feature/123-login-sso, `git commit` must:
  * have a Conventional Commits header  (feat(scope): summary)
  * reference the work item             (footer "Refs: #123")
Azure Repos links commits mentioning #<id> to the work item on push.
Exit code 2 blocks the tool call and shows stderr to Claude so it can fix it.
"""
import json
import re
import subprocess
import sys

CC_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]+\))?!?: \S.*")
# git commit at the start of a (sub)command, optionally after VAR=val prefixes.
GIT_COMMIT_RE = re.compile(r"(?:^|[;&|(\n])\s*(?:\w+=\S*\s+)*git(?:\s+-[cC]\s+\S+)*\s+commit\b")


def first_message(cmd):
    """Best-effort extraction of the first -m / --message value."""
    m = re.search(r"""(?:\s-m|\s--message)(?:=|\s+)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|(\S+))""",
                  cmd, re.S)
    if not m:
        return None
    msg = next(g for g in m.groups() if g is not None)
    heredoc = re.match(r"\$\(cat <<-?\s*['\"]?(\w+)['\"]?\s*\n(.*)", msg, re.S)
    if heredoc:
        msg = heredoc.group(2)
    return msg.strip().splitlines()[0].strip() if msg.strip() else None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not GIT_COMMIT_RE.search(cmd):
        return 0
    if "--amend" in cmd and "--no-edit" in cmd:
        return 0
    try:
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                text=True, cwd=data.get("cwd") or None, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 0
    m = re.search(r"(?:^|/)(\d+)(?=-|$)", branch)
    if not m:
        return 0
    wid = m.group(1)
    problems = []
    uses_file = re.search(r"\s(-F|--file)(=|\s)", cmd)
    if not uses_file and not re.search(rf"(?<![\w&])#{wid}\b", cmd):
        problems.append(f"missing work item reference: add the footer 'Refs: #{wid}'")
    header = None if uses_file else first_message(cmd)
    if header and not header.startswith(("Merge ", "Revert \"")) and not CC_RE.match(header):
        problems.append(f"header '{header}' is not Conventional Commits "
                        "(type(scope): summary, type in feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)")
    if problems:
        print(f"azure-flow: commit blocked on branch '{branch}' (work item #{wid}):\n- "
              + "\n- ".join(problems)
              + f"\nExample: git commit -m \"feat(auth): add SSO login\" -m \"Refs: #{wid}\"",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
