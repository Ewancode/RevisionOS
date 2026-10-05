"""Process-level tuning."""

import gc


def freeze_heap() -> None:
    """Tell the garbage collector that everything alive now (imported code,
    config, the loaded embedding model) stays for good.

    Full collections otherwise rescan those millions of long-lived objects
    every time, which showed up as 2-3x tail latency on every endpoint in
    the Phase 12 performance tests. Call once, after start-up has loaded
    everything.
    """
    gc.collect()
    gc.freeze()
