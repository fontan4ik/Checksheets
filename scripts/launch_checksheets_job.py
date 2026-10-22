#!/usr/bin/env python3
"""Run the saved launchd job using Python's existing external-volume access.

Installed locally in ~/Library/Application Support/Voltmir/ChecksheetsRuntime.
launchd starts in that internal directory; this process opens the original logs
and starts the original command in its original working directory. Job schedules,
environment and Telegram wrappers remain in the installed job configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys


def main() -> int:
    config_path = Path(sys.argv[1])
    with config_path.open('rb') as handle:
        job = plistlib.load(handle)
    streams = []
    child = None
    pending_signals = []

    def forward(signum, _frame):
        if child is None:
            pending_signals.append(signum)
        else:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, forward)

    def log_stream(key):
        path = job.get(key)
        if not path:
            return None
        handle = open(path, 'ab', buffering=0)
        streams.append(handle)
        return handle

    try:
        child = subprocess.Popen(
            job['ProgramArguments'],
            cwd=job.get('WorkingDirectory'),
            env={**os.environ, **job.get('EnvironmentVariables', {})},
            stdin=subprocess.DEVNULL,
            stdout=log_stream('StandardOutPath'),
            stderr=log_stream('StandardErrorPath'),
            start_new_session=True,
        )
        for signum in pending_signals:
            forward(signum, None)
        result = child.wait()
        return result if result >= 0 else 128 - result
    finally:
        for handle in streams:
            handle.close()


if __name__ == '__main__':
    sys.exit(main())
