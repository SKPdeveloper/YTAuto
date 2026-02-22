"""
A/B Daemon Launcher — shared utility for starting the A/B rotation daemon.

Used by:
- publish_stage.py (after successful YouTube upload)
- control_pipeline.py (after _register_for_ab_monitoring)
- scripts/APPROVE.bat (via CLI)

The daemon is started as a detached background process on Windows.
Non-fatal: all errors are logged but never block the pipeline.
"""

import os
import subprocess
import sys
from pathlib import Path

from app.utils.logger import logger
from app.core.config import settings


# PID file lives at project root
PID_FILE = settings.BASE_DIR / "ab_daemon.pid"


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except ImportError:
        pass

    # Fallback: os.kill with signal 0 (works on Windows too)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def ensure_ab_daemon_running(caller: str = "unknown") -> bool:
    """
    Ensure the A/B rotation daemon is running.

    If a PID file exists and the process is alive, does nothing.
    Otherwise starts a new daemon process (detached on Windows).

    Args:
        caller: identifier for logging (e.g. "publish_stage", "control_pipeline")

    Returns:
        True if daemon is running (was already running or just started).
        False if failed to start (non-fatal — logged as warning).
    """
    try:
        # Check existing PID file
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                if _is_process_alive(pid):
                    logger.info(f"[{caller}] AB daemon: already running (PID {pid})")
                    return True
                else:
                    logger.debug(f"[{caller}] AB daemon: PID file check — stale PID {pid}, restarting")
                    PID_FILE.unlink(missing_ok=True)
            except (ValueError, OSError):
                PID_FILE.unlink(missing_ok=True)

        # Start new daemon process
        python_exe = sys.executable
        daemon_cmd = [python_exe, "-X", "utf8", "-m", "src.publisher.ab_daemon"]

        # Windows: DETACHED_PROCESS so it survives parent exit
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            daemon_cmd,
            cwd=str(settings.BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        # Write PID file
        PID_FILE.write_text(str(proc.pid))

        logger.success(f"[{caller}] AB daemon: started (PID {proc.pid})")
        return True

    except Exception as e:
        logger.warning(f"[{caller}] AB daemon: failed to start — {e}")
        return False
