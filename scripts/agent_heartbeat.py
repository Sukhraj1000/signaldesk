#!/usr/bin/env python3
"""Read GitHub project context and emit the next AI-development loop actions.

This script is intentionally read-only. It does not create branches, comments,
commits, PRs, or merges. It gives the heartbeat/orchestrator enough context to
choose the next bounded sub-agent lane.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = "Sukhraj1000/signaldesk"
OWNER, REPO_NAME = REPO.split("/", 1)
ROADMAP = ROOT / "roadmap.md"
API_ERRORS: list[str] = []


@dataclass(frozen=True)
class Action:
    lane: str
    target: str
    reason: str
    suggested_agent: str


@dataclass(frozen=True)
class OrderedTarget:
    issue: dict[str, Any]
    parent_number: int

    @property
    def issue_number(self) -> int:
        return int(self.issue["number"])

    @property
    def label(self) -> str:
        parent = (
            f" under roadmap parent #{self.parent_number}"
            if self.parent_number != self.issue_number
            else ""
        )
        return f"Issue #{self.issue_number}: {self.issue['title']}{parent}"


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def gh_json(args: list[str]) -> Any:
    completed = run(["gh", *args])
    return json.loads(completed.stdout or "null")


def gh_api(path: str) -> Any:
    completed = run(["gh", "api", path], check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"gh api failed for {path}: {message}")
    return json.loads(completed.stdout or "[]")


def gh_graphql(query: str, fields: dict[str, str | int]) -> Any:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in fields.items():
        flag = "-F" if isinstance(value, int) else "-f"
        args.extend([flag, f"{key}={value}"])
    completed = run(args, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"gh graphql failed: {message}")
    return json.loads(completed.stdout or "{}")


def roadmap_snapshot() -> list[str]:
    if not ROADMAP.exists():
        return ["roadmap.md not present in this checkout"]

    headings: list[str] = []
    for line in ROADMAP.read_text(encoding="utf-8").splitlines():
        if line.startswith("##"):
            headings.append(line.strip())
    return headings[:20] or ["roadmap.md has no section headings"]


def check_summary(checks: list[dict[str, Any]]) -> tuple[int, int, int]:
    failed = 0
    pending = 0
    passed = 0
    for check in checks:
        status = check.get("status")
        conclusion = check.get("conclusion")
        if status != "COMPLETED":
            pending += 1
        elif conclusion == "SUCCESS":
            passed += 1
        else:
            failed += 1
    return passed, pending, failed


def issue_comments(number: int) -> list[dict[str, Any]]:
    try:
        comments = gh_api(f"repos/{REPO}/issues/{number}/comments?per_page=20")
    except RuntimeError as exc:
        API_ERRORS.append(str(exc))
        return []
    return [
        {
            "author": comment.get("user", {}).get("login"),
            "createdAt": comment.get("created_at"),
            "body": (comment.get("body") or "")[:500],
        }
        for comment in comments[-5:]
    ]


def pr_review_comments(number: int) -> list[dict[str, Any]]:
    query = """
    query($owner:String!, $repo:String!, $num:Int!) {
      repository(owner:$owner, name:$repo) {
        pullRequest(number:$num) {
          reviewThreads(first:50) {
            nodes {
              isResolved
              path
              comments(first:1) {
                nodes {
                  author { login }
                  createdAt
                  body
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        data = gh_graphql(query, {"owner": OWNER, "repo": REPO_NAME, "num": number})
    except RuntimeError as exc:
        API_ERRORS.append(str(exc))
        return []

    threads = (
        data.get("data", {})
        .get("repository", {})
        .get("pullRequest", {})
        .get("reviewThreads", {})
        .get("nodes", [])
    )
    unresolved: list[dict[str, Any]] = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = thread.get("comments", {}).get("nodes", [])
        if not comments:
            continue
        comment = comments[0]
        unresolved.append(
            {
                "author": comment.get("author", {}).get("login"),
                "path": thread.get("path"),
                "createdAt": comment.get("createdAt"),
                "body": (comment.get("body") or "")[:500],
            }
        )
    return unresolved[-5:]


def label_names(item: dict[str, Any]) -> set[str]:
    return {label["name"] for label in item.get("labels", []) if "name" in label}


def parent_issue_number(issue: dict[str, Any]) -> int:
    """Return the roadmap parent used for ordered execution.

    GitHub issues are the execution plan. Roadmap parents keep their own issue
    number; implementation children may declare ``Parent: #NN`` in their body.
    When no parent is declared, the issue orders by its own number.
    """

    labels = label_names(issue)
    if "roadmap" in labels:
        return int(issue["number"])

    match = re.search(r"(?im)^\s*Parent:\s*#(\d+)\b", issue.get("body") or "")
    if match:
        return int(match.group(1))
    return int(issue["number"])


def ordered_issue_targets(issues: list[dict[str, Any]]) -> list[OrderedTarget]:
    """Return open issues in canonical roadmap/issue order, lowest first."""

    targets = [
        OrderedTarget(issue=issue, parent_number=parent_issue_number(issue))
        for issue in issues
    ]
    return sorted(targets, key=lambda target: (target.parent_number, target.issue_number))


def active_ordered_target(issues: list[dict[str, Any]]) -> OrderedTarget | None:
    ordered = ordered_issue_targets(issues)
    return ordered[0] if ordered else None


def actionable_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out bot/status comments that should not block the loop."""

    actionable: list[dict[str, Any]] = []
    ignored_markers = (
        "review skipped",
        "auto-generated comment",
        "finishing touches",
        "local heartbeat + preflight + tox are passing",
    )
    for comment in comments:
        author = (comment.get("author") or "").lower()
        body = (comment.get("body") or "").lower()
        if author.endswith("[bot]") or author in {"coderabbitai"}:
            if any(marker in body for marker in ignored_markers):
                continue
        if any(marker in body for marker in ignored_markers):
            continue
        actionable.append(comment)
    return actionable


def propose_actions(issues: list[dict[str, Any]], prs: list[dict[str, Any]]) -> list[Action]:
    actions: list[Action] = []
    pr_titles = {pr["title"].lower() for pr in prs}

    for pr in prs:
        passed, pending, failed = check_summary(pr.get("statusCheckRollup", []))
        comments = actionable_comments(issue_comments(pr["number"]))
        review_comments = pr_review_comments(pr["number"])
        target = f"PR #{pr['number']}: {pr['title']}"
        if API_ERRORS:
            actions.append(
                Action(
                    lane="manual-check",
                    target=target,
                    reason="GitHub API lookup failed; not safe to infer PR state",
                    suggested_agent="no coding agent; inspect GitHub/API credentials",
                )
            )
        elif failed:
            actions.append(
                Action(
                    lane="fix-pr",
                    target=target,
                    reason=f"{failed} failing check(s)",
                    suggested_agent="bug/fix agent on existing branch, then rerun checks",
                )
            )
        elif comments or review_comments:
            actions.append(
                Action(
                    lane="respond-to-review",
                    target=target,
                    reason="PR has comments/review comments to incorporate or explicitly resolve",
                    suggested_agent="review-response agent on existing branch",
                )
            )
        elif pending:
            actions.append(
                Action(
                    lane="wait",
                    target=target,
                    reason=f"{pending} check(s) still pending",
                    suggested_agent="no coding agent; poll again later",
                )
            )
        elif pr.get("reviewDecision") == "APPROVED" and pr.get("mergeStateStatus") == "CLEAN":
            actions.append(
                Action(
                    lane="auto-merge",
                    target=target,
                    reason=(
                        "checks are green, comments are addressed, "
                        "and approval gate is satisfied"
                    ),
                    suggested_agent="enable squash auto-merge; no coding agent needed",
                )
            )
        elif pr.get("reviewDecision") in (None, "", "REVIEW_REQUIRED"):
            actions.append(
                Action(
                    lane="human-review",
                    target=target,
                    reason="checks are green but approval is still required",
                    suggested_agent="review agent can summarize, but human approves",
                )
            )

    ordered_target = active_ordered_target(issues)
    issue_pool = [ordered_target.issue] if ordered_target else []
    for issue in issue_pool:
        labels = label_names(issue)
        title = issue["title"].lower()
        already_has_pr = any(title[:30] and title[:30] in pr_title for pr_title in pr_titles)
        if already_has_pr:
            continue
        if "bug" in labels:
            actions.append(
                Action(
                    lane="bug",
                    target=f"Issue #{issue['number']}: {issue['title']}",
                    reason="earliest open ordered bug issue has no active PR",
                    suggested_agent="bug agent with regression-test-first loop",
                )
            )
        elif "feature" in labels or "enhancement" in labels:
            actions.append(
                Action(
                    lane="feature",
                    target=f"Issue #{issue['number']}: {issue['title']}",
                    reason="earliest open ordered feature issue has no active PR",
                    suggested_agent="feature agent on fresh branch from main",
                )
            )
        elif "roadmap" in labels:
            actions.append(
                Action(
                    lane="issue-decomposition",
                    target=f"Issue #{issue['number']}: {issue['title']}",
                    reason=(
                        "earliest open roadmap issue is too broad for a bounded "
                        "branch unless child issues exist"
                    ),
                    suggested_agent="create up to three small linked child implementation issues",
                )
            )
        else:
            actions.append(
                Action(
                    lane="feature",
                    target=f"Issue #{issue['number']}: {issue['title']}",
                    reason="earliest open ordered issue has no active PR",
                    suggested_agent="bounded implementation agent on fresh branch from main",
                )
            )

    if not actions:
        actions.append(
            Action(
                lane="wait",
                target="GitHub issue queue",
                reason="no open PR or issue needs immediate action",
                suggested_agent="no coding agent; poll again later",
            )
        )
    return actions


def print_section(title: str) -> None:
    print()
    print(f"## {title}")


def main() -> None:
    branch = run(["git", "branch", "--show-current"]).stdout.strip() or "(detached)"
    status = run(["git", "status", "--short", "--branch"]).stdout.strip()
    issues = gh_json(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "20",
            "--json",
            "number,title,labels,updatedAt,body",
        ]
    )
    prs = gh_json(
        [
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "20",
            "--json",
            "number,title,headRefName,labels,reviewDecision,mergeStateStatus,statusCheckRollup,updatedAt,body",
        ]
    )

    print("# SignalDesk Agent Heartbeat")
    print(f"Repo: {REPO}")
    print(f"Branch: {branch}")
    print("Status:")
    print(status)

    print_section("Roadmap snapshot")
    for heading in roadmap_snapshot():
        print(f"- {heading}")

    print_section("Open PRs")
    if not prs:
        print("- None")
    for pr in prs:
        passed, pending, failed = check_summary(pr.get("statusCheckRollup", []))
        check_text = f"checks=pass:{passed}/pending:{pending}/fail:{failed}"
        print(
            f"- PR #{pr['number']} {pr['title']} "
            f"branch={pr['headRefName']} review={pr.get('reviewDecision') or 'none'} "
            f"merge={pr.get('mergeStateStatus')} {check_text}"
        )
        for comment in issue_comments(pr["number"]):
            print(f"  - issue comment by {comment['author']}: {comment['body'][:160]!r}")
        for comment in pr_review_comments(pr["number"]):
            print(
                f"  - review comment by {comment['author']} on {comment['path']}: "
                f"{comment['body'][:160]!r}"
            )

    print_section("Open issues")
    if not issues:
        print("- None")
    for issue in issues:
        labels = ",".join(sorted(label_names(issue))) or "no-labels"
        print(f"- Issue #{issue['number']} {issue['title']} labels={labels}")
        for comment in issue_comments(issue["number"]):
            print(f"  - comment by {comment['author']}: {comment['body'][:160]!r}")

    print_section("Ordered target")
    ordered_target = active_ordered_target(issues)
    if ordered_target is None:
        print("- None")
    else:
        print(f"- {ordered_target.label}")
        print(
            "  selection: lowest open roadmap parent / issue number first; "
            "out-of-order PR service is limited to safety, CI, or review-response gates"
        )

    print_section("Suggested next loop actions")
    for index, action in enumerate(propose_actions(issues, prs), start=1):
        print(f"{index}. [{action.lane}] {action.target}")
        print(f"   reason: {action.reason}")
        print(f"   agent: {action.suggested_agent}")

    print_section("Loop rule")
    print(
        "The heartbeat only selects the next lane. Sub-agents work on bounded branches, "
        "comments/issues/PRs carry context, CI and review provide feedback, and the loop "
        "continues until checks are green and human approval is present."
    )


if __name__ == "__main__":
    main()
