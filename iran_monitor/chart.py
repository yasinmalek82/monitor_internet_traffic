"""Keep plotting libraries out of the long-running monitor's address space."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from functools import lru_cache

from .analysis import Assessment
from .sources import SourceError


@lru_cache(maxsize=1)
def render_chart(result: Assessment, *, demo=False) -> bytes:
    payload = json.dumps({"assessment": asdict(result), "demo": demo},
                         default=lambda value: value.isoformat()).encode()
    environment = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                   "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
    try:
        worker = subprocess.run([sys.executable, "-m", "iran_monitor.chart_worker"], input=payload,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=environment, timeout=60, check=False)
    except (subprocess.TimeoutExpired, OSError):
        raise SourceError("Chart worker could not finish within its limits") from None
    if worker.returncode != 0 or not worker.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SourceError("Chart worker did not produce a valid PNG")
    return worker.stdout
