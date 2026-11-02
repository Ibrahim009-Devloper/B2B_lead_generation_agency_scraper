import os
import gc
import logging
from typing import Dict, Any

logger = logging.getLogger("MemoryGuard")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

def get_memory_stats() -> Dict[str, Any]:
    """Returns current process RAM usage in MB."""
    if not HAS_PSUTIL:
        return {"rss_mb": 0.0, "vms_mb": 0.0, "percent": 0.0}
    try:
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        rss_mb = round(mem.rss / (1024 * 1024), 2)
        vms_mb = round(mem.vms / (1024 * 1024), 2)
        percent = round(proc.memory_percent(), 1)
        return {
            "rss_mb": rss_mb,
            "vms_mb": vms_mb,
            "percent": percent
        }
    except Exception:
        return {"rss_mb": 0.0, "vms_mb": 0.0, "percent": 0.0}

def check_memory_and_cleanup(threshold_mb: float = 340.0) -> bool:
    """
    Checks RAM usage against a safe threshold (340 MB for Render's 512 MB limit).
    If memory exceeds threshold, forces cyclic garbage collection immediately.
    Returns True if threshold was exceeded and cleanup was executed.
    """
    stats = get_memory_stats()
    rss = stats.get("rss_mb", 0.0)

    if rss >= threshold_mb:
        logger.warning(
            f"MEMORY GUARD: High memory pressure detected ({rss} MB / 512 MB limit). "
            f"Triggering immediate aggressive garbage collection..."
        )
        # Run gc collection across all generations
        collected = gc.collect()
        new_stats = get_memory_stats()
        new_rss = new_stats.get("rss_mb", 0.0)
        logger.info(f"MEMORY GUARD: Collected {collected} unreachable objects. RAM dropped from {rss} MB to {new_rss} MB.")
        return True
    
    return False

def force_garbage_collection() -> None:
    """Explicitly runs garbage collector to release cyclic references."""
    gc.collect()

