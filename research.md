# Research & reading that shaped Prism

These are papers, books, and systems I studied while designing Prism — grouped by the decision they informed. Not a flex list: each item maps to something in the codebase.

For the project showcase see [`README.md`](README.md). For diagrams see [`architecture.md`](architecture.md).

---

## Layout, reading order, document AI

| Work | Why I read it | Where it shows up |
|------|----------------|-------------------|
| **Zhao et al.** — *DETRs Beat YOLOs on Real-time Object Detection* (RT-DETR), arXiv:2304.08069, 2023 | Real-time detection without killing throughput | Layout via Docling / RT-DETR-class detectors in `gpu-extractor` |
| **Livathinos et al. / IBM Deep Search** — *Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion*, arXiv:2408.09869, 2024 | Production PDF→structure toolkit; DocLayNet lineage | Layout service + SmolDocling path; I use pieces, not the whole monolith |
| **Pfitzmann et al.** — *DocLayNet: A Large Human-Annotated Dataset for Document-Layout Segmentation*, DocEng 2022 | What “good layout labels” look like | Informed trusting CV layout over naive PDF scrape |
| **Ha, Haralick & Phillips** — recursive **X-Y cut** page segmentation (classic document analysis) | Geometric page segmentation predates transformers | My 1D Y-cluster + X-sort reading-order pass |
| **Ester et al.** — *A Density-Based Algorithm for Discovering Clusters… (DBSCAN)*, KDD 1996 | Density clustering with noise | Inspiration for line clustering on Y (ε ≈ 15px) without loading LayoutLM |
| **Huang et al.** — *LayoutLMv3*, arXiv:2204.08387, 2022 | Strong multimodal layout — also heavy | Explicitly **rejected** as default (VRAM); kept as fallback idea for scans |
| **Blecher et al.** — *Nougat: Neural Optical Understanding for Academic Documents*, arXiv:2308.13418, 2023 | End-to-end PDF→markdown | Useful baseline; weak on financial grids vs dedicated table VLMs |
| **PaddleOCR / PaddleOCR-VL** (PaddlePaddle technical reports & model cards) | Grid-aware table extraction locally | `PaddleOCR-VL-1.6` adapter + OTSL parse in bifurcation |

---

## Constrained generation & small models

| Work | Why I read it | Where it shows up |
|------|----------------|-------------------|
| **Willard & Louf** — *Efficient Guided Generation for Large Language Models* (Outlines), arXiv:2307.09702, 2023 | FSM / regex / JSON constrains tokens at decode time | ADR lineage for “structure isn’t a prompt suggestion”; production path uses vLLM guided JSON / instructor structured outputs |
| **Kwon et al.** — *Efficient Memory Management for Large Language Model Serving with PagedAttention* (vLLM), arXiv:2309.06180, 2023 | High-throughput serving, continuous batching | Centralized vLLM; thin aligner/extractor workers |
| **OpenAI** — Structured Outputs / JSON Schema constrained decoding (2024 product + eng notes) | Schema-faithful decode in practice | `beta.chat.completions.parse` / guided_json paths |
| **Qwen Team** — *Qwen2.5 Technical Report*, arXiv:2412.15115, 2024 | Strong open instruct models for local extract | Default SLM target in ADRs |
| **Dettmers et al.** — *QLoRA*, arXiv:2305.14314 / NeurIPS 2023 | Cheap fine-tunes from HITL corrections | Roadmap: distill from analyst patches |
| **Liu et al.** — *Lost in the Middle*, arXiv:2307.03172, 2023 | Long context ≠ used context | Sliding / chunked table windows instead of stuffing whole PDFs |

---

## Dedup, streaming, data systems

| Work | Why I read it | Where it shows up |
|------|----------------|-------------------|
| **Broder** — *On the Resemblance and Containment of Documents*, SEQS 1997 | MinHash for near-duplicate detection | Triage near-dup / version story |
| **Leskovec, Rajaraman & Ullman** — *Mining of Massive Datasets* (LSH chapters) | Banding, Jaccard approximation | How I think about similarity thresholds |
| **Kreps, Narkhede & Rao** — *Kafka: a Distributed Messaging System for Log Processing*, NetDB 2011 | Durable log as integration spine | Whole pipeline |
| **Debezium / CDC literature** (Red Hat docs + “log-based CDC” pattern) | Capture DB changes without dual-write | `storage-sync` observer on extracted table events |
| **Kleppmann** — *Designing Data-Intensive Applications* (event sourcing / log chapters) | Replay, idempotency, “turn the DB inside out” | Idempotent `(document_id, node_id, row_index)` upserts |

---

## Agents, repair loops, RAG

| Work | Why I read it | Where it shows up |
|------|----------------|-------------------|
| **Shinn et al.** — *Reflexion: Language Agents with Verbal Reinforcement Learning*, arXiv:2303.11366, 2023 | Verbal feedback → next attempt | `align_with_reflexion` + critic error reinjection |
| **Yao et al.** — *ReAct*, arXiv:2210.03629, 2023 | Reason + act loops | Generate → execute → retry in LangGraph nodes |
| **Madaan et al.** — *Self-Refine*, arXiv:2303.17651, 2023 | Iterative self-critique | Same family as critic-guided repair |
| **Edge et al.** — *From Local to Global: A GraphRAG Approach…*, arXiv:2404.16130, 2024 | Graph-structured retrieval for QA | Tri-modal brain; Neo4j + vectors (native GraphRAG consolidation still roadmap) |
| **Lewis et al.** — *Retrieval-Augmented Generation for Knowledge-Intensive NLP*, arXiv:2005.11401, 2020 | RAG baseline | Vector modality |
| **Xiao et al.** — *C-Pack / BGE embedding models*, arXiv:2309.07597, 2023 | Strong small embedders | TEI + `bge-small` in compose |
| **LangGraph** (LangChain eng docs / blogs) | Durable agent graphs, checkpoints | `agentic-brain` workflow |