"""Small renderer supervisor: kill the model process group if its GitTok parent dies.

No model or MLX imports here. The renderer starts this supervisor in a new session.
"""

import os
import signal
import subprocess
import sys


def main() -> int:
    parent = int(sys.argv[1])
    if os.getppid() != parent:
        return 1
    child = subprocess.Popen(sys.argv[2:])  # inherit the batch request pipe, if present
    while True:
        if os.getppid() != parent:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        try:
            code = child.wait(timeout=0.2)
            return code if code >= 0 else 128 - code
        except subprocess.TimeoutExpired:
            continue


if __name__ == "__main__":
    sys.exit(main())
