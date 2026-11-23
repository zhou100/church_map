"""Deterministic auto-merge gate for zhou100/church_map.

Pure functions: no network, no GitHub calls. `classify()` judges the files and
diff of a PR against `.github/automerge-policy.yml`; `decide()` combines that
verdict with the Claude review and the PR's GitHub state into the final
`auto` / `needs_human` result. `automerge_gate.py` does the I/O.

CLI (offline replay):
    python .github/scripts/automerge_policy.py --files files.json
    python .github/scripts/automerge_policy.py --pr 86      # uses `gh api`

`files.json` is the GitHub "list pull request files" response: a list of
{filename, status, additions, deletions, patch?, previous_filename?}.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

AUTO = "auto"
NEEDS_HUMAN = "needs_human"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO_ROOT / ".github" / "automerge-policy.yml"


# ── policy loading ──────────────────────────────────────────────────────────

def load_policy(path: Path | str = DEFAULT_POLICY) -> dict:
    with open(path, encoding="utf-8") as fh:
        policy = yaml.safe_load(fh)
    if policy.get("version") != 1:
        raise ValueError(f"unsupported policy version: {policy.get('version')!r}")
    # Compile once; a bad regex should fail loudly, not silently match nothing.
    for rule in policy.get("protected", []):
        rule["_content_re"] = [re.compile(p) for p in rule.get("content", [])]
    return policy


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_to_regex(glob: str) -> re.Pattern:
    """`**` crosses '/', `*` and `?` do not. `**/x` also matches top-level x."""
    if glob in _GLOB_CACHE:
        return _GLOB_CACHE[glob]
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    pat = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[glob] = pat
    return pat


def matches_any(path: str, globs) -> bool:
    return any(glob_to_regex(g).match(path) for g in globs or [])


def changed_lines(patch: str | None):
    """Added/removed lines of a unified diff, without the +/- marker."""
    for line in (patch or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            yield line[1:]


# ── deterministic classification ────────────────────────────────────────────

@dataclass
class PolicyResult:
    verdict: str                                  # auto | needs_human
    reasons: list[str] = field(default_factory=list)
    # files that are neither docs/tests/style nor protected: they need the
    # review to confirm "small bug fix / copy edit" before auto-merge.
    code_files: list[str] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)
    changed_lines: int = 0

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reasons": self.reasons,
            "code_files": self.code_files,
            "categories": self.categories,
            "changed_lines": self.changed_lines,
        }


def classify(files: list[dict], policy: dict) -> PolicyResult:
    reasons: list[str] = []
    categories: dict[str, list[str]] = {}
    code_files: list[str] = []
    total = 0

    def hit(msg: str):
        if msg not in reasons:
            reasons.append(msg)

    if not files:
        hit("PR 没有可检查的文件改动")

    for f in files:
        path = f["filename"]
        status = f.get("status", "modified")
        total += int(f.get("additions", 0)) + int(f.get("deletions", 0))
        paths = [path] + ([f["previous_filename"]] if f.get("previous_filename") else [])

        if any(matches_any(p, policy.get("meta_paths")) for p in paths):
            hit(f"改了自动合并策略/流程本身: {path}")

        if status == "removed":
            hit(f"删除文件: {path}")
        elif status == "renamed":
            hit(f"重命名（旧路径被删除）: {f.get('previous_filename')} → {path}")

        patch = f.get("patch")
        has_diff = int(f.get("additions", 0)) + int(f.get("deletions", 0)) > 0
        if patch is None and has_diff and status != "removed":
            # GitHub omits the patch for binary or very large files; we cannot
            # content-scan what we cannot see.
            hit(f"diff 不可检查（二进制或过大）: {path}")

        scan = not matches_any(path, policy.get("content_scan_exempt"))
        protected_hit = False
        for rule in policy.get("protected", []):
            if any(matches_any(p, rule.get("paths")) for p in paths):
                hit(f"{rule['reason']}: {path}")
                protected_hit = True
                continue
            if scan and rule["_content_re"]:
                for line in changed_lines(patch):
                    m = next((r for r in rule["_content_re"] if r.search(line)), None)
                    if m:
                        snippet = m.search(line).group(0)
                        hit(f"{rule['reason']}: {path} 改动行含 `{snippet}`")
                        protected_hit = True
                        break

        cat = next(
            (name for name, globs in (policy.get("allowed") or {}).items()
             if matches_any(path, globs)),
            None,
        )
        if cat:
            categories.setdefault(cat, []).append(path)
        elif not protected_hit:
            categories.setdefault("code", []).append(path)
            code_files.append(path)

    limit = int(policy["max_changed_lines"])
    if total > limit:
        hit(f"改动 {total} 行 > {limit} 行上限")

    return PolicyResult(
        verdict=NEEDS_HUMAN if reasons else AUTO,
        reasons=reasons,
        code_files=code_files,
        categories=categories,
        changed_lines=total,
    )


# ── final decision ──────────────────────────────────────────────────────────

@dataclass
class Decision:
    verdict: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reasons": self.reasons}


def review_is_blocking(review: dict) -> bool:
    return bool(review.get("blocking")) or any(
        i.get("severity") == "blocking" for i in review.get("issues", [])
    )


def pr_blockers(pr: dict, policy: dict, required_checks: list[str]) -> list[str]:
    """Reasons from GitHub state alone (no diff, no review)."""
    reasons = []
    if pr.get("draft"):
        reasons.append("PR 是 draft")
    if pr.get("base") != policy["base_branch"]:
        reasons.append(f"目标分支不是 {policy['base_branch']}: {pr.get('base')}")
    if pr.get("cross_repository"):
        reasons.append("来自 fork 的 PR")
    if pr.get("author_association") not in policy["trusted_author_associations"]:
        reasons.append(f"作者权限 {pr.get('author_association')} 不在自动合并名单内")

    mergeable = pr.get("mergeable")
    if mergeable == "CONFLICTING":
        reasons.append("与目标分支有冲突")
    elif mergeable != "MERGEABLE":
        reasons.append(f"GitHub 还没算出能否合并（mergeable={mergeable}）")

    if not required_checks:
        reasons.append(
            f"{policy['base_branch']} 没有 required status checks，"
            "开启 auto-merge 会不等 CI 直接合并"
        )
    return reasons


def review_needed(policy_result: PolicyResult, pr: dict, policy: dict,
                  required_checks: list[str]) -> bool:
    """Only pay for a Claude review when it can still change the outcome:
    if the rules or GitHub state already force needs_human, it cannot."""
    if not policy["review"].get("skip_when_needs_human", True):
        return True
    return not policy_result.reasons and not pr_blockers(pr, policy, required_checks)


def decide(policy_result: PolicyResult, review: dict | None, pr: dict, policy: dict,
           *, required_checks: list[str]) -> Decision:
    """Combine every gate. `review` is None when the review did not run
    (skipped, failed, refused, too large); `pr` carries GitHub state (see
    automerge_gate.pr_state)."""
    reasons = list(policy_result.reasons) + pr_blockers(pr, policy, required_checks)

    if review is None:
        # Fail closed. When other reasons already block, the review was
        # skipped on purpose and repeating that here is noise.
        if not reasons:
            reasons.append("Claude 审查没有跑成（缺 key、失败、被拒或 diff 过大）")
    else:
        if review_is_blocking(review):
            reasons.append("Claude 审查报告了阻塞问题")
        allowed_kinds = policy["review_kinds_allowed_for_code"]
        if policy_result.code_files and review.get("change_kind") not in allowed_kinds:
            reasons.append(
                f"改了代码文件，但审查判定改动类型为 {review.get('change_kind')!r}，"
                f"不属于 {allowed_kinds}"
            )

    # de-dup, keep order
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return Decision(NEEDS_HUMAN if out else AUTO, out)


# ── CLI ─────────────────────────────────────────────────────────────────────

def fetch_pr_files(pr: int, repo: str | None = None) -> list[dict]:
    repo_part = repo or "{owner}/{repo}"
    out = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", f"repos/{repo_part}/pulls/{pr}/files?per_page=100"],
        check=True, capture_output=True, text=True,
    ).stdout
    pages = json.loads(out)
    return [f for page in pages for f in page]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--files", help="JSON file: GitHub PR files API response")
    src.add_argument("--pr", type=int, help="PR number to fetch with gh")
    ap.add_argument("--repo", help="owner/repo (default: current gh repo)")
    ap.add_argument("--policy", default=str(DEFAULT_POLICY))
    args = ap.parse_args(argv)

    policy = load_policy(args.policy)
    if args.files:
        files = json.loads(Path(args.files).read_text(encoding="utf-8"))
    else:
        files = fetch_pr_files(args.pr, args.repo)
    result = classify(files, policy)
    json.dump(result.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
