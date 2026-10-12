"""Lock singleton buat Celery beat (Fase 10.1d, sebelumnya dipindah dari 6.7).

Celery beat TIDAK punya leader election -- dua proses beat yang jalan
barengan sama-sama fire SEMUA jadwal (84 scraper + 9 task periodik) dua
kali. Itu kejadian nyata pas deploy: `docker compose up -d` bikin container
beat baru nyala selagi yang lama masih berhenti pelan-pelan, atau ada dua
node yang salah-konfigurasi. Scraper sendiri aman dari dobel-run (dedup),
tapi task periodik (recap mingguan, alert PIR, digest Telegram) TIDAK -- itu
kirim pesan dobel.

Pola: `SET key token NX PX ttl` buat ambil, Lua "extend kalau masih punya
gue" buat perpanjang, Lua "delete kalau masih punya gue" buat lepas. Token
unik per proses -- proses yang lock-nya kadaluarsa terus diambil orang lain
GAK bisa nge-perpanjang/ngehapus lock orang itu.

Dipakai `cti_worker.beat_main` (gate di depan `celery beat`), bukan
scheduler kustom: standby sama sekali gak ngejalanin Celery beat, jadi pas
ambil alih dia mulai bersih, gak nge-fire catch-up buat slot yang lewat
selama dia nunggu."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

LOCK_KEY = "cti:beat:lock"

_LUA_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_LUA_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class BeatLock:
    def __init__(
        self, client: redis.Redis, *, ttl_ms: int, key: str = LOCK_KEY, token: str | None = None
    ) -> None:
        self._client = client
        self._key = key
        self._ttl_ms = ttl_ms
        self.token = token or uuid.uuid4().hex
        self._renew_script = client.register_script(_LUA_RENEW)
        self._release_script = client.register_script(_LUA_RELEASE)

    def acquire(self) -> bool:
        """True kalau SEKARANG kita leader. Cuma berhasil kalau key belum
        ada (NX) -- gak nyuri lock yang masih hidup."""
        return bool(self._client.set(self._key, self.token, nx=True, px=self._ttl_ms))

    def renew(self) -> bool:
        """Perpanjang TTL. False = lock udah bukan punya kita (kadaluarsa,
        diambil proses lain) -- caller HARUS berhenti jadi leader, bukan
        nyoba `acquire()` diam-diam sambil tetap jalan."""
        return bool(self._renew_script(keys=[self._key], args=[self.token, self._ttl_ms]))

    def release(self) -> bool:
        """Lepas lock kalau masih punya kita, biar standby ambil alih
        seketika (bukan nunggu TTL abis). Aman dipanggil kapan pun."""
        return bool(self._release_script(keys=[self._key], args=[self.token]))
