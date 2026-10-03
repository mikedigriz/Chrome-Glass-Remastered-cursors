"""GPU backend: torch ports of cgr/hybrid.py stages, checked against the CPU path.

Load limits, so a build leaves the desktop usable (all overridable by env):
  CGR_BACKEND          cpu (default) | gpu
  CGR_GPU_WORKERS      render processes when the backend is gpu (default: half the cores, at most 6; an explicit value is taken as is)
  CGR_GPU_MEM_MB       VRAM one process may hold (default 1024)
  CGR_GPU_CHUNK_MB     size of one temporary tensor, i.e. how long a kernel runs (default 48)
  CGR_GPU_FIT_MB       the same for the fold width search, which is launch-bound (default 300)
  CGR_NICE             1 (default) runs render processes below normal priority
"""
import os

BACKEND = os.environ.get("CGR_BACKEND", "cpu")      # "gpu" switches ported stages to torch

MEM_MB = int(os.environ.get("CGR_GPU_MEM_MB", "1024"))
CHUNK_MB = int(os.environ.get("CGR_GPU_CHUNK_MB", "48"))
FIT_MB = int(os.environ.get("CGR_GPU_FIT_MB", "300"))      # the width search: launch-bound, wants big chunks


def workers(default_cores):
    """How many render processes to run: fewer on the gpu backend, which shares one device."""
    if BACKEND != "gpu":
        return default_cores
    asked = int(os.environ.get("CGR_GPU_WORKERS", 0))
    return max(1, asked if asked else min(default_cores // 2, 6))


def lower_priority():
    if os.environ.get("CGR_NICE", "1") != "1":
        return
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)   # BELOW_NORMAL
        else:
            os.nice(10)
    except OSError:
        pass


def apply_limits():
    """Called once per render process: priority and a VRAM ceiling."""
    if BACKEND != "gpu":
        return
    lower_priority()
    import torch
    free, total = torch.cuda.mem_get_info()
    torch.cuda.set_per_process_memory_fraction(min(1.0, MEM_MB * 2 ** 20 / total))


def rows_for(width_elems, itemsize=8, mb=None):
    """Rows of a (rows, width_elems) tensor that fit in one CHUNK_MB temporary (at least 1)."""
    return max(1, int((mb or CHUNK_MB) * 2 ** 20 // (width_elems * itemsize)))
