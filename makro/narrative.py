"""Yorum katmanı. Claude yalnızca hazır sayıları yorumlar; yeni sayı üretmez.
ANTHROPIC_API_KEY yoksa kural tabanlı şablon metin kullanılır."""
from __future__ import annotations

import json
import os
import re

import requests

from .analyze import fmt_change, fmt_num, fmt_val

SYSTEM = """Sen deneyimli bir makro stratejistsin ve Türkçe günlük makro rapor yazıyorsun.
KESİN KURALLAR:
- Sadece sana verilen JSON'daki sayıları kullan. Yeni sayı, tarih, olay, haber veya tahmin UYDURMA.
- Veride olmayan bir şeyden (haber, Fed konuşması, jeopolitik olay) bahsetme.
- Yatırım tavsiyesi verme; "al/sat" deme. Portföy notunda sadece verideki kural işaretlerini yorumla.
- Sade, akıcı Türkçe. Jargon kullanırsan parantez içinde kısaca açıkla.
- Çıktı yalnızca geçerli JSON olsun, başka hiçbir şey yazma."""

USER_TMPL = """Bugünün deterministik verisi:
```json
{facts}
```
Şu JSON şemasıyla yanıt ver:
{{
  "ozet": "2-3 cümlelik genel tablo",
  "hikaye": ["3-4 madde: günün ana makro hikayesi, her biri 1-2 cümle"],
  "teknik": "2-3 cümle: teknik sağlık skoru, trend/genişlik/rotasyon/hacim tablosunun özeti ve makro tabloyla uyumu ya da çelişkisi",
  "portfoy": "MODEL V7.0 adayları için 2-3 cümle: makro rejim bu temaları nasıl etkiliyor, hangi kural işaretleri öne çıkıyor",
  "izle": ["2-4 madde: senaryo eşiklerine göre bundan sonra izlenecek seviyeler"]
}}"""


def compact_facts(a: dict) -> dict:
    m = a["metrics"]
    return {
        "tarih": a["tarih"],
        "rejim": {"skor": a["regime"]["skor"], "etiket": a["regime"]["etiket"],
                  "ayaklar": [{k: x[k] for k in ("ad", "skor", "etiket")} for x in a["regime"]["ayaklar"]]},
        "gostergeler": {x["ad"]: {"deger": fmt_val(x), "degisim": fmt_change(x), "veri_tarihi": x["tarih"],
                                  "1y_aralik_konum_%": x["yil_konum"], "bayat": x["bayat"]}
                        for x in m.values() if x.get("ok")},
        "turetilmis": {v["ad"]: f"{fmt_num(v['deger'])} {v['birim']}" for v in a["derived"].values()},
        "uyarilar": [f"[{x['seviye']}] {x['baslik']}: {x['metin']}" for x in a["alerts"]],
        "senaryolar": [{"ad": s["ad"], "aktif": s["aktif"],
                        "kosullar": [_cond_text(k) for k in s["kosullar"]]}
                       for s in a["scenarios"]],
        "portfoy": [{"sembol": h["sembol"], "tema": h["tema"], "gun_%": h.get("gun"), "ay_%": h.get("ay"),
                     "zirveden_%": h.get("zirveden"), "sma200_uzaklik_%": h.get("sma200_uzaklik"),
                     "rsi": h.get("rsi"), "spy_gore_3ay_%": h.get("rel_3m"),
                     "isaretler": [t for _, t in h.get("isaretler", [])]} for h in a["portfolio"]["hisseler"] if h.get("ok")],
        "dca_kurali": a["portfolio"]["dca_notu"],
        "onceki_rapordan_degisenler": a["degisenler"],
        "manuel_notlar": a.get("manuel", {}),
        "teknik": _tech_facts(a.get("teknik") or {}),
    }


def _tech_facts(t: dict) -> dict:
    if not t:
        return {}
    return {
        "saglik_skoru": t["saglik"]["skor"], "saglik_etiket": t["saglik"]["etiket"],
        "ayaklar": {k: f"{v['puan']}/10 · {v['not']}" for k, v in t["saglik"]["ayaklar"].items()},
        "endeksler": [{"sembol": r["sembol"], "fiyat": r["fiyat"], "evre": r["evre_ad"], "rsi": r["rsi"],
                       "ay_%": r["ay"], "ustunde_oldugu_ortalamalar": [f"{n}G" for n in r["ma_ust"]],
                       "ortalamalar": {f"{n}G": v for n, v in r["ma"].items()}} for r in t["endeksler"]],
        "grafik_okumalari": [g["okuma"] for g in t["grafikler"]],
        "rotasyon": [f"{r['sembol']}: {r['kadran_ad']}, skor {r['skor']}, SPY'ye göre 1A {r['rel_1a']}%" for r in t["rotasyon"]],
        "hacim": t["hacim"]["sonuc"],
        "momentum_stresi": t.get("momentum_stres"),
        "vix_yapisi": t.get("vix"),
        "takvim": t.get("takvim"),
        "bilanco_manuel": t.get("bilanco"),
        "izleme_sirasi": [f"[{w['seviye']}] {w['metin']}" for w in t["izleme"]],
    }


def _threshold_text(k: dict) -> str:
    """Koşul eşiğini okunur yaz. Not: analyze, eşiği 'deger' anahtarının üzerine
    mevcut değerle yazmasın diye eşik 'esik' alanında tutulur."""
    e = k["esik"]
    if k["op"] == "between":
        return f"{fmt_num(e[0])}–{fmt_num(e[1])} arası"
    return f"{k['op']} {fmt_num(e)}"


def _cond_text(k: dict) -> str:
    now = fmt_num(k["mevcut"]) if k.get("mevcut") is not None else "—"
    return f"{k['ad']} {_threshold_text(k)} (şu an {now}, {'sağlandı' if k['saglandi'] else 'sağlanmadı'})"


def template_narrative(a: dict) -> dict:
    r = a["regime"]
    risks = [x for x in a["alerts"] if x["tur"] == "risk"]
    supports = [x for x in a["alerts"] if x["tur"] == "destek"]
    ayak = sorted(r["ayaklar"], key=lambda x: x["skor"])
    ozet = f"Makro rejim skoru {r['skor']}/100 ile '{r['etiket']}' bölgesinde."
    if ayak:
        ozet += f" En zayıf ayak {ayak[0]['ad']} ({ayak[0]['skor']}), en güçlü ayak {ayak[-1]['ad']} ({ayak[-1]['skor']})."
    hikaye = [x["metin"] for x in risks[:2]] + [x["metin"] for x in supports[:2]]
    aktif = [s["ad"] for s in a["scenarios"] if s["aktif"]]
    izle = []
    for s in a["scenarios"]:
        for k in s["kosullar"]:
            if k["mevcut"] is not None and not k["saglandi"]:
                izle.append(f"{k['ad']} şu an {fmt_num(k['mevcut'])}; "
                            f"{s['ad'].split('·')[0].strip()} senaryosu için {_threshold_text(k)}.")
    flags = [f"{h['sembol']}: {', '.join(t for _, t in h['isaretler'])}" for h in a["portfolio"]["hisseler"] if h.get("ok") and h["isaretler"]]
    portfoy = ("Öne çıkan işaretler — " + " · ".join(flags)) if flags else ""
    if aktif:
        hikaye.append("Şu an geçerli senaryo: " + ", ".join(aktif) + ".")
    teknik = ""
    t = a.get("teknik") or {}
    if t:
        ay = sorted(t["saglik"]["ayaklar"].items(), key=lambda kv: kv[1]["puan"])
        teknik = (f"Teknik sağlık skoru {t['saglik']['skor']}/100 ({t['saglik']['etiket']}). "
                  f"En güçlü ayak {ay[-1][0]} ({ay[-1][1]['puan']}/10: {ay[-1][1]['not']}), "
                  f"en zayıf ayak {ay[0][0]} ({ay[0][1]['puan']}/10: {ay[0][1]['not']}). {t['hacim']['sonuc']}")
    return {"ozet": ozet, "hikaye": hikaye or ["Belirgin bir risk veya destek sinyali yok."],
            "teknik": teknik, "portfoy": portfoy, "izle": izle[:4], "kaynak": "şablon"}


def claude_narrative(a: dict, model: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    facts = json.dumps(compact_facts(a), ensure_ascii=False, default=str)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 1500, "system": SYSTEM,
                  "messages": [{"role": "user", "content": USER_TMPL.format(facts=facts)}]},
            timeout=90,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0))
        out["kaynak"] = f"Claude ({model})"
        return out
    except Exception as e:
        print(f"  ! Claude yorumu alınamadı, şablona dönülüyor: {e}")
        return None


def narrative(a: dict, cfg: dict) -> dict:
    return claude_narrative(a, cfg["rapor"].get("claude_model", "claude-sonnet-5")) or template_narrative(a)
