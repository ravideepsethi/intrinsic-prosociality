"""Bounded offline test runner; the production download has no elapsed-time cap."""
import os, signal, subprocess, sys
from pathlib import Path

if __name__=='__main__':
    cmd=[sys.executable,'-u',str(Path(__file__).with_name('test_expansion.py'))]
    print('Offline tests: synthetic files and fake HTTP only; 180-second limit.',flush=True)
    process=subprocess.Popen(cmd,start_new_session=True)
    try:code=process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        print('Offline tests exceeded 180 seconds. No production requests were started.',flush=True);code=124
    except KeyboardInterrupt:
        os.killpg(process.pid,signal.SIGTERM);process.wait();code=130
    sys.exit(code)
