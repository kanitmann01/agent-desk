"""Shadow copying: never parse the live workbook.

Desktop Excel holds an exclusive lock shape on open workbooks (the ~$
owner file plus deny-write sharing), so the poll copies the workbook to a
temp shadow file first, with a short retry for the moments Excel is mid-
save, and only ever parses the copy (research A9.2 rule 3). A persistent
PermissionError means the workbook is open: that is the amber state, not
an error dump.
"""

import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from agentdesk.excel.core import WorkbookLocked, WorkbookUnreadable

SHADOW_DIRNAME = "agentdesk-shadow"


def copy_to_shadow(
    path: str,
    workdir: str | Path | None = None,
    retries: int = 3,
    delay: float = 0.15,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Copy the workbook to the shadow dir; return the copy's path.

    A file that is gone is unreadable; a file that stays locked through
    every retry is the designed locked state the widget recovers from.
    """
    src = Path(path)
    if not src.is_file():
        raise WorkbookUnreadable(f"{src.name} is not there anymore")
    shadow_dir = Path(workdir) / SHADOW_DIRNAME if workdir else Path(tempfile.gettempdir()) / SHADOW_DIRNAME
    shadow_dir.mkdir(parents=True, exist_ok=True)
    # One destination per copy, not per basename: two watches on
    # same-named workbooks must never read each other's half-written
    # copies. Nothing outlives the poll's parse (the watcher removes it).
    dest = shadow_dir / f"{uuid.uuid4().hex[:12]}-{src.name}"
    last_error: PermissionError | None = None
    for _attempt in range(retries):
        try:
            # copyfile, not copy2: the copy must not inherit the source's
            # read-only attribute, or the next poll cannot overwrite it.
            shutil.copyfile(src, dest)
            return dest
        except PermissionError as exc:
            last_error = exc
            sleep(delay)
    raise WorkbookLocked(f"{src.name} is open in Excel right now") from last_error


def remove_shadow(path: str | Path) -> None:
    """Remove a shadow copy after its parse, so copies never accumulate.

    Only a file inside a shadow dir is ever removed: the poll must not be
    able to delete anything the shadow module did not create (tests and
    probes hand the watcher plain paths). A missing or unremovable copy
    is swallowed; the poll has what it read.
    """
    copy = Path(path)
    if copy.parent.name != SHADOW_DIRNAME:
        return
    try:
        copy.unlink()
    except OSError:
        pass
