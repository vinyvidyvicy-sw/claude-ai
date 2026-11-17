#!/usr/bin/env python3
"""Uji asap (smoke test) untuk portal yang sedang berjalan. Hanya memakai pustaka standar Python 3.

Contoh:
  python3 scripts/smoke_test.py http://127.0.0.1:8000 --username admin
  python3 scripts/smoke_test.py https://portal.lab.local --username admin --insecure   # sertifikat self-signed

Kata sandi dibaca dari prompt tersembunyi (atau variabel lingkungan PORTAL_SMOKE_PASSWORD), tidak pernah dari argumen
baris perintah. Skrip tidak mengirim kata sandi salah untuk akun yang ada, sehingga tidak memicu penguncian akun.
Skrip ini hanya membaca halaman; tidak menjalankan workflow apa pun.
"""
from __future__ import annotations

import argparse
import getpass
import html
import http.cookiejar
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

OK, FAIL = "[ OK ]", "[GAGAL]"
failures = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global failures
    print(f"{OK if cond else FAIL} {label}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures += 1


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # we want to see 3xx ourselves
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_url", help="mis. http://127.0.0.1:8000 atau https://portal.lab.local")
    ap.add_argument("--username", required=True)
    ap.add_argument("--insecure", action="store_true", help="jangan verifikasi sertifikat TLS (self-signed di lab)")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    password = os.environ.get("PORTAL_SMOKE_PASSWORD") or getpass.getpass(f"Kata sandi {args.username}: ")

    ctx = ssl.create_default_context()
    if args.insecure:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    jar = http.cookiejar.CookieJar()
    follow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=ctx))
    stay = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=ctx), NoRedirect)

    def get(path, opener=follow):
        try:
            return opener.open(base + path, timeout=15)
        except urllib.error.HTTPError as e:
            return e

    # 1. server hidup
    try:
        r = get("/healthz")
    except Exception as e:  # noqa: BLE001
        print(f"{FAIL} Tidak dapat terhubung ke {base}: {e}")
        return 2
    check(r.status == 200 and r.read().strip() == b"ok", "healthz menjawab 'ok'")

    # 2. halaman login + header keamanan
    r = get("/login")
    page = r.read().decode()
    check(r.status == 200, "halaman login terbuka")
    check("frame-ancestors 'none'" in r.headers.get("Content-Security-Policy", ""), "header CSP terpasang")
    check(r.headers.get("X-Content-Type-Options") == "nosniff", "header X-Content-Type-Options terpasang")
    if base.startswith("https://"):
        check("max-age" in r.headers.get("Strict-Transport-Security", ""), "header HSTS terpasang (HTTPS)")
    check("MII - Hybrid AI Infrastructure Lab Topology" in page, "judul halaman login tampil")
    m = re.search(r'name="csrf_token" value="([^"]+)"', page)
    check(bool(m), "token CSRF login ada")
    if not m:
        return 1
    for asset in ("/static/img/login-topology.jpg", "/static/img/login-rack.jpg", "/static/css/app.css"):
        check(get(asset).status == 200, f"aset {asset} dapat diambil")

    def post_login(user, pw):
        data = urllib.parse.urlencode({"username": user, "password": pw, "csrf_token": m.group(1), "next": "/"}).encode()
        try:
            return stay.open(urllib.request.Request(base + "/login", data=data), timeout=15)
        except urllib.error.HTTPError as e:
            return e

    # 3. login ditolak untuk pengguna yang tidak ada (tidak mengunci akun nyata)
    r = post_login("pengguna-tidak-ada-xyz", "salah-salah-salah")
    check(r.status == 401, "login dengan pengguna tak dikenal ditolak (401)", f"status {r.status}")

    # 4. login sungguhan
    page2 = get("/login").read().decode()  # token baru untuk percobaan berikutnya
    m = re.search(r'name="csrf_token" value="([^"]+)"', page2)
    r = post_login(args.username, password)
    check(r.status == 303, "login berhasil (303)", f"status {r.status}; periksa nama pengguna/kata sandi")
    if r.status != 303:
        return 1
    cookies = {c.name: c for c in jar}
    sess = next((c for n, c in cookies.items() if n.endswith("portal_session")), None)
    check(sess is not None, "cookie sesi diterima")
    if sess is not None and base.startswith("https://"):
        check(sess.secure, "cookie sesi bertanda Secure")
        check(sess.has_nonstandard_attr("HttpOnly"), "cookie sesi bertanda HttpOnly")

    # 5. dashboard
    r = get("/")
    page = html.unescape(r.read().decode())
    check(r.status == 200 and "Cisco & Splunk Lab Portal" in page, "dashboard terbuka dengan judul portal")
    tiles = page.count('class="tile"')
    check(tiles == 8, "8 tile platform tampil", f"ditemukan {tiles}")
    check("Mode DRY-RUN" in page, "portal dalam mode DRY-RUN (aman)", "jika Anda memang memakai mode live, abaikan")

    # 6. halaman lain dapat dibuka
    for path, text in (("/p/nxos", "Cisco NX-OS"), ("/p/nxos/nxos-create-vlan", "Buat VLAN"),
                       ("/runs", "Riwayat")):
        r = get(path)
        check(r.status == 200 and text in r.read().decode(), f"halaman {path} terbuka")

    # 7. keluar
    page = get("/").read().decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)
    if token:
        data = urllib.parse.urlencode({"csrf_token": token.group(1)}).encode()
        try:
            r = stay.open(urllib.request.Request(base + "/logout", data=data), timeout=15)
        except urllib.error.HTTPError as e:
            r = e
        check(r.status == 303, "keluar berhasil")
        check(get("/", stay).status == 303, "setelah keluar, dashboard meminta login lagi")

    print("\nHasil:", "SEMUA LULUS" if not failures else f"{failures} pemeriksaan GAGAL")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
