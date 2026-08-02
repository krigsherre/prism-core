# Architecture Decision Record (ADR): GPU Extractor

Foundational decisions for the `gpu-extractor` service — concurrent extraction, GPU batching, and a slim dependency surface.

---

## 1. Concurrency: asyncio + Thread Offload

**Decision:** Coordinate the pipeline with `asyncio`; offload CPU/GPU-bound work via `asyncio.to_thread` and internal futures. Cap in-flight docs with a semaphore on the Kafka consumer.

**Alternatives Evaluated:**
* Fully synchronous per-message processing.
* Celery/RQ for every crop/box.

**Why Chosen:** Downloads are I/O-bound; inference is compute-bound. Blocking the consumer on GPU work breaks Kafka heartbeats. An in-process event loop keeps acknowledgements healthy without the serialization cost of an external task fleet for short-lived crops.

---

## 2. GPU Inference: Dynamic Continuous Batching

**Decision:** Decouple inference behind a `DynamicBatcher` that flushes on a latency window or max batch size.

**Alternatives Evaluated:**
* Batch size = 1 (sequential).
* Static batching (wait for exactly N).

**Why Chosen:** Vision/OCR models amortize transfer cost across batches. Static batching deadlocks on short documents; continuous batching saturates the GPU under load while bounding latency when idle.

---

## 3. Layout: 1D DBSCAN on Native Coordinates

**Decision:** Group reading order with 1D DBSCAN on Y-coordinates from PyMuPDF boxes for digitally native PDFs.

**Alternatives Evaluated:**
* Hardcoded pixel grids.
* LayoutLMv3 / heavy vision layout models on every page.

**Why Chosen:** Native PDFs already expose accurate coordinates. DBSCAN is sub-millisecond on CPU and leaves VRAM for table VLMs. Scanned-only pages can later route to a heavier layout model without taxing the common path.

---

## 4. Office → PDF via Gotenberg Sidecar

**Decision:** Convert `.docx` / `.pptx` through [Gotenberg](https://gotenberg.dev/) over HTTP, not LibreOffice inside the GPU image.

**Why Chosen:** Keeps the worker image slim and avoids embedding a JVM/LibreOffice stack on GPU nodes. Conversion scales horizontally on cheap CPU sidecars.

---

## 5. In-Memory I/O (No Disk Spool)

**Decision:** Stream S3 objects into `BytesIO` / memory and feed PyMuPDF from bytes.

**Why Chosen:** Avoids `/tmp` IOPS thrash under concurrency. Trade-off: very large documents need future chunked streaming or external shard cache.

---

## 6. Custom Pipeline over Unstructured / Docling Monoliths

**Decision:** Own the pipeline (PyMuPDF fast-path + PaddleOCR-VL / adapter factory) instead of wrapping full `unstructured` or Docling stacks.

**Why Chosen:** Monolithic parsers pull multi-GB deps, run synchronously, and force vision layout on native PDFs. A custom path reserves GPU for tables/images, stays air-gap friendly, and matches the async batching model in §§1–2.
