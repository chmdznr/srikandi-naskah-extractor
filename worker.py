"""RQ worker entrypoint. Run with: uv run python worker.py"""
import logging
import sys
import time

from rq import SimpleWorker

from jobs import QUEUE_NAME, get_queue, get_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("extractor-worker")


def _warmup_extractor():
    """Eager-init Docling converter so first real job doesn't pay 50-70s cold-start tax.
    Trade-off: worker startup ~60s longer, but every job latency consistent + low.
    """
    log.info("Warming up Docling converter (loading layout + tableformer models to memory)...")
    t0 = time.perf_counter()
    import extractor
    extractor._get_converter()
    log.info(f"Docling converter ready in {time.perf_counter()-t0:.1f}s")


def main():
    log.info(f"Starting RQ worker on queue '{QUEUE_NAME}'")
    log.info(f"Redis: {get_redis().connection_pool.connection_kwargs}")
    # Pre-load Docling models at startup so the FIRST job doesn't eat the ~100s
    # cold-start (model load to GPU). Pays it ONCE here, not per first-job. The
    # earlier "hang" was just this load taking ~60-100s — not an actual hang.
    _warmup_extractor()
    # SimpleWorker runs jobs IN-PROCESS (no fork). Required for CUDA: RQ's default
    # Worker forks a child per job, and a forked child cannot reuse the parent's
    # already-initialized CUDA context (Docling's PDF layout model runs on GPU) →
    # "Cannot re-initialize CUDA in forked subprocess". In-process also keeps the
    # warmed model resident across jobs. (DOCX used SimplePipeline = no GPU, so it
    # worked even under fork; PDF exposed the bug.)
    worker = SimpleWorker([get_queue()], connection=get_redis())
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    sys.exit(main() or 0)
