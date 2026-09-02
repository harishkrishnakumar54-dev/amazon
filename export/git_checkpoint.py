import os
import sys
import subprocess
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("amazon_scraper")

def run_git_cmd(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a git command safely and return CompletedProcess."""
    return subprocess.run(
        cmd,
        cwd=cwd or os.getcwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

def ensure_git_config(repo_dir: str):
    """Ensure user.name and user.email are configured."""
    chk_name = run_git_cmd(["git", "config", "user.name"], cwd=repo_dir)
    if chk_name.returncode != 0 or not chk_name.stdout.strip():
        run_git_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=repo_dir)

    chk_email = run_git_cmd(["git", "config", "user.email"], cwd=repo_dir)
    if chk_email.returncode != 0 or not chk_email.stdout.strip():
        run_git_cmd(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=repo_dir)

def commit_and_push_checkpoint(
    category: str,
    files_to_commit: Optional[List[str]] = None,
    repo_dir: Optional[str] = None
) -> bool:
    """
    Safely commits and pushes scraper checkpoint files during execution.
    Never uses --force or reset --hard.
    """
    if files_to_commit is None:
        files_to_commit = [
            "output/Amazon_Seller_Master_Data.xlsx",
            "amazon_sellers.db",
            "output/progress.json"
        ]

    target_dir = repo_dir or os.getcwd()

    # Check if in a git repository
    chk_repo = run_git_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=target_dir)
    if chk_repo.returncode != 0 or chk_repo.stdout.strip() != "true":
        logger.debug(f"Not a git repository: {target_dir}. Skipping git checkpoint.")
        return False

    ensure_git_config(target_dir)

    # Filter to files that actually exist
    existing_files = [f for f in files_to_commit if (Path(target_dir) / f).exists()]
    if not existing_files:
        logger.warning("No checkpoint files exist to stage for commit.")
        return False

    # Stage files forcefully in case .gitignore matches any pattern
    add_cmd = ["git", "add", "-f"] + existing_files
    res_add = run_git_cmd(add_cmd, cwd=target_dir)
    if res_add.returncode != 0:
        logger.warning(f"git add failed: {res_add.stderr.strip()}")
        return False

    # Check if there are staged changes
    res_diff = run_git_cmd(["git", "diff", "--cached", "--quiet"], cwd=target_dir)
    if res_diff.returncode == 0:
        logger.info(f"No changes to commit for checkpoint '{category}'.")
        return True

    # Commit checkpoint
    commit_msg = f"Amazon scraper checkpoint: {category}"
    res_commit = run_git_cmd(["git", "commit", "-m", commit_msg], cwd=target_dir)
    if res_commit.returncode != 0:
        logger.warning(f"git commit failed: {res_commit.stderr.strip()}")
        return False

    logger.info(f"Git checkpoint committed: {commit_msg}")

    # Check if remote origin exists
    res_remote = run_git_cmd(["git", "remote", "get-url", "origin"], cwd=target_dir)
    if res_remote.returncode != 0 or not res_remote.stdout.strip():
        logger.info("No git remote origin configured. Checkpoint committed locally.")
        return True

    # Safely reconcile remote changes before push (no force, no hard reset)
    run_git_cmd(["git", "fetch", "origin", "main"], cwd=target_dir)
    # Attempt merge with preference for keeping our committed data
    run_git_cmd(["git", "merge", "origin/main", "--no-edit", "-X", "ours"], cwd=target_dir)

    # Push to origin
    res_push = run_git_cmd(["git", "push", "origin", "HEAD:main"], cwd=target_dir)
    if res_push.returncode == 0:
        logger.info(f"Git checkpoint successfully pushed to origin/main for '{category}'.")
        print(f"Git checkpoint pushed: {category}")
        return True
    else:
        logger.warning(f"git push failed (will retry next checkpoint): {res_push.stderr.strip()}")
        return False
