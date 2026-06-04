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
