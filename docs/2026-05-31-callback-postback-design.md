# Design — Postback callback ke FE (2026-05-31)

## Tujuan
Saat job ekstraksi selesai, extractor mengirim hasilnya (POST) ke endpoint FE
(dikonfigurasi via env `CALLBACK_URL`). Endpoint FE masih *in-progress*,
jadi postback harus gagal dengan anggun tanpa merusak job.

## Keputusan desain (disepakati)
| Aspek | Pilihan |
|---|---|
| Error handling | **Fire-and-forget + log** — 1x POST, timeout pendek, semua error ditangkap & di-log; job tak terpengaruh |
| Kapan kirim | **Sukses dan gagal** (status `finished` / `failed`) |
| Auth | Header `X-Callback-Token` dari env `CALLBACK_TOKEN` (kosong = header tak dikirim) |
| Payload | Hasil lengkap inline, mirror `GET /jobs/{id}` |

## Arsitektur
Modul baru `callback.py` (satu tanggung jawab: kirim hasil ke FE), dipanggil dari
`run_extraction()` di `jobs.py`. Fire di **worker process** — satu-satunya titik yang
tahu "proses selesai" + punya hasilnya. `SimpleWorker` in-process → `post_result`
sinkron dengan timeout pendek, tak menahan worker lama.

```
run_extraction()
  ├─ extractor.extract() → sukses → payload(finished) ─┐
  │                        └ gagal → payload(failed) ──┤
  │                                                     ▼
  │                            callback.post_result(payload)  (fire-and-forget)
  └─ finally: hapus file upload
  (saat gagal: kirim callback failed → re-raise agar RQ menandai job failed)
```

## Konfigurasi (env, di `deploy/.env`)
- `CALLBACK_URL` — endpoint FE (mis. `https://your-fe.example/api/callback/ai`). **Kosong/unset = callback off** (skip + log debug).
- `CALLBACK_TOKEN` — kosong = header `X-Callback-Token` tak dikirim.
- `CALLBACK_TIMEOUT_S` — default `10`.

## Payload (body POST, `application/json`)
```json
{
  "job_id": "749d223a-...",
  "status": "finished",
  "original_filename": "SURAT TUGAS PEMUSNAHAN.pdf",
  "result": { "nomor_naskah": "...", "tanggal": "...", "suggest_ringkasan": "...", "...": "..." },
  "error": null,
  "completed_at": "2026-05-31T01:15:35.138523+00:00"
}
```
Saat `failed`: `result=null`, `error=<pesan>`.

## Error handling (inti)
`post_result` membungkus POST dalam try/except yang menangkap **semua** exception
(timeout, connection refused, 4xx/5xx, DNS). Gagal → `log.warning(...)` lalu return
tenang. Status job tetap `finished`/`failed` dan hasil tetap bisa di-poll via
`GET /jobs/{id}`. Begitu FE online, callback mulai bekerja tanpa perubahan kode.

## Dependency & testing
- `httpx` sudah terpasang (client Ollama) → tak ada dep baru.
- TDD `test_callback.py`:
  1. payload & header `X-Callback-Token` benar saat token diset
  2. header absen saat token kosong
  3. kegagalan HTTP **tak meng-raise** (bukti fire-and-forget)
  4. `CALLBACK_URL` kosong = tak ada HTTP call

## Out of scope (YAGNI)
- Retry / backoff / dead-letter (sengaja tidak — fire-and-forget cukup untuk PoC).
- Async/threaded dispatch (worker in-process, timeout pendek sudah cukup).
