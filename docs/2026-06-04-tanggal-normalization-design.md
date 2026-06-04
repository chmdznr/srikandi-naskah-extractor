# Normalisasi Field `tanggal` ke ISO `YYYY-MM-DD`

**Tanggal:** 2026-06-04 · **Status:** disetujui

## Masalah

Field `tanggal` di hasil ekstraksi di-pass mentah dari output LLM (`extractor.py`,
assignment `result.tanggal`). Prompt metadata tidak menyebut format, sehingga nilai
mengikuti gaya penulisan dokumen: `"12 Mei 2026"`, `"Jakarta, 12 Mei 2026"`,
`"12/05/2026"`, dst. Konsumen (FE) harus menebak format.

## Keputusan desain

| Keputusan | Pilihan |
|---|---|
| Pendekatan | **Prompt + normalizer Python** (dua lapis) |
| Prompt benchmark Colab | Boleh diubah (deviasi dicatat; angka 85.2% diukur dengan prompt lama) |
| Kontrak field `tanggal` | **Selalu** `YYYY-MM-DD` valid **atau** `null` — tidak pernah format lain |
| Gagal normalisasi | `tanggal = null` + warning `tanggal_not_normalized: <raw>` (nilai mentah terbaca di warning, tidak hilang jejak) |
| Konvensi tanggal numerik | `DD/MM/YYYY` (Indonesia), bukan `MM/DD/YYYY` |

## Perubahan

### 1. `prompts.py` — `PROMPT_METADATA`
Tambah aturan setelah blok format JSON:

```
Aturan field "tanggal": tulis dalam format YYYY-MM-DD (contoh: 2026-05-12).
Konversi nama bulan Indonesia ke angka. Jika tanggal tidak lengkap atau tidak
ditemukan, isi null.
```

### 2. `extractor.py` — `_normalize_tanggal(value: str | None) -> str | None`
Urutan:
1. `None` / string kosong → `None`
2. Sudah `YYYY-MM-DD` → validasi tanggal riil (`datetime.strptime`; `2026-02-30` ditolak) → lolos
3. Regex **search** (bukan full-match — toleran prefix kota/hari, mis. `"Jakarta, 12 Mei 2026"`):
   - `D NamaBulan YYYY` — bulan Indonesia case-insensitive, nama panjang + singkatan umum
     (`jan|januari`, `feb|februari|pebruari`, `mar|maret`, `apr|april`, `mei`,
     `jun|juni`, `jul|juli`, `agu|agt|ags|agustus`, `sep|sept|september`,
     `okt|oktober`, `nov|november|nopember`, `des|desember`)
   - `DD/MM/YYYY`, `DD-MM-YYYY`, `DD.MM.YYYY` — interpretasi DD/MM (konvensi Indonesia)
4. Semua gagal → `None`

Integrasi di `extract()`:
```python
raw = meta_obj.get("tanggal")
result.tanggal = _normalize_tanggal(raw)
if raw and result.tanggal is None:
    result.warnings.append(f"tanggal_not_normalized: {raw!r}")
```

### 3. Test — `test_normalize_tanggal.py` (TDD, parametrized)
Kasus: ISO valid lolos apa adanya; bulan Indonesia panjang & singkat; `dd/mm/yyyy`
dan varian separator; prefix kota (`"Jakarta, 12 Mei 2026"`); tanggal invalid
(`2026-02-30`, `31/04/2026`) → `None`; tanggal parsial (`"Mei 2026"`) → `None`;
`None`/kosong → `None`; string sampah → `None`; literal merge-var `"${tanggal}"` → `None`.

### 4. Dokumentasi
- README: catat kontrak `tanggal` (ISO atau null) di tabel field `result`
- `main.py`: contoh OpenAPI responses pakai `"2026-05-12"`
- FE dikabari (via WA) bahwa format kini seragam + arti warning `tanggal_not_normalized`

## Tidak diubah
Dataclass `ExtractionResult` (tipe field tetap `str | None`), alur ekstraksi lain,
benchmark Colab itu sendiri.

## Risiko
- Prompt baru ≠ prompt benchmark → angka akurasi laporan PoC secara ketat merujuk
  prompt lama. Mitigasi: normalizer deterministik menjamin kontrak terlepas dari
  perilaku LLM; field lain tak tersentuh.
- Dokumen dengan >1 tanggal di header: LLM yang memilih (perilaku sama dengan
  sekarang); normalizer hanya menyeragamkan format, tidak memilih tanggal.
