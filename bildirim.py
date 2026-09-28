#!/usr/bin/env python3
"""Günlük makro raporun özetini Telegram'a gönderir.

Gerekli GitHub sırları (Settings → Secrets and variables → Actions):
  TELEGRAM_BOT_TOKEN  — @BotFather'dan alınan bot anahtarı
  TELEGRAM_CHAT_ID    — mesajın gideceği sohbet numarası
Sırlar yoksa sessizce atlar; rapor üretimini asla bozmaz.
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

import requests

from makro.analyze import fmt_change, fmt_num, fmt_val

ROOT = Path(__file__).parent
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def site_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")  # ör. Kurtcebe70/Makro_Rapor
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def e(x) -> str:
    return html.escape(str(x), quote=False)


def yuzde(x: float | None) -> str:
    if x is None:
        return "—"
    if round(abs(x), 1) == 0:
        return "%0,0"
    return f"{'+' if x > 0 else '−'}%{fmt_num(abs(x), 1)}"


def mesaj() -> str:
    d = json.loads((ROOT / "data" / "son_analiz.json").read_text())
    a, yorum = d["analiz"], d["yorum"]
    r, t = a["regime"], a.get("teknik") or {}
    y, m, g = a["tarih"].split("-")
    satirlar = [f"📊 <b>Makro Rapor · {int(g)} {AYLAR[int(m) - 1]}</b>", ""]
    satirlar.append(f"Makro rejim: <b>{r['skor']}/100</b> · {e(r['etiket'])}")
    if t.get("saglik"):
        satirlar.append(f"Teknik sağlık: <b>{t['saglik']['skor']}/100</b> · {e(t['saglik']['etiket'])}")
    satirlar.append("")

    ozet = []
    for k in ("spx", "ndx", "us10y", "vix", "dxy", "brent", "gold"):
        mt = a["metrics"].get(k)
        if mt and mt.get("ok"):
            ozet.append(f"{e(mt['ad'])} {e(fmt_val(mt))} ({e(fmt_change(mt))})")
    if ozet:
        satirlar += ["<b>Piyasa</b>", *[f"• {x}" for x in ozet], ""]

    uyarilar = [x for x in a["alerts"] if x["tur"] in ("risk", "hareket")][:3]
    if uyarilar:
        satirlar.append("<b>⚠️ Öne çıkanlar</b>")
        satirlar += [f"• [{e(x['seviye'])}] {e(x['baslik'])}" for x in uyarilar]
        satirlar.append("")

    izleme = (t.get("izleme") or [])[:3]
    if izleme:
        satirlar.append("<b>👀 İzleme</b>")
        satirlar += [f"• {e(w['metin'])}" for w in izleme]
        satirlar.append("")

    aktif = [s["ad"] for s in a["scenarios"] if s["aktif"]]
    if aktif:
        satirlar.append(f"🎯 Senaryo: {e(', '.join(aktif))}")

    port = [h for h in a["portfolio"]["hisseler"] if h.get("ok")]
    if port:
        satirlar.append("")
        satirlar.append("<b>💼 Portföy</b>")
        for h in port:
            gun = h.get("gun")
            isaret = [txt for tur, txt in h.get("isaretler", []) if tur in ("zone", "hot", "down")]
            satirlar.append(f"• {e(h['sembol'])} {fmt_num(h['fiyat'], 2)} ({yuzde(gun)})"
                            + (f" — {e(', '.join(isaret))}" if isaret else ""))
        if a["portfolio"].get("dca_notu"):
            satirlar.append(f"<i>{e(a['portfolio']['dca_notu'])}</i>")

    if yorum.get("ozet"):
        satirlar += ["", e(yorum["ozet"])]
    url = site_url()
    if url:
        satirlar += ["", f'🔗 <a href="{url}">Raporun tamamı</a>']
    return "\n".join(satirlar)[:4000]


def main() -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Telegram sırları tanımlı değil — bildirim atlandı.")
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": mesaj(), "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        print("Telegram:", "gönderildi ✓" if r.ok else f"hata {r.status_code} {r.text[:200]}")
    except Exception as ex:  # bildirim hatası raporu bozmasın
        print(f"Telegram bildirimi gönderilemedi: {ex}", file=sys.stderr)


if __name__ == "__main__":
    main()
