#!/usr/bin/env python3
"""A stand-in for sudo that records the command it was asked to run.

The server's tests build it with `Settings(sudo=<this file>)`. It appends its
arguments, joined by spaces, as one line to the file named by
`VITALS_STUB_LOG`, then exits 0, or 1 when `VITALS_STUB_FAIL` is set.
"""

import os
import sys

with open(os.environ["VITALS_STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
sys.exit(1 if os.environ.get("VITALS_STUB_FAIL") else 0)
