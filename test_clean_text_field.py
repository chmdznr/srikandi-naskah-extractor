"""Tests for _clean_text_field — kontrak: string bermakna (ter-strip) atau None, tak pernah ""."""
import pytest

from extractor import _clean_text_field


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Nilai bermakna → lolos (ter-strip)
        ("Undangan Narasumber", "Undangan Narasumber"),
        ("  Permohonan Pemasangan Jaringan  ", "Permohonan Pemasangan Jaringan"),
        ("000.5.6.2/X /2025", "000.5.6.2/X /2025"),
        # Kosong / whitespace → None
        (None, None),
        ("", None),
        ("   ", None),
        # Konvensi "kosong" di surat dinas → None
        ("-", None),
        ("—", None),
        # Literal merge-var template Srikandi yang belum terisi → None
        ("${hal}", None),
        ("${nomor_naskah}", None),
        ("${ tanggal }", None),
        # Merge-var di tengah teks bermakna → biarkan (bukan murni merge-var)
        ("Permohonan ${jenis} jaringan", "Permohonan ${jenis} jaringan"),
    ],
)
def test_clean_text_field(raw, expected):
    assert _clean_text_field(raw) == expected


# --- _hal_label_present ----------------------------------------------------
from extractor import _hal_label_present


@pytest.mark.parametrize(
    "header,expected",
    [
        # Label di kop surat → True
        ("Nomor : 1\nHal : Undangan Narasumber", True),
        ("Perihal\t: Permohonan Pemasangan", True),
        ("HAL: SESUATU", True),
        # Bentuk markdown table hasil Docling → True
        ("| Hal | : Undangan |", True),
        ("| Perihal | : | Permohonan |", True),
        # Tanpa label (Surat Tugas / SK) → False
        ("SURAT TUGAS\nNOMOR : 000.5/2025\nDasar : ...\nUntuk : Melaksanakan ...", False),
        # Kata "hal" di tengah kalimat ≠ label → False
        ("dalam hal : sesuatu yang lain", False),
        ("segala hal: penting", False),
        # "Hal." singkatan halaman → False
        ("Hal. 2 dari 3", False),
        ("", False),
    ],
)
def test_hal_label_present(header, expected):
    assert _hal_label_present(header) is expected
