# Archive Branch

The pipeline commits all intermediate artefacts to a dedicated git branch (default: `data`) to keep `main` clean. This replaces the previous Google Drive upload for IoC files.

Source: `src/sinks/git_archive.py`.

## Why a separate branch

- Daily runs produce fetch JSON (~100 KB), analysis JSON (~200 KB), and IoC txt files — committing to `main` would pollute its history and inflate repo size.
- A separate branch accumulates a clean, browseable audit trail organised by source and month.
- GitHub raw URLs for committed files are stable and can be embedded in Google Sheet cells (column H).

## Worktree mechanics

On the first call to `commit_files` when `GIT_ARCHIVE_BRANCH` is set:

1. **Branch creation** (if the branch doesn't exist): creates an empty orphan commit via git plumbing (`git hash-object -t tree` + `git commit-tree`) and creates the branch pointing at it. No empty commit pollutes `main`.
2. **Worktree setup**: calls `git worktree add /tmp/security-info-archive {branch}`. The worktree shares the main repo's `.git` directory (credentials, remotes) but has an independent working tree.
3. On subsequent calls the worktree is reused (detected via `git worktree list --porcelain`).

Each `commit_files` call:
- Copies files into the worktree at the target path.
- Runs `git add -A` then `git commit` with bot identity (`GIT_AUTHOR_NAME=security-info-bot`).
- If `GIT_ARCHIVE_AUTO_PUSH=true`, runs `git push origin {branch}` from the worktree immediately after.

## ⚠️ The worktree can be stale — never read state from it

`_ensure_worktree` guarantees *a* worktree, **not** a worktree of the current `origin/{branch}`. Step 1 only fetches when the local branch is **absent** (`_branch_exists` → `_fetch_remote_branch`); when a local `{branch}` already exists it is used **as-is, with no fetch**. `Dockerfile` is `COPY . /app` and both `.dockerignore` and `.gcloudignore` deliberately keep `.git`, so **a local archive branch left in the checkout you build from gets baked into the image**, and every container then works from that frozen snapshot.

Writing tolerates this: the archive only appends uniquely-named files, and `_push` rebases, so a stale base still lands correctly. **Reading does not.** A stale worktree reports every newer file as absent — indistinguishable from "not written yet".

Consequences:
- `read_archive_file` therefore bypasses the worktree entirely and reads `origin/{branch}` (`git ls-remote --exit-code` → `git fetch` → `git show FETCH_HEAD:{path}`). It returns `None` only for "branch disabled / remote branch absent / file not on the branch", and **raises** when the remote is unreachable — so a caller keeping state on the branch can tell "no state yet" from "could not read state". Reporting the latter as the former silently resets any state machine (this is how the TWCERT staleness alert lost its quiet streak; see `configuration.md`).
- **Do not leave a local `data` branch in a checkout used to build images.** `git branch -D data` before building; `origin/data` holds the full history and the branch has no local value.

## Directory layout in the archive branch

```
twcert/
  2026-05/
    twcert_2026-05-01_20260527_170653.json    ← Stage 1 fetch output
    analysis_twcert_20260527_174915.json      ← Stage 2 analysis output
    ioc_TWISAC-202605-0025.txt                ← Stage 3 IoC txt
cisa_kev/
  2026-05/
    cisa_kev_2026-05-27_20260527_*.json
    analysis_cisa_kev_*.json
```

The month directory is derived from `--since` (or today TW+8 as fallback). IoC files use the `IntelItem.publish_date` month.

## IoC URL backfill into Sheet

After committing an IoC file, `ioc_file_url(filename, archive_dir)` constructs a GitHub raw URL:

```
https://github.com/{owner}/{repo}/raw/{branch}/{archive_dir}/{filename}
```

`_github_base()` parses the `origin` remote URL:
- HTTPS: `https://github.com/owner/repo.git` → `https://github.com/owner/repo`
- SSH: `git@github.com:owner/repo.git` → `https://github.com/owner/repo`
- Any other host → returns `None` (URL backfill silently skipped)

The URL is appended to `AnalysisResult.recommendation` as `\n\nIoC 清單：{url}` before writing to Sheet column H. The URL is deterministic — it does not depend on push timing, so it is recorded in the Sheet even if `GIT_ARCHIVE_AUTO_PUSH=false` and the push happens later.

## No-op conditions

`commit_files` and `ioc_file_url` are silent no-ops when:
- `GIT_ARCHIVE_BRANCH` is empty (not set or set to `""`).
- All supplied file paths are missing (files that failed to write).
- The worktree detects no changed files after copying (duplicate content).
