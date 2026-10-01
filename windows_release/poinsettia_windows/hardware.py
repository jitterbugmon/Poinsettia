from __future__ import annotations

import ctypes
import os


def installed_memory_gb() -> float | None:
    """Read physical memory without requiring a third-party Windows package."""
    if os.name != "nt":
        return None
    try:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_uint32),
                ("memory_load", ctypes.c_uint32),
                ("total_phys", ctypes.c_uint64),
                ("avail_phys", ctypes.c_uint64),
                ("total_page", ctypes.c_uint64),
                ("avail_page", ctypes.c_uint64),
                ("total_virtual", ctypes.c_uint64),
                ("avail_virtual", ctypes.c_uint64),
                ("avail_extended", ctypes.c_uint64),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.total_phys / (1024**3)
    except (AttributeError, OSError):
        return None


def p3_warning() -> str | None:
    memory = installed_memory_gb()
    if memory is not None and memory < 16:
        return (
            f"This computer has about {memory:.1f} GB of RAM. "
            "Poinsettia 3.9 with Gemma 4 12B may experience heavy performance latency."
        )
    return None