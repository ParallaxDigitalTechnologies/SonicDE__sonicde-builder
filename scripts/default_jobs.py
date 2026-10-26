#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Print a conservative default compiler job count for one package build."""
import os
from pathlib import Path

available = 0
try:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            available = int(line.split()[1]) * 1024
            break
except OSError:
    pass
try:
    limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
    current = int(Path("/sys/fs/cgroup/memory.current").read_text())
    if limit != "max":
        available = min(available or int(limit), max(0, int(limit) - current))
except (OSError, ValueError):
    pass
usable = max(0, available - 1024**3)
memory_jobs = max(1, usable // (2 * 1024**3))
print(max(1, min(os.cpu_count() or 1, memory_jobs, 8)))
