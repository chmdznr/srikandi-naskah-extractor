"""Core pipeline: Docling parse → Ollama LLM extract → typed dict.

Single source of truth for extraction logic. Imported by FastAPI app and any
future worker (Celery, batch script, etc.).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import ollama
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

# Explicit Ollama client — respects OLLAMA_HOST env var (set in docker-compose for worker container
# to reach host's Ollama via host.docker.internal). Defaults to localhost for native dev.
_ollama_client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))

from prompts import (
    PROMPT_METADATA,
    PROMPT_RINGKASAN_SINGLE,
    PROMPT_RINGKASAN_MAP,
    PROMPT_RINGKASAN_REDUCE,
    HEADER_CHARS,
    CHUNK_CHARS,
    CHUNK_OVERLAP_CHARS,
    RESPONSE_TOKENS,
    needed_tokens,
    fits_single_shot,
)


def _chunk_text(text: str, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Char-based chunking with overlap. Returns list of chunks."""
    if overlap >= chunk_chars:
        raise ValueError(f"overlap ({overlap}) must be < chunk_chars ({chunk_chars}) — would infinite-loop")
    if len(text) <= chunk_chars:
        return [text]
    chunks, i = [], 0
    step = chunk_chars - overlap
    while i < len(text):
        chunks.append(text[i : i + chunk_chars])
        i += step
    return chunks

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
DEFAULT_CTX_TOKENS = 32_768  # qwen2.5 context window

# Single shared converter instance — Docling loads layout model on first call (~3s, ~2GB VRAM).
# Reuse means subsequent parses are fast.
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        log.info("Initializing Docling converter (loads layout model on first parse)...")
        # Log accelerator visibility — important for perf debugging.
        # Docling auto-detects CUDA → MPS → CPU. In Docker on Mac, Metal NOT exposed → CPU fallback.
        try:
            import torch
            if torch.cuda.is_available():
                acc = f"CUDA ({torch.cuda.get_device_name(0)})"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                acc = "MPS (Apple Metal)"
            else:
                acc = "CPU (no GPU detected — parsing image-heavy PDF will be ~5-10× slower)"
            log.info(f"Docling accelerator: {acc}")
        except Exception:
            pass

        # Disable OCR — naskah dinas Srikandi semua born-digital (DOCX→PDF) dengan text layer.
        # OCR pipeline init = +20-30s startup + RapidOCR model download. Untuk scanned PDF nantinya,
        # extract akan return parsed_chars rendah → bisa di-flag via warning di caller.
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True  # tetap parse table structure
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    return _converter


def parse_document(file_path: Path) -> tuple[str, float]:
    """Parse DOCX/PDF to markdown. Returns (markdown_text, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = _get_converter().convert(str(file_path))
    markdown = result.document.export_to_markdown()
    return markdown, time.perf_counter() - t0


def _ceil_to(n: int, step: int) -> int:
    return ((n + step - 1) // step) * step


def _extract_json(text: str) -> tuple[dict, bool]:
    """Best-effort JSON extraction from LLM output. Returns (parsed_dict, is_valid)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    try:
        return json.loads(t), True
    except json.JSONDecodeError:
        pass
    depth, start = 0, -1
    for i, ch in enumerate(t):
        if ch == "{":
            if start < 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(t[start : i + 1]), True
                except Exception:
                    break
    return {"_raw": text[:500]}, False


def _ollama_call(model: str, prompt: str, model_ctx: int, num_predict: int = RESPONSE_TOKENS) -> tuple[str, dict]:
    """Run a single Ollama generate call with right-sized num_ctx. Returns (response_text, timing_dict)."""
    ctx_needed = needed_tokens(len(prompt), num_predict)
    num_ctx = min(model_ctx, max(2048, _ceil_to(ctx_needed, 2048)))
    options = {"temperature": 0.0, "num_predict": num_predict, "num_ctx": num_ctx}

    t0 = time.perf_counter()
    resp = _ollama_client.generate(model=model, prompt=prompt, options=options, stream=False)
    elapsed = time.perf_counter() - t0

    r = resp if isinstance(resp, dict) else resp.__dict__
    return r.get("response", ""), {
        "elapsed_s": round(elapsed, 3),
        "eval_tokens": r.get("eval_count", 0) or 0,
        "prompt_tokens": r.get("prompt_eval_count", 0) or 0,
        "num_ctx_used": num_ctx,
    }


@dataclass
class ExtractionResult:
    hal: str | None = None
    nomor_naskah: str | None = None
    tanggal: str | None = None
    suggest_ringkasan: str | None = None
    # Diagnostics
    parsed_markdown_preview: str = ""
    docling_elapsed_s: float = 0.0
    metadata_elapsed_s: float = 0.0
    ringkasan_elapsed_s: float = 0.0
    ringkasan_n_llm_calls: int = 0       # 1 untuk single-shot, N+1 untuk map-reduce
    metadata_json_valid: bool = False
    ringkasan_json_valid: bool = False
    model: str = ""
    strategy: str = "single-shot"        # "single-shot" | "map-reduce"
    parsed_chars: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract(
    file_path: Path,
    model: str = DEFAULT_MODEL,
    model_ctx: int = DEFAULT_CTX_TOKENS,
) -> ExtractionResult:
    """Full pipeline: parse → metadata extract → ringkasan extract → typed result.

    Errors in any sub-step are captured in `warnings` rather than raised, so partial
    results still return (e.g. metadata succeeds but ringkasan fails).
    """
    result = ExtractionResult(model=model)

    # 1. Docling parse
    try:
        markdown, parse_t = parse_document(file_path)
        result.docling_elapsed_s = round(parse_t, 3)
        result.parsed_chars = len(markdown)
        result.parsed_markdown_preview = markdown[:1000]
    except Exception as e:
        result.warnings.append(f"docling_parse_failed: {e}")
        return result

    # 2. Metadata extraction (header-only, fast)
    header = markdown[:HEADER_CHARS]
    meta_prompt = PROMPT_METADATA.format(header_text=header)
    try:
        meta_response, meta_timing = _ollama_call(model, meta_prompt, model_ctx)
        result.metadata_elapsed_s = meta_timing["elapsed_s"]
        meta_obj, meta_ok = _extract_json(meta_response)
        result.metadata_json_valid = meta_ok
        if meta_ok:
            result.hal = meta_obj.get("hal")
            result.nomor_naskah = meta_obj.get("nomor_naskah")
            result.tanggal = meta_obj.get("tanggal")
        else:
            result.warnings.append("metadata_json_parse_failed")
    except Exception as e:
        result.warnings.append(f"metadata_extract_failed: {e}")

    # 3. Ringkasan generation — single-shot kalau muat, else map-reduce chunking
    if fits_single_shot(len(markdown), model_ctx):
        _ringkasan_single_shot(result, markdown, model, model_ctx)
    else:
        _ringkasan_map_reduce(result, markdown, model, model_ctx)

    return result


def _ringkasan_single_shot(result: ExtractionResult, markdown: str, model: str, model_ctx: int) -> None:
    result.strategy = "single-shot"
    prompt = PROMPT_RINGKASAN_SINGLE.format(document_text=markdown)
    try:
        response, timing = _ollama_call(model, prompt, model_ctx)
        result.ringkasan_elapsed_s = timing["elapsed_s"]
        result.ringkasan_n_llm_calls = 1
        obj, ok = _extract_json(response)
        result.ringkasan_json_valid = ok
        if ok:
            result.suggest_ringkasan = obj.get("suggest_ringkasan")
        else:
            result.warnings.append("ringkasan_json_parse_failed")
    except Exception as e:
        result.warnings.append(f"ringkasan_single_shot_failed: {e}")


def _ringkasan_map_reduce(result: ExtractionResult, markdown: str, model: str, model_ctx: int) -> None:
    """Doc terlalu panjang untuk single-shot: chunk → ringkas tiap chunk → merge ringkasan."""
    result.strategy = "map-reduce"
    chunks = _chunk_text(markdown)
    log.info(f"Ringkasan map-reduce: {len(chunks)} chunks @ ~{CHUNK_CHARS} chars each")

    chunk_summaries: list[str] = []
    total_elapsed = 0.0
    try:
        # MAP: summarize each chunk in 1-2 kalimat
        for i, chunk in enumerate(chunks, 1):
            prompt = PROMPT_RINGKASAN_MAP.format(chunk_idx=i, total_chunks=len(chunks), chunk=chunk)
            response, timing = _ollama_call(model, prompt, model_ctx, num_predict=200)
            chunk_summaries.append(response.strip())
            total_elapsed += timing["elapsed_s"]
            result.ringkasan_n_llm_calls += 1
    except Exception as e:
        result.warnings.append(f"ringkasan_map_phase_failed: {e}")
        result.ringkasan_elapsed_s = round(total_elapsed, 3)
        return

    try:
        # REDUCE: merge chunk summaries jadi satu ringkasan final dalam JSON
        merged = "\n\n".join(f"[{i+1}] {s}" for i, s in enumerate(chunk_summaries))
        prompt = PROMPT_RINGKASAN_REDUCE.format(summaries=merged)
        response, timing = _ollama_call(model, prompt, model_ctx)
        total_elapsed += timing["elapsed_s"]
        result.ringkasan_n_llm_calls += 1
        result.ringkasan_elapsed_s = round(total_elapsed, 3)
        obj, ok = _extract_json(response)
        result.ringkasan_json_valid = ok
        if ok:
            result.suggest_ringkasan = obj.get("suggest_ringkasan")
        else:
            result.warnings.append("ringkasan_reduce_json_parse_failed")
    except Exception as e:
        result.warnings.append(f"ringkasan_reduce_phase_failed: {e}")
        result.ringkasan_elapsed_s = round(total_elapsed, 3)
