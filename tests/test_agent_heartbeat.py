import importlib.util
import sys
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agent_heartbeat.py"
SPEC = importlib.util.spec_from_file_location("agent_heartbeat", SCRIPT_PATH)
assert SPEC is not None
agent_heartbeat = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["agent_heartbeat"] = agent_heartbeat
SPEC.loader.exec_module(agent_heartbeat)


def issue(number: int, title: str, labels: list[str], body: str = "") -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "labels": [{"name": label} for label in labels],
        "body": body,
    }


def pr(
    number: int,
    title: str,
    *,
    review_decision: str | None = None,
    merge_state: str = "CLEAN",
    closing_issue: int | None = None,
) -> dict[str, Any]:
    references = [] if closing_issue is None else [{"number": closing_issue}]
    return {
        "number": number,
        "title": title,
        "body": "",
        "reviewDecision": review_decision,
        "mergeStateStatus": merge_state,
        "statusCheckRollup": [
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
        "closingIssuesReferences": references,
    }


def test_ordered_targets_use_roadmap_parent_before_child_issue_number() -> None:
    issues = [
        issue(67, "Restore ordered issue execution", ["agent-loop"], "Parent: #61"),
        issue(44, "Roadmap 1: Engineering Foundation", ["roadmap"]),
        issue(47, "Roadmap 4: Technical Analysis Engine", ["roadmap", "feature"]),
    ]

    ordered = agent_heartbeat.ordered_issue_targets(issues)

    assert [target.issue_number for target in ordered] == [44, 47, 67]
    assert ordered[-1].parent_number == 61


def test_active_ordered_target_is_lowest_open_roadmap_parent() -> None:
    issues = [
        issue(67, "Restore ordered issue execution", ["agent-loop"], "Parent: #61"),
        issue(44, "Roadmap 1: Engineering Foundation", ["roadmap"]),
    ]

    target = agent_heartbeat.active_ordered_target(issues)

    assert target is not None
    assert target.issue_number == 44


def test_propose_actions_decomposes_earliest_roadmap_issue_before_later_features() -> None:
    issues = [
        issue(67, "Restore ordered issue execution", ["agent-loop"], "Parent: #61"),
        issue(44, "Roadmap 1: Engineering Foundation", ["roadmap", "safety"]),
        issue(47, "Roadmap 4: Technical Analysis Engine", ["feature", "roadmap"]),
    ]

    actions = agent_heartbeat.propose_actions(issues, prs=[])

    assert actions[0].lane == "issue-decomposition"
    assert actions[0].target == "Issue #44: Roadmap 1: Engineering Foundation"


def test_propose_actions_services_active_target_pr_before_waiting(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_heartbeat, "issue_comments", lambda _number: [])
    monkeypatch.setattr(agent_heartbeat, "pr_review_comments", lambda _number: [])
    issues = [
        issue(67, "Restore ordered issue execution", ["agent-loop"], "Parent: #61"),
    ]
    prs = [
        pr(
            73,
            "Restore ordered heartbeat issue selection",
            review_decision="CHANGES_REQUESTED",
            merge_state="BLOCKED",
            closing_issue=67,
        )
    ]

    actions = agent_heartbeat.propose_actions(issues, prs=prs)

    assert actions[0].lane == "respond-to-review"
    assert actions[0].target == "PR #73: Restore ordered heartbeat issue selection"
    assert "requiring safety-lane service" in actions[0].reason
