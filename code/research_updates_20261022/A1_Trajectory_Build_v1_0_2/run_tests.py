#!/usr/bin/env python3
"""Bound the offline self-test process, including its synthetic subprocesses."""
from __future__ import annotations
import os,signal,subprocess,sys
from pathlib import Path

def stop_test_group(process):
    # This group was created below solely for these offline tests. Do not
    # signal other Python/Stockfish processes or another research job.
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait(timeout=5)

def main():
    script=Path(__file__).resolve().with_name('test_build.py')
    print('Offline test limit: 180 seconds; any stall prints a stack trace after 45 seconds.',flush=True)
    process=subprocess.Popen([sys.executable,'-u',str(script)],start_new_session=True)
    try:
        code=process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        print('OFFLINE_TESTS_TIMED_OUT: saved log contains diagnostic stacks. Real downloads were not started.',flush=True)
        stop_test_group(process)
        return 2
    except KeyboardInterrupt:
        stop_test_group(process)
        print('Offline tests interrupted; real downloads were not started.',flush=True)
        return 130
    if code==0:print('A1_TRAJECTORY_TESTS_OK; synthetic data and fake engine only.',flush=True)
    return code if code>=0 else 128-code

if __name__=='__main__':raise SystemExit(main())
