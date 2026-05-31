"""Extraction prompts — identical to the Colab benchmark (decomposed metadata + ringkasan)."""

PROMPT_METADATA = """Kamu adalah ekstractor data dokumen.
Ekstrak field berikut dari HEADER dokumen di bawah ini dan kembalikan HANYA dalam format JSON, tanpa penjelasan apapun.

Format JSON yang diinginkan:
{{
  "hal": "",
  "nomor_naskah": "",
  "tanggal": ""
}}

Jika data tidak ditemukan atau berupa ${{param}} isi dengan null.

HEADER DOKUMEN:
{header_text}

JSON:"""

PROMPT_RINGKASAN_SINGLE = """Kamu adalah ekstractor data dokumen.
Baca dokumen di bawah dan buat ringkasan singkat dalam 2-3 kalimat. Kembalikan HANYA dalam format JSON, tanpa penjelasan apapun.

Format JSON yang diinginkan:
{{
  "suggest_ringkasan": ""
}}

Jika tidak ada context, isi null.

DOKUMEN:
{document_text}

JSON:"""

PROMPT_RINGKASAN_MAP = """Buat ringkasan singkat dalam 1-2 kalimat dari bagian dokumen di bawah ini. Fokus pada poin substantif (apa, kapan, siapa, mengapa). Abaikan kop surat / formalitas.

BAGIAN DOKUMEN ({chunk_idx}/{total_chunks}):
{chunk}

RINGKASAN BAGIAN:"""

PROMPT_RINGKASAN_REDUCE = """Di bawah ini adalah ringkasan beberapa bagian dari SATU dokumen. Gabungkan menjadi SATU ringkasan akhir dalam 2-3 kalimat yang menggambarkan dokumen secara keseluruhan. Kembalikan HANYA dalam format JSON, tanpa penjelasan apapun.

Format JSON yang diinginkan:
{{
  "suggest_ringkasan": ""
}}

RINGKASAN BAGIAN-BAGIAN:
{summaries}

JSON:"""

# Chunking config — same as benchmark
CHUNK_CHARS = 14_000           # ~3500 tokens per chunk (fit di model 8K ctx dengan headroom)
CHUNK_OVERLAP_CHARS = 500

# Sizing — match benchmark config
HEADER_CHARS = 6_000   # chars dari awal parsed markdown untuk metadata extraction
TOKENS_PER_CHAR = 1 / 3.5  # Indonesian estimate
RESPONSE_TOKENS = 512
PROMPT_TEMPLATE_TOK_OVERHEAD = 150


def needed_tokens(prompt_chars: int, num_predict: int = RESPONSE_TOKENS) -> int:
    return int(prompt_chars * TOKENS_PER_CHAR) + num_predict + PROMPT_TEMPLATE_TOK_OVERHEAD


def fits_single_shot(doc_chars: int, ctx_tokens: int, num_predict: int = RESPONSE_TOKENS) -> bool:
    template_overhead = 500  # chars of template scaffolding around the doc
    return needed_tokens(doc_chars + template_overhead, num_predict) < ctx_tokens
