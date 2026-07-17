from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from src.config import GIT_ARCHIVE_AUTO_PUSH, GIT_ARCHIVE_BRANCH
from src.utils.logging import log

_WORKTREE_DIR = Path(os.environ.get("GIT_ARCHIVE_WORKTREE_DIR", "/tmp/security-info-archive"))
_github_base_url_cache: str | None | bool = False  # False = not yet fetched

_GIT_BOT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "security-info-bot",
    "GIT_AUTHOR_EMAIL": "bot@local",
    "GIT_COMMITTER_NAME": "security-info-bot",
    "GIT_COMMITTER_EMAIL": "bot@local",
}


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(out)


def _worktree_linked(wt: Path) -> bool:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return str(wt) in out


def _branch_exists(branch: str, cwd: Path) -> bool:
    r = subprocess.run(
        ["git", "show-ref", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        cwd=cwd,
    )
    return r.returncode == 0


def _fetch_remote_branch(branch: str, cwd: Path) -> bool:
    """Fetch a remote branch and return True if it now exists as origin/<branch>."""
    r = subprocess.run(
        ["git", "fetch", "origin", branch],
        capture_output=True,
        cwd=cwd,
    )
    return r.returncode == 0


def _ensure_worktree() -> Path:
    repo = _repo_root()
    wt = _WORKTREE_DIR

    if _worktree_linked(wt):
        return wt

    if wt.exists():
        shutil.rmtree(wt)

    if not _branch_exists(GIT_ARCHIVE_BRANCH, repo):
        # In CI the repo is a fresh clone and only 'main' is fetched, so the
        # local archive branch never exists even when remote already does.
        # Fetch from remote first; only fabricate an orphan root when the
        # remote also has no such branch (true first-ever run).
        if _fetch_remote_branch(GIT_ARCHIVE_BRANCH, repo):
            subprocess.run(
                ["git", "branch", GIT_ARCHIVE_BRANCH, f"origin/{GIT_ARCHIVE_BRANCH}"],
                cwd=repo,
                check=True,
            )
            log.info("git_archive: created branch '%s' from remote", GIT_ARCHIVE_BRANCH)
        else:
            empty_tree = (
                subprocess.run(
                    ["git", "hash-object", "-t", "tree", "--stdin"],
                    input=b"",
                    capture_output=True,
                    check=True,
                    cwd=repo,
                )
                .stdout.decode()
                .strip()
            )
            msg = f"init: {GIT_ARCHIVE_BRANCH} archive branch"
            commit = subprocess.run(
                ["git", "commit-tree", empty_tree, "-m", msg],
                capture_output=True,
                text=True,
                check=True,
                cwd=repo,
                env=_GIT_BOT_ENV,
            ).stdout.strip()
            subprocess.run(["git", "branch", GIT_ARCHIVE_BRANCH, commit], cwd=repo, check=True)
            log.info("git_archive: created branch '%s'", GIT_ARCHIVE_BRANCH)

    subprocess.run(
        ["git", "worktree", "add", str(wt), GIT_ARCHIVE_BRANCH],
        cwd=repo,
        check=True,
    )
    log.info("git_archive: worktree ready at %s", wt)
    return wt


def read_archive_file(relpath: str) -> str | None:
    """Return the text of relpath on the archive branch as it exists on origin.

    Reads origin directly instead of the worktree: _ensure_worktree reuses a
    pre-existing local branch *without fetching*, so a stale branch baked into a
    container image (the Dockerfile COPYs .git) would report every file as absent.
    Archiving tolerates that — it only appends uniquely-named files and rebases on
    push — but a caller that reads state back cannot.

    Returns None only when there is genuinely nothing to read: the archive branch
    is disabled, the remote branch does not exist yet, or the file is not on it.
    Raises when the remote cannot be reached, so that callers keeping state on the
    branch can tell "no state yet" from "could not read state".
    """
    if not GIT_ARCHIVE_BRANCH:
        return None

    repo = _repo_root()
    # --exit-code distinguishes "remote has no such branch" (2) from a transport
    # failure (anything else); plain `git fetch` collapses both into non-zero.
    ls = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", GIT_ARCHIVE_BRANCH],
        capture_output=True,
        cwd=repo,
    )
    if ls.returncode == 2:
        return None
    if ls.returncode != 0:
        raise RuntimeError(
            f"git_archive: cannot reach origin to read {relpath}: "
            f"{ls.stderr.decode(errors='replace').strip()}"
        )

    fetch = subprocess.run(
        ["git", "fetch", "origin", GIT_ARCHIVE_BRANCH],
        capture_output=True,
        cwd=repo,
    )
    if fetch.returncode != 0:
        raise RuntimeError(
            f"git_archive: failed to fetch '{GIT_ARCHIVE_BRANCH}' to read {relpath}: "
            f"{fetch.stderr.decode(errors='replace').strip()}"
        )

    # FETCH_HEAD is what we just fetched, independent of any stale local branch.
    if (
        subprocess.run(
            ["git", "cat-file", "-e", f"FETCH_HEAD:{relpath}"],
            capture_output=True,
            cwd=repo,
        ).returncode
        != 0
    ):
        return None
    blob = subprocess.run(
        ["git", "show", f"FETCH_HEAD:{relpath}"],
        capture_output=True,
        check=True,
        cwd=repo,
    )
    return blob.stdout.decode("utf-8")


def commit_files(
    files: list[Path],
    message: str,
    archive_dir: str | Path | None = None,
) -> None:
    """Commit files to the archive branch.

    When archive_dir is given, all files land in that directory inside the
    worktree (e.g. 'twcert/2026-05').  Otherwise, files under the repo root
    preserve their relative path; files outside go to 'ioc/'.
    No-ops when GIT_ARCHIVE_BRANCH is empty.
    """
    if not GIT_ARCHIVE_BRANCH:
        return

    existing = [f for f in files if f and f.exists()]
    if not existing:
        return

    wt = _ensure_worktree()
    repo = _repo_root()

    for src in existing:
        if archive_dir is not None:
            rel = Path(archive_dir) / src.name
        else:
            try:
                rel = src.relative_to(repo)
            except ValueError:
                rel = Path("ioc") / src.name
        dst = wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=wt,
    ).stdout.strip()
    if not status:
        return

    subprocess.run(
        ["git", "commit", "--no-verify", "-m", message], cwd=wt, env=_GIT_BOT_ENV, check=True
    )
    log.info("git_archive: committed %d file(s) to '%s'", len(existing), GIT_ARCHIVE_BRANCH)

    if GIT_ARCHIVE_AUTO_PUSH:
        _push()


def _github_base() -> str | None:
    """Return 'https://github.com/owner/repo' parsed from origin, or None."""
    global _github_base_url_cache
    if _github_base_url_cache is not False:
        return _github_base_url_cache  # type: ignore[return-value]
    try:
        raw = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        _github_base_url_cache = None
        return None

    if raw.startswith("https://github.com/"):
        _github_base_url_cache = raw.removesuffix(".git")
    elif raw.startswith("git@github.com:"):
        path = raw.removeprefix("git@github.com:").removesuffix(".git")
        _github_base_url_cache = f"https://github.com/{path}"
    else:
        _github_base_url_cache = None
    return _github_base_url_cache


def ioc_file_url(filename: str, archive_dir: str | Path) -> str | None:
    """Return the GitHub raw URL for a committed IoC file, or None if unavailable."""
    if not GIT_ARCHIVE_BRANCH:
        return None
    base = _github_base()
    if not base:
        return None
    return f"{base}/raw/{GIT_ARCHIVE_BRANCH}/{archive_dir}/{filename}"


def _push() -> None:
    wt = _WORKTREE_DIR
    if not wt.exists():
        return
    # Rebase on remote before pushing to handle concurrent CI runs.
    # fetch returns non-zero when remote branch doesn't exist yet (first push) — skip rebase then.
    fetch = subprocess.run(
        ["git", "fetch", "origin", GIT_ARCHIVE_BRANCH],
        cwd=wt,
        capture_output=True,
    )
    if fetch.returncode == 0:
        subprocess.run(
            ["git", "rebase", f"origin/{GIT_ARCHIVE_BRANCH}"],
            cwd=wt,
            check=True,
            capture_output=True,
        )
    subprocess.run(["git", "push", "origin", GIT_ARCHIVE_BRANCH], cwd=wt, check=True)
    log.info("git_archive: pushed '%s' to origin", GIT_ARCHIVE_BRANCH)
