"""Workflow driver for the auto-merge gate.

Runs from the BASE branch under pull_request_target. It never checks out or
executes PR code: it reads the PR through the GitHub API, judges it with
automerge_policy.classify(), asks Claude for a review, combines both with
decide(), then posts one sticky comment and either arms GitHub auto-merge
(squash, pinned to the reviewed head SHA) or labels the PR needs-review.

    python .github/scripts/automerge_gate.py --pr 123            # live
    python .github/scripts/automerge_gate.py --pr 123 --dry-run  # print only

Every run first disarms any existing auto-merge, so a push that turns an auto
PR into a needs_human PR cannot ride an earlier approval.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import automerge_policy as ap  # noqa: E402
import automerge_review as ar  # noqa: E402

MARKER = "<!-- automerge-gate -->"


def gh(*args: str, input: str | None = None, check: bool = True) -> str:
    res = subprocess.run(["gh", *args], input=input, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''} failed: {res.stderr.strip()[:300]}")
    return res.stdout


def gh_json(*args: str):
    return json.loads(gh(*args))


def pr_state(repo: str, number: int) -> dict:
    rest = gh_json("api", f"repos/{repo}/pulls/{number}")
    # mergeable is computed lazily; GraphQL reports UNKNOWN until it is ready.
    for attempt in range(6):
        view = gh_json("pr", "view", str(number), "--repo", repo, "--json",
                       "state,mergeable,headRefOid,isDraft,baseRefName,isCrossRepository,autoMergeRequest")
        if view["mergeable"] != "UNKNOWN" or view["state"] != "OPEN":
            break
        time.sleep(5 * (attempt + 1))
    return {
        "number": number,
        "title": rest["title"],
        "body": rest.get("body") or "",
        "head_sha": view["headRefOid"],
        "draft": view["isDraft"],
        "base": view["baseRefName"],
        "cross_repository": view["isCrossRepository"],
        "author_association": rest.get("author_association"),
        "mergeable": view["mergeable"],
        "auto_merge_armed": view["autoMergeRequest"] is not None,
    }


def required_checks(repo: str, branch: str) -> list[str]:
    """Status checks GitHub enforces on `branch`, from rulesets and classic
    branch protection. Empty means auto-merge would not wait for CI."""
    contexts: list[str] = []
    try:
        for rule in gh_json("api", f"repos/{repo}/rules/branches/{branch}"):
            if rule.get("type") == "required_status_checks":
                for c in rule.get("parameters", {}).get("required_status_checks", []):
                    contexts.append(c["context"])
    except RuntimeError:
        pass
    try:
        prot = gh_json("api", f"repos/{repo}/branches/{branch}/protection/required_status_checks")
        contexts += prot.get("contexts", [])
    except RuntimeError:
        pass  # 404 = not protected, or token cannot read it
    return sorted(set(contexts))


def render_comment(pr: dict, result: ap.PolicyResult, review: dict | None, note: str,
                   decision: ap.Decision, checks: list[str], armed: str) -> str:
    ok = decision.verdict == ap.AUTO
    lines = [
        MARKER,
        f"### 自动合并判定：{'✅ auto' if ok else '⛔ needs_human'}",
        "",
        f"head `{pr['head_sha'][:7]}` · 改动 {result.changed_lines} 行 · "
        + " · ".join(f"{k}: {len(v)}" for k, v in result.categories.items()),
        "",
    ]
    if ok:
        lines.append(armed)
    else:
        lines.append("**需要人工审查，原因：**")
        lines += [f"- {r}" for r in decision.reasons]
        if armed:
            lines += ["", armed]
    lines += ["", "**Claude 审查**"]
    if review is None:
        lines.append(f"- 未完成：{note}")
    else:
        blocking = ap.review_is_blocking(review)
        lines.append(f"- 结论：{'有阻塞问题' if blocking else '无阻塞问题'} · 改动类型 `{review['change_kind']}` · {note}")
        lines.append(f"- {review['summary']}")
        for i in review.get("issues", []):
            loc = f"`{i['file']}" + (f":{i['line']}`" if i.get("line") else "`")
            tag = "🛑 blocking" if i["severity"] == "blocking" else "💬"
            lines.append(f"  - {tag} {loc} {i['description']}")
    lines += [
        "",
        f"<sub>规则见 `.github/automerge-policy.yml`；required checks: "
        f"{', '.join(f'`{c}`' for c in checks) or '无'}。每次 push 都会重新判定。</sub>",
    ]
    return "\n".join(lines)


def upsert_comment(repo: str, number: int, body: str) -> None:
    pages = json.loads(gh("api", "--paginate", "--slurp",
                          f"repos/{repo}/issues/{number}/comments?per_page=100"))
    mine = [c for page in pages for c in page
            if c.get("user", {}).get("login") == "github-actions[bot]" and MARKER in (c.get("body") or "")]
    payload = json.dumps({"body": body})
    if mine:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{mine[-1]['id']}", "--input", "-", input=payload)
    else:
        gh("api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-", input=payload)


def set_label(repo: str, number: int, label: str, on: bool) -> None:
    if on:
        gh("label", "create", label, "--repo", repo, "--color", "B60205",
           "--description", "Auto-merge gate: needs a human review", check=False)
        gh("pr", "edit", str(number), "--repo", repo, "--add-label", label)
    else:
        gh("pr", "edit", str(number), "--repo", repo, "--remove-label", label, check=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    p.add_argument("--policy", default=str(ap.DEFAULT_POLICY))
    p.add_argument("--dry-run", action="store_true", help="print the comment; change nothing")
    p.add_argument("--no-review", action="store_true", help="skip the Claude call")
    args = p.parse_args(argv)
    if not args.repo:
        p.error("--repo or GITHUB_REPOSITORY is required")

    policy = ap.load_policy(args.policy)
    pr = pr_state(args.repo, args.pr)

    if pr["auto_merge_armed"] and not args.dry_run:
        gh("pr", "merge", str(args.pr), "--repo", args.repo, "--disable-auto", check=False)

    files = ap.fetch_pr_files(args.pr, args.repo)
    result = ap.classify(files, policy)

    if args.no_review:
        review, note = None, "本次运行跳过了审查（--no-review）"
    else:
        review, note = ar.review_pr(pr["title"], pr["body"], files, policy)

    checks = required_checks(args.repo, policy["base_branch"])
    decision = ap.decide(result, review, pr, policy, required_checks=checks)

    armed = ""
    if decision.verdict == ap.AUTO and not args.dry_run:
        res = subprocess.run(
            ["gh", "pr", "merge", str(args.pr), "--repo", args.repo, "--auto",
             f"--{policy['merge_method']}", "--match-head-commit", pr["head_sha"]],
            capture_output=True, text=True,
        )
        if res.returncode == 0:
            armed = (f"已开启 auto-merge（{policy['merge_method']}，锁定 `{pr['head_sha'][:7]}`），"
                     "required checks 全部通过后由 GitHub 合并。")
        else:
            decision = ap.Decision(ap.NEEDS_HUMAN, [f"开启 auto-merge 失败：{res.stderr.strip()[:200]}"])
    elif decision.verdict == ap.AUTO:
        armed = "（dry run：不会开启 auto-merge）"

    body = render_comment(pr, result, review, note, decision, checks, armed)
    # Public log: verdict and counts only.
    print(json.dumps({"pr": args.pr, "head": pr["head_sha"][:7], "verdict": decision.verdict,
                      "reasons": len(decision.reasons), "changed_lines": result.changed_lines,
                      "review": None if review is None else review["change_kind"]}))
    if args.dry_run:
        print(body)
        return 0

    upsert_comment(args.repo, args.pr, body)
    set_label(args.repo, args.pr, policy["needs_human_label"], decision.verdict != ap.AUTO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
