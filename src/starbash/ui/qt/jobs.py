"""Long-running operations executed on worker threads.

Each job constructs its **own** :class:`~starbash.app.Starbash`, so it owns a
private SQLite connection and can safely run off the GUI thread.  Detailed
progress is not pushed from here - the core publishes it on the event bus and
:class:`~starbash.ui.qt.bridge.EventBusBridge` forwards it to the GUI.

Jobs poll their :class:`~starbash.ui.qt.workers.CancelToken` between phases.
Cancellation is therefore *cooperative*: it takes effect at the next phase
boundary, not mid-recipe.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starbash.ui.qt.workers import CancelToken

__all__ = ["reindex_job", "process_job", "publish_job", "add_repo_job"]


def reindex_job(report: Callable[[Any], None], token: CancelToken) -> dict[str, Any]:
    """Re-index every configured repository."""
    from starbash.app import Starbash

    token.raise_if_cancelled()
    report("Re-indexing repositories...")
    with Starbash("gui.reindex") as sb:
        sb.reindex_repos()
    return {"message": "Re-index complete."}


def add_repo_job(
    report: Callable[[Any], None],
    token: CancelToken,
    path: str,
    kind: str | None = None,
) -> dict[str, Any]:
    """Add (and index) a local repository folder."""
    from starbash.app import Starbash

    token.raise_if_cancelled()
    report(f"Adding repository {path}...")
    with Starbash("gui.repo.add") as sb:
        sb.add_local_repo(path, repo_type=kind)
    return {"message": f"Added repository: {path}"}


def process_job(
    report: Callable[[Any], None],
    token: CancelToken,
    masters_only: bool = False,
) -> dict[str, Any]:
    """Run the automated processing pipeline (or just generate masters)."""
    import starbash
    from starbash.app import Starbash
    from starbash.processing import Processing

    token.raise_if_cancelled()
    if masters_only:
        starbash.process_masters = True
        report("Generating master calibration frames...")
    else:
        report("Auto-processing selected sessions...")

    # Bind before the `with`: `__exit__` can suppress exceptions, so the type
    # checker (correctly) can't prove the body ran.
    results: list[Any] = []
    with Starbash("gui.process") as sb, Processing(sb) as proc:
        results = proc.run_master_stages() if masters_only else proc.run_all_stages()

    succeeded = sum(1 for r in results if getattr(r, "success", None))
    failed = len(results) - succeeded
    return {
        "count": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "message": f"{len(results)} stage(s) run, {succeeded} succeeded, {failed} failed.",
    }


def publish_job(
    report: Callable[[Any], None],
    token: CancelToken,
    github_username: str | None = None,
) -> dict[str, Any]:
    """Generate the local Jekyll report site (no upload)."""
    from starbash.app import Starbash
    from starbash.publish.github import GitHubPublisher

    token.raise_if_cancelled()
    report("Generating report site...")
    site = ""
    with Starbash("gui.publish") as sb:
        site = str(GitHubPublisher(sb, github_username=github_username).publish())

    return {"site": site, "message": f"Report site generated at {site}"}
