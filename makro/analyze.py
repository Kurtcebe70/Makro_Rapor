"""Analiz katmanı: tamamen deterministik. Sayıları sadece burası üretir."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

STALE_DAYS = {"d": 6, "w": 16, "m": 75}
UNIT_CHANGE = {"pct": "bp", "idx": "%", "usd": "%", "num": "Δ"}


# ---------------------------------------------------------------- yardımcılar
def _pick_source(spec: str, raw: dict[str, pd.Series]) -> tuple[str, pd.Series] | tuple[None, None]:
    best = (None, None)
    for src in spec.split("|"):
        s = raw.get(src)
        if s is None or s.empty:
            continue
        if best[1] is None or s.index[-1] > best[1].index[-1]:
            best = (src, s)
    return best


def _transform(s: pd.Series, how: str | None) -> pd.Series:
    if how == "yoy":
        return (s.pct_change(12, fill_method=None) * 100).dropna()
    if how == "mdiff":
        return s.diff().dropna()
    return s


def _change(v: float, p: float | None, unit: str) -> float | None:
    if p is None or pd.isna(p):
        return None
    if unit == "pct":
        return round((v - p) * 100, 1)  # baz puan
    if unit in ("idx", "usd"):
        return round((v / p - 1) * 100, 2) if p else None
    return round(v - p, 3)


def _spark(s: pd.Series, freq: str) -> list[float]:
    n = {"d": 90, "w": 52, "m": 24}.get(freq, 60)
    return [round(float(x), 4) for x in s.tail(n).values]


def _rsi(s: pd.Series, n: int = 14) -> float | None:
    if len(s) < n + 1:
        return None
    d = s.diff().dropna()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up.iloc[-1] / dn.iloc[-1] if dn.iloc[-1] else np.inf
    return round(float(100 - 100 / (1 + rs)), 1)


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2) if b else 0.0


# ---------------------------------------------------------------- göstergeler
def build_metrics(cfg: dict, raw: dict[str, pd.Series], today: date) -> dict[str, dict]:
    metrics: dict[str, dict] = {}
    for g in cfg["gostergeler"]:
        src, s = _pick_source(g["kaynak"], raw)
        base = {**g, "kaynak_kullanilan": src, "ok": False}
        if s is None:
            metrics[g["anahtar"]] = base
            continue
        t = _transform(s, g.get("donusum"))
        if t.empty:
            metrics[g["anahtar"]] = base
            continue
        v = float(t.iloc[-1])
        p = float(t.iloc[-2]) if len(t) > 1 else None
        last_year = t[t.index >= t.index[-1] - pd.Timedelta(days=365)]
        lo, hi = float(last_year.min()), float(last_year.max())
        pos = round((v - lo) / (hi - lo) * 100) if hi > lo else 50
        # olağandışı hareket (günlük seriler): değişimin 1 yıllık std'ye oranı
        z = None
        if g.get("frekans") == "d" and len(last_year) > 60:
            ch = last_year.pct_change().dropna() if g["birim"] in ("idx", "usd") else last_year.diff().dropna()
            sd = float(ch.std())
            if sd > 0:
                z = round(float(ch.iloc[-1]) / sd, 1)
        age = (pd.Timestamp(today) - t.index[-1]).days
        metrics[g["anahtar"]] = {
            **base,
            "ok": True,
            "deger": round(v, 4),
            "onceki": None if p is None else round(p, 4),
            "tarih": t.index[-1].strftime("%Y-%m-%d"),
            "onceki_tarih": t.index[-2].strftime("%Y-%m-%d") if len(t) > 1 else None,
            "degisim": _change(v, p, g["birim"]),
            "degisim_birim": UNIT_CHANGE[g["birim"]],
            "yil_min": round(lo, 4), "yil_max": round(hi, 4), "yil_konum": pos,
            "z": z,
            "bayat": age > STALE_DAYS.get(g.get("frekans", "d"), 10),
            "spark": _spark(t, g.get("frekans", "d")),
        }
    return metrics


def build_derived(cfg: dict, raw: dict[str, pd.Series]) -> dict[str, dict]:
    """Özel metrikler: trend, genişlik, net likidite."""
    d: dict[str, dict] = {}
    spx = raw.get("yahoo:^GSPC")
    if spx is not None and len(spx) > 200:
        sma = spx.rolling(200).mean()
        d["spx_vs_200"] = {"ad": "S&P 500 / 200G ortalama", "deger": _pct(spx.iloc[-1], sma.iloc[-1]), "birim": "%"}

    gen = cfg.get("genislik", {})
    above, total, rows = 0, 0, []
    for sym in gen.get("sektor_etfleri", []):
        s = raw.get(f"yahoo:{sym}")
        if s is None or len(s) < 200:
            continue
        sma = s.rolling(200).mean().iloc[-1]
        up = bool(s.iloc[-1] > sma)
        above += up
        total += 1
        rows.append({"sembol": sym, "ustunde": up, "uzaklik": _pct(s.iloc[-1], sma),
                     "ay": _pct(s.iloc[-1], s.iloc[-22]) if len(s) > 22 else None})
    if total:
        d["breadth"] = {"ad": "Sektörlerin 200G üstünde olanı", "deger": round(above / total * 100), "birim": "%",
                        "detay": f"{above}/{total}", "sektorler": sorted(rows, key=lambda r: -(r["ay"] or 0))}

    rsp, spy = raw.get(f"yahoo:{gen.get('esit_agirlik', 'RSP')}"), raw.get(f"yahoo:{gen.get('piyasa', 'SPY')}")
    if rsp is not None and spy is not None:
        ratio = (rsp / spy).dropna()
        if len(ratio) > 64:
            d["rsp_rel_3m"] = {"ad": "Eşit ağırlık / S&P (3 ay)", "deger": _pct(ratio.iloc[-1], ratio.iloc[-64]), "birim": "%"}

    walcl, tga, rrp = raw.get("fred:WALCL"), raw.get("fred:WTREGEN"), raw.get("fred:RRPONTSYD")
    if walcl is not None and tga is not None and rrp is not None:
        idx = walcl.index
        nl = walcl - tga.reindex(idx, method="ffill") - rrp.reindex(idx, method="ffill") * 1000
        nl = nl.dropna()
        if len(nl) > 5:
            d["net_liq"] = {"ad": "Net Likidite ($ mr)", "deger": round(nl.iloc[-1] / 1000, 1), "birim": "$mr",
                            "tarih": nl.index[-1].strftime("%Y-%m-%d"),
                            "spark": [round(x / 1000, 1) for x in nl.tail(52).values]}
            d["net_liq_4w"] = {"ad": "Net Likidite 4 haftalık değişim", "deger": _pct(nl.iloc[-1], nl.iloc[-5]), "birim": "%"}
    return d


# ---------------------------------------------------------------- rejim
def _value(key: str, metrics: dict, derived: dict) -> float | None:
    if key in derived:
        return derived[key]["deger"]
    m = metrics.get(key)
    return m["deger"] if m and m.get("ok") else None


def score_signals(cfg: dict, metrics: dict, derived: dict) -> dict:
    sigs = []
    for s in cfg.get("sinyaller", []):
        v = _value(s["metrik"], metrics, derived)
        if v is None:
            continue
        if "yesil_alti" in s:
            g, r, low_good = s["yesil_alti"], s["kirmizi_ustu"], True
            puan = 1 if v < g else (-1 if v > r else 0)
        else:
            g, r, low_good = s["yesil_ustu"], s["kirmizi_alti"], False
            puan = 1 if v > g else (-1 if v < r else 0)
        width = abs(r - g) or 1
        asim = (v - r) / width if low_good else (r - v) / width  # >0 ise kırmızı eşiğin ötesinde
        ad = metrics.get(s["metrik"], {}).get("ad") or derived.get(s["metrik"], {}).get("ad") or s["metrik"]
        sigs.append({**s, "ad": ad, "deger": v, "puan": puan, "yesil": g, "kirmizi": r,
                     "dusuk_iyi": low_good, "asim": round(asim, 2)})

    ayaklar: dict[str, list] = {}
    for s in sigs:
        ayaklar.setdefault(s["ayak"], []).append(s["puan"])
    ayak_ozet = []
    for ad, puanlar in ayaklar.items():
        ort = sum(puanlar) / len(puanlar)
        ayak_ozet.append({"ad": ad, "skor": round((ort + 1) / 2 * 100), "n": len(puanlar),
                          "etiket": "Destekleyici" if ort > 0.33 else ("Baskılı" if ort < -0.33 else "Karışık")})
    tum = [s["puan"] for s in sigs]
    skor = round((sum(tum) / len(tum) + 1) / 2 * 100) if tum else 50
    rejim = "risk_on" if skor >= 60 else ("risk_off" if skor < 40 else "notr")
    etiket = {"risk_on": "Risk Açık", "notr": "Nötr / Karışık", "risk_off": "Risk Kapalı"}[rejim]
    return {"sinyaller": sigs, "ayaklar": ayak_ozet, "skor": skor, "rejim": rejim, "etiket": etiket}


# ---------------------------------------------------------------- uyarılar
def build_alerts(metrics: dict, regime: dict) -> list[dict]:
    alerts = []
    for s in regime["sinyaller"]:
        if s["puan"] == -1:
            seviye = "YÜKSEK" if s["asim"] > 0.5 else "ORTA"
            yon = "üstünde" if s["dusuk_iyi"] else "altında"
            alerts.append({"tur": "risk", "seviye": seviye, "baslik": f"{s['ad']} kırmızı bölgede",
                           "metin": f"{s['ad']} {fmt_num(s['deger'])} ile kırmızı eşik {fmt_num(s['kirmizi'])}'in {yon}. ({s['ayak']})",
                           "siralama": 2 if seviye == "YÜKSEK" else 1})
    for key, m in metrics.items():
        if m.get("ok") and m.get("z") is not None and abs(m["z"]) >= 2:
            alerts.append({"tur": "hareket", "seviye": "ORTA" if abs(m["z"]) >= 3 else "DÜŞÜK",
                           "baslik": f"{m['ad']}: olağandışı günlük hareket",
                           "metin": f"Son değişim {fmt_change(m)} — son bir yılın tipik günlük hareketinin {abs(m['z']):.1f} katı.",
                           "siralama": 0.5})
    firsat = [s for s in regime["sinyaller"] if s["puan"] == 1]
    for s in firsat[:4]:
        alerts.append({"tur": "destek", "seviye": "DESTEK", "baslik": f"{s['ad']} destekleyici",
                       "metin": f"{s['ad']} {fmt_num(s['deger'])} ile yeşil eşiğin ({fmt_num(s['yesil'])}) iyi tarafında.",
                       "siralama": -1})
    return sorted(alerts, key=lambda a: -a["siralama"])


# ---------------------------------------------------------------- senaryolar
def eval_scenarios(cfg: dict, metrics: dict, derived: dict) -> list[dict]:
    out = []
    for sc in cfg.get("senaryolar", []):
        kosullar, aktif = [], False
        for k in sc["kosullar"]:
            v = _value(k["metrik"], metrics, derived)
            ad = metrics.get(k["metrik"], {}).get("ad") or derived.get(k["metrik"], {}).get("ad") or k["metrik"]
            base = {"metrik": k["metrik"], "op": k["op"], "esik": k["deger"], "ad": ad, "mevcut": v}
            if v is None:
                kosullar.append({**base, "saglandi": False, "mesafe": None})
                continue
            if k["op"] == "<":
                ok, mesafe = v < k["deger"], v - k["deger"]
            elif k["op"] == ">":
                ok, mesafe = v > k["deger"], k["deger"] - v
            else:
                lo, hi = k["deger"]
                ok, mesafe = lo <= v <= hi, 0 if lo <= v <= hi else min(abs(v - lo), abs(v - hi))
            aktif = aktif or ok
            kosullar.append({**base, "saglandi": ok, "mesafe": round(mesafe, 3)})
        out.append({**sc, "kosullar": kosullar, "aktif": aktif})
    return out


# ---------------------------------------------------------------- portföy
def build_portfolio(cfg: dict, raw: dict, regime: dict) -> dict:
    port = cfg.get("portfoy", {})
    bench = raw.get(f"yahoo:{port.get('benchmark', 'SPY')}")
    zone = port.get("geri_cekilme_bolgesi", 20)
    rows = []
    for h in port.get("hisseler", []):
        s = raw.get(f"yahoo:{h['sembol']}")
        if s is None or len(s) < 30:
            rows.append({**h, "ok": False})
            continue
        y = s[s.index >= s.index[-1] - pd.Timedelta(days=365)]
        hi = float(y.max())
        sma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else None
        rel = None
        if bench is not None and len(bench) > 64:
            a = s.reindex(bench.index, method="ffill").dropna()
            b = bench.reindex(a.index)
            if len(a) > 64:
                rel = round(_pct(a.iloc[-1], a.iloc[-64]) - _pct(b.iloc[-1], b.iloc[-64]), 1)
        dd = _pct(s.iloc[-1], hi)
        rsi = _rsi(s)
        isaretler = []
        if -dd >= zone:
            isaretler.append(("zone", f"Geri çekilme bölgesi (zirveden %{abs(dd):.0f})"))
        if sma200 is not None:
            isaretler.append(("up" if s.iloc[-1] > sma200 else "down",
                              "200G üstünde" if s.iloc[-1] > sma200 else "200G altında"))
        if rsi is not None and rsi >= 70:
            isaretler.append(("hot", f"RSI {rsi:.0f} · aşırı ısınmış"))
        elif rsi is not None and rsi <= 30:
            isaretler.append(("zone", f"RSI {rsi:.0f} · aşırı satım"))
        rows.append({**h, "ok": True, "fiyat": round(float(s.iloc[-1]), 2), "tarih": s.index[-1].strftime("%Y-%m-%d"),
                     "gun": _pct(s.iloc[-1], s.iloc[-2]), "ay": _pct(s.iloc[-1], s.iloc[-22]) if len(s) > 22 else None,
                     "zirveden": dd, "sma200_uzaklik": _pct(s.iloc[-1], sma200) if sma200 else None,
                     "rsi": rsi, "rel_3m": rel, "isaretler": isaretler,
                     "spark": [round(float(x), 2) for x in s.tail(90).values]})
    return {"hisseler": rows, "dca_notu": port.get("dca_kurallari", {}).get(regime["rejim"], ""),
            "bolge": zone, "benchmark": port.get("benchmark", "SPY")}


# ---------------------------------------------------------------- dünden bu yana
def diff_vs_previous(today_rec: dict, prev_rec: dict | None, metrics: dict) -> list[str]:
    if not prev_rec:
        return ["İlk rapor — karşılaştırılacak önceki kayıt yok."]
    out = []
    if prev_rec.get("skor") is not None and prev_rec["skor"] != today_rec["skor"]:
        out.append(f"Rejim skoru {prev_rec['skor']} → {today_rec['skor']} ({today_rec['etiket']}).")
    ps, ts = prev_rec.get("sinyal", {}), today_rec["sinyal"]
    renk = {1: "yeşil", 0: "sarı", -1: "kırmızı"}
    for k, v in ts.items():
        if k in ps and ps[k] != v:
            ad = metrics.get(k, {}).get("ad", k)
            out.append(f"{ad} sinyali {renk[ps[k]]} → {renk[v]} oldu.")
    for k in ("vix", "us10y", "dxy", "brent", "hy", "spx"):
        m = metrics.get(k)
        pv = prev_rec.get("deger", {}).get(k)
        if m and m.get("ok") and pv is not None and pv != m["deger"]:
            out.append(f"{m['ad']}: {fmt_val(m, pv)} → {fmt_val(m, m['deger'])}.")
    return out or ["Önceki rapordan bu yana kayda değer değişiklik yok."]


def history_record(regime: dict, metrics: dict) -> dict:
    return {"skor": regime["skor"], "etiket": regime["etiket"],
            "sinyal": {s["metrik"]: s["puan"] for s in regime["sinyaller"]},
            "deger": {k: m["deger"] for k, m in metrics.items() if m.get("ok")}}


# ---------------------------------------------------------------- biçimlendirme (TR)
def fmt_num(x: float | None, nd: int | None = None) -> str:
    if x is None:
        return "—"
    if nd is None and isinstance(x, int):
        nd = 0
    if nd is None:
        ax = abs(x)
        nd = 0 if ax >= 10000 else (1 if ax >= 1000 else 2)
    s = f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s.replace("-", "−")


def fmt_val(m: dict, v: float | None = None) -> str:
    v = m["deger"] if v is None else v
    if m["birim"] == "pct":
        return "%" + fmt_num(v, 2)
    if m["birim"] == "usd":
        return fmt_num(v, 2) + " $"
    return fmt_num(v)


def fmt_change(m: dict) -> str:
    c = m.get("degisim")
    if c is None:
        return "—"
    if m["degisim_birim"] == "bp" and round(abs(c)) == 0:
        return "±0 bp"
    sign = "+" if c > 0 else ("−" if c < 0 else "±")
    if m["degisim_birim"] == "bp":
        return f"{sign}{fmt_num(abs(c), 0)} bp"
    if m["degisim_birim"] == "%":
        return f"{sign}%{fmt_num(abs(c), 2)}"
    return f"{sign}{fmt_num(abs(c))}"


def analyze(cfg: dict, raw: dict, today: date, prev_rec: dict | None) -> dict:
    metrics = build_metrics(cfg, raw, today)
    derived = build_derived(cfg, raw)
    regime = score_signals(cfg, metrics, derived)
    rec = history_record(regime, metrics)
    return {
        "tarih": today.isoformat(),
        "metrics": metrics,
        "derived": derived,
        "regime": regime,
        "alerts": build_alerts(metrics, regime),
        "scenarios": eval_scenarios(cfg, metrics, derived),
        "portfolio": build_portfolio(cfg, raw, regime),
        "degisenler": diff_vs_previous(rec, prev_rec, metrics),
        "kayit": rec,
    }
