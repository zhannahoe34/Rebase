"""GitHub client against a fake HTTP transport; push() against real bare git repos."""

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from rebase_agent.github_api import (
    APPROVED_LABEL,
    GitHub,
    GitHubError,
    PushRejected,
    PushTarget,
    push,
)
from rebase_agent.resolver.agent import prepare_workdir


def client(routes: dict[str, object]) -> GitHub:
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        body = routes[key]
        if isinstance(body, httpx.Response):
            return body
        if callable(body):
            return body(request)
        return httpx.Response(200, json=body)

    return GitHub("o/r", "tok-SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))


def review(user: str, state: str) -> dict:
    return {"user": {"login": user}, "state": state}


PR = {"number": 5, "labels": [], "head": {"ref": "pr/x"}}


@pytest.mark.parametrize(
    "reviews,labels,expected",
    [
        ([], [], (False, "not approved")),
        ([review("a", "APPROVED")], [], (True, "approved review")),
        ([review("a", "APPROVED"), review("b", "CHANGES_REQUESTED")], [], (False, "changes requested")),
        ([review("a", "CHANGES_REQUESTED"), review("a", "APPROVED")], [], (True, "approved review")),
        ([review("a", "APPROVED"), review("a", "DISMISSED")], [], (False, "not approved")),
        ([review("a", "COMMENTED")], [], (False, "not approved")),
        ([], [{"name": APPROVED_LABEL}], (True, f"label {APPROVED_LABEL}")),
    ],
)  # fmt: skip
def test_eligibility(reviews, labels, expected):
    gh = client({"GET /repos/o/r/pulls/5/reviews": reviews})
    assert gh.eligibility({**PR, "labels": labels}) == expected


def test_remove_label_encodes_the_name():
    seen = []

    def delete(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json=[])

    client({"DELETE /repos/o/r/issues/5/labels/rebase:approved": delete}).remove_label(
        5, APPROVED_LABEL
    )
    assert seen == ["/repos/o/r/issues/5/labels/rebase%3Aapproved"]


def test_remove_label_ignores_a_label_that_is_not_there():
    gh = client({"DELETE /repos/o/r/issues/5/labels/rebase:approved": httpx.Response(404)})
    gh.remove_label(5, APPROVED_LABEL)  # no raise


def test_remove_label_surfaces_other_errors():
    gh = client({"DELETE /repos/o/r/issues/5/labels/rebase:approved": httpx.Response(403)})
    with pytest.raises(GitHubError):
        gh.remove_label(5, APPROVED_LABEL)


def test_open_prs_paginates_and_filters_by_base():
    seen = []

    def pulls(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[{"number": i} for i in range(100 if page == 1 else 3)])

    gh = client({"GET /repos/o/r/pulls": pulls})
    assert len(gh.open_prs(base="base/trivial")) == 103
    assert seen[0]["base"] == "base/trivial" and seen[0]["state"] == "open"


def test_errors_scrub_the_token():
    gh = client({"POST /repos/o/r/issues/5/comments": httpx.Response(401, text="bad tok-SECRET")})
    with pytest.raises(GitHubError) as e:
        gh.post_comment(5, "hi")
    assert "tok-SECRET" not in str(e.value) and "***" in str(e.value)


def test_post_comment_sends_body():
    def comment(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"body": "hello"}
        assert request.headers["Authorization"] == "Bearer tok-SECRET"
        return httpx.Response(201, json={"html_url": "https://x/1"})

    assert (
        client({"POST /repos/o/r/issues/5/comments": comment}).post_comment(5, "hello")
        == "https://x/1"
    )


def _bare_remote(tmp_path: Path, repo: Path, branch: str, sha: str) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "push", "-q", str(remote), f"{sha}:refs/heads/{branch}"],
        check=True,
    )
    return remote


def _remote_sha(remote: Path, branch: str) -> str:
    return subprocess.run(
        ["git", "-C", str(remote), "rev-parse", branch], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_push_with_lease(scenario_repos, tmp_path):
    refs = scenario_repos["trivial"]
    workdir, onto, head = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    remote = _bare_remote(tmp_path, Path(refs.repo), "pr/trivial", head)
    subprocess.run(["git", "-C", str(workdir), "rebase", "-q", onto], check=True)
    new = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    push(workdir, PushTarget(url=str(remote), branch="pr/trivial", expected_sha=head))
    assert _remote_sha(remote, "pr/trivial") == new


def test_push_rejected_when_branch_moved(scenario_repos, tmp_path):
    refs = scenario_repos["trivial"]
    workdir, onto, head = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    remote = _bare_remote(tmp_path, Path(refs.repo), "pr/trivial", onto)  # someone else's push
    subprocess.run(["git", "-C", str(workdir), "rebase", "-q", onto], check=True)
    with pytest.raises(PushRejected):
        push(workdir, PushTarget(url=str(remote), branch="pr/trivial", expected_sha=head))
    assert _remote_sha(remote, "pr/trivial") == onto
