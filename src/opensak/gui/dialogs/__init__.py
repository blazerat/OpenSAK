"""Dialogs package."""

# Cap GUI progress updates so per-cache callbacks on large exports (thousands of
# caches) never flood the Qt event loop.
_MAX_PROGRESS_UPDATES = 200


def make_progress_cb(emit):
    """Return a throttled progress_cb(done, total) that forwards to *emit*.

    Emits at most ~200 updates plus the final one, keeping the progress bar
    smooth without swamping the event loop.
    """
    def cb(done: int, total: int) -> None:
        if total <= 0:
            return
        if done == total or done % max(1, total // _MAX_PROGRESS_UPDATES) == 0:
            emit(done, total)

    return cb
