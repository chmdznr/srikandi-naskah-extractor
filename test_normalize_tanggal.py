"""Tests for _normalize_tanggal — kontrak: selalu YYYY-MM-DD valid atau None."""
import pytest

from extractor import _normalize_tanggal


@pytest.mark.parametrize(
    "raw,expected",
    [
        # ISO valid → lolos apa adanya
        ("2026-05-12", "2026-05-12"),
        ("Ditetapkan tanggal 2026-05-12", "2026-05-12"),
        # Bulan Indonesia — nama panjang
        ("12 Mei 2026", "2026-05-12"),
        ("12 mei 2026", "2026-05-12"),
        ("3 Agustus 2025", "2025-08-03"),
        ("17 Pebruari 2025", "2025-02-17"),  # ejaan lama
        ("5 Nopember 2024", "2024-11-05"),   # ejaan lama
        # Bulan Indonesia — singkatan
        ("3 Agt 2025", "2025-08-03"),
        ("3 Ags 2025", "2025-08-03"),
        ("21 Okt 2026", "2026-10-21"),
        ("1 Des 2025", "2025-12-01"),
        # Prefix kota / hari (regex search, bukan full-match)
        ("Jakarta, 12 Mei 2026", "2026-05-12"),
        ("Senin, 12 Mei 2026", "2026-05-12"),
        # Numerik DD/MM/YYYY (konvensi Indonesia) + varian separator
        ("12/05/2026", "2026-05-12"),
        ("12-05-2026", "2026-05-12"),
        ("12.05.2026", "2026-05-12"),
        ("5/11/2026", "2026-11-05"),
        # Tanggal invalid → None
        ("2026-02-30", None),
        ("31/04/2026", None),
        ("32 Mei 2026", None),
        # Tanggal parsial / tidak lengkap → None
        ("Mei 2026", None),
        ("2026", None),
        # Kosong / null / sampah → None
        (None, None),
        ("", None),
        ("   ", None),
        ("tidak ada", None),
        ("${tanggal}", None),  # literal merge-var dari template DOCX kosong
        ("12 Foo 2026", None),  # nama bulan tak dikenal
    ],
)
def test_normalize_tanggal(raw, expected):
    assert _normalize_tanggal(raw) == expected
