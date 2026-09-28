"""GitHub REST access (httpx) for the sandbox repo: PRs, eligibility, comments, pushes.

Token: SANDBOX_REPO_TOKEN (a PAT or App token), never the Actions GITHUB_TOKEN, whose
pushes don't retrigger CI. The token only ever appears in request headers and in the
push URL handed to git; it is scrubbed from any error text we raise.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

API = "https://api.github.com"
TOKEN_ENV = "SANDBOX_REPO_TOKEN"
REPO_ENV = "SANDBOX_REPO"
DEFAULT_REPO = "zhannahoe34/RebaseSandbox"
# Q2b fallback: GitHub blocks self-approval, so a label also counts as approval.
APPROVED_LABEL = "rebase:approved"


class GitHubError(RuntimeError):
    pass


def sandbox_repo() -> str:
    return os.environ.get(REPO_ENV) or DEFAULT_REPO


def token() -> str:
    value = os.environ.get(TOKEN_ENV)
    if not value:
        raise GitHubError(f"{TOKEN_ENV} is not set")
    return value


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


class GitHub:
    def __init__(self, repo: str, token: str, *, client: httpx.Client | None = None) -> None:
        self.repo = repo
        self._token = token
        self._client = client or httpx.Client(timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, f"{API}{path}", headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise GitHubError(
                f"{method} {path}: HTTP {resp.status_code}: {_scrub(resp.text[:300], self._token)}"
            )
        return resp.json() if resp.content else None

    def _paged(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            batch = self._request(
                "GET", path, params={**(params or {}), "per_page": 100, "page": page}
            )
            items += batch
            if len(batch) < 100:
                return items
            page += 1

    # --- pull requests ---------------------------------------------------------------
    def open_prs(self, base: str | None = None, head: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"state": "open"}
        if base:
            params["base"] = base
        if head:
            params["head"] = f"{self.repo.split('/')[0]}:{head}"
        return self._paged(f"/repos/{self.repo}/pulls", params)

    def get_pr(self, number: int) -> dict:
        return self._request("GET", f"/repos/{self.repo}/pulls/{number}")

    def create_pr(self, head: str, base: str, title: str, body: str) -> dict:
        return self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        )

    def update_pr(self, number: int, **fields: str) -> dict:
        return self._request("PATCH", f"/repos/{self.repo}/pulls/{number}", json=fields)

    def close_pr(self, number: int) -> None:
        self._request("PATCH", f"/repos/{self.repo}/pulls/{number}", json={"state": "closed"})

    def add_label(self, number: int, label: str) -> None:
        self._request(
            "POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": [label]}
        )

    def remove_label(self, number: int, label: str) -> None:
        """No-op when the PR doesn't carry the label."""
        try:
            self._request(
                "DELETE", f"/repos/{self.repo}/issues/{number}/labels/{quote(label, safe='')}"
            )
        except GitHubError as e:
            if "HTTP 404" not in str(e):
                raise

    def eligibility(self, pr: dict) -> tuple[bool, str]:
        """Eligible = the approval label, or an APPROVED review with no reviewer's latest
        review requesting changes."""
        if any(label["name"] == APPROVED_LABEL for label in pr.get("labels", [])):
            return True, f"label {APPROVED_LABEL}"
        latest: dict[str, str] = {}
        for review in self._paged(f"/repos/{self.repo}/pulls/{pr['number']}/reviews"):
            if review["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                latest[review["user"]["login"]] = review["state"]
        if "CHANGES_REQUESTED" in latest.values():
            return False, "changes requested"
        if "APPROVED" in latest.values():
            return True, "approved review"
        return False, "not approved"

    def post_comment(self, number: int, body: str) -> str:
        data = self._request(
            "POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body}
        )
        return data["html_url"]

    def push_url(self) -> str:
        return f"https://x-access-token:{self._token}@github.com/{self.repo}.git"


@dataclass(frozen=True)
class PushTarget:
    """Where run_pr pushes: `branch` on `url`, only if it is still at `expected_sha`."""

    url: str
    branch: str
    expected_sha: str


class PushRejected(RuntimeError):
    pass


def push(workdir: Path, target: PushTarget) -> None:
    """git push --force-with-lease from the throwaway clone. The URL goes on the command
    line only (the clone keeps no remote); it's scrubbed from any error."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(workdir),
            "push",
            "--porcelain",
            f"--force-with-lease=refs/heads/{target.branch}:{target.expected_sha}",
            target.url,
            f"HEAD:refs/heads/{target.branch}",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        check=False,
    )
    if proc.returncode != 0:
        secret = target.url.split("@", 1)[0] if "@" in target.url else ""
        detail = _scrub(proc.stdout + proc.stderr, secret).strip()[-500:]
        if "stale info" in detail or "[rejected]" in detail:
            raise PushRejected(f"branch {target.branch} moved since it was checked: {detail}")
        raise GitHubError(f"push failed: {detail}")
