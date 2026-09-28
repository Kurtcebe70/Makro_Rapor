"""Teknik görünüm katmanı (MarketPulse benzeri). Tamamen deterministik."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .analyze import _pct, _rsi, fmt_num

EVRE_AD = {1: "Evre 1 · Taban", 2: "Evre 2 · Yükseliş", 3: "Evre 3 · Tepe", 4: "Evre 4 · Düşüş"}
KADRAN = {"lider": "Lider", "zayif": "Zayıflayan", "geride": "Geride", "gucl": "Güçlenen"}


def _s(raw: dict, sym: str, vol: bool = False) -> pd.Series | None:
    s = raw.get(f"{'yahoo_vol' if vol else 'yahoo'}:{sym}")
    return s if s is not None and len(s) else None


def _sma(s: pd.Series, n: int) -> float | None:
    return float(s.tail(n).mean()) if len(s) >= n else None


# ------------------------------------------------------------------ trend evresi
def stage(s: pd.Series) -> int:
    """Weinstein evresi: 150 günlük (30 haftalık) ortalama ve eğimi."""
    if len(s) < 175:
        return 1
    sma = s.rolling(150).mean()
    slope = (sma.iloc[-1] / sma.iloc[-21] - 1) * 100  # son ~1 ayda ortalamanın eğimi (%)
    above = s.iloc[-1] > sma.iloc[-1]
    if above and slope > 0.3:
        return 2
    if not above and slope < -0.3:
        return 4
    return 3 if above or slope > 0 else 1


def index_rows(cfg: dict, raw: dict) -> list[dict]:
    rows = []
    for sym in cfg["teknik"]["trend_endeksleri"]:
        s = _s(raw, sym)
        if s is None or len(s) < 60:
            continue
        p = float(s.iloc[-1])
        mas = {n: _sma(s, n) for n in (10, 21, 50, 200)}
        ust = [n for n, v in mas.items() if v is not None and p > v]
        ev = stage(s)
        rows.append({"sembol": sym, "fiyat": round(p, 2), "gun": _pct(s.iloc[-1], s.iloc[-2]),
                     "ay": _pct(s.iloc[-1], s.iloc[-22]), "rsi": _rsi(s),
                     "ma": {n: (round(v, 2) if v else None) for n, v in mas.items()},
                     "ma_ust": ust, "evre": ev, "evre_ad": EVRE_AD[ev],
                     "zirveden": _pct(p, float(s.tail(252).max()))})
    return rows


# ------------------------------------------------------------------ grafik
def chart_data(cfg: dict, raw: dict, n: int = 60) -> list[dict]:
    out = []
    for sym in cfg["teknik"]["grafikler"]:
        s = _s(raw, sym)
        if s is None or len(s) < 210:
            continue
        lines = {"Fiyat": s}
        for k in (10, 21, 50, 200):
            lines[f"{k}G"] = s.rolling(k).mean()
        tail = {k: [round(float(x), 2) for x in v.tail(n).values] for k, v in lines.items()}
        p = float(s.iloc[-1])
        last = {k: v[-1] for k, v in tail.items()}
        ustte = [k for k in ("10G", "21G", "50G", "200G") if p > last[k]]
        dizilim = last["10G"] > last["21G"] > last["50G"] > last["200G"]
        ters = last["10G"] < last["21G"] < last["50G"] < last["200G"]
        if len(ustte) == 4:
            okuma = f"{sym} {fmt_num(p, 2)} ile 10, 21, 50 ve 200 günlük ortalamaların hepsinin üstünde."
        elif not ustte:
            okuma = f"{sym} {fmt_num(p, 2)} ile tüm ana ortalamaların altında."
        else:
            alt = [k for k in ("10G", "21G", "50G", "200G") if k not in ustte]
            okuma = f"{sym} {fmt_num(p, 2)} · üstünde: {', '.join(ustte)} · altında: {', '.join(alt)}."
        okuma += (" Kısa ortalamalar uzunların üstünde sıralı — dizilim boğa tarafında." if dizilim else
                  " Ortalamalar ters sıralı — dizilim ayı tarafında." if ters else
                  " Ortalama dizilimi karışık.")
        dates = [d.strftime("%d.%m") for d in s.tail(n).index]
        out.append({"sembol": sym, "fiyat": p, "gun": _pct(s.iloc[-1], s.iloc[-2]), "seriler": tail,
                    "son": last, "okuma": okuma, "ilk_tarih": dates[0], "orta_tarih": dates[len(dates) // 2],
                    "son_tarih": dates[-1]})
    return out


# ------------------------------------------------------------------ rotasyon
def rotation(cfg: dict, raw: dict) -> list[dict]:
    spy = _s(raw, "SPY")
    if spy is None:
        return []
    rows = []
    for sym in cfg["teknik"]["rotasyon_evreni"]:
        s = _s(raw, sym)
        if s is None or len(s) < 140:
            continue
        a = s.reindex(spy.index, method="ffill").dropna()
        rs = a / spy.reindex(a.index)
        trend_series = (rs / rs.rolling(50).mean() - 1) * 100
        trend = float(trend_series.iloc[-1])
        mom = float(trend_series.iloc[-1] - trend_series.iloc[-11])
        k = ("lider" if trend > 0 and mom > 0 else "zayif" if trend > 0 else
             "geride" if mom < 0 else "gucl")
        r1, r3, r6 = (_pct(a.iloc[-1], a.iloc[-n]) - _pct(spy.iloc[-1], spy.iloc[-n]) for n in (22, 64, 127))
        ev = stage(s)
        rows.append({"sembol": sym, "trend": round(trend, 2), "mom": round(mom, 2), "kadran": k,
                     "kadran_ad": KADRAN[k], "rel_1a": round(r1, 1), "rel_3a": round(r3, 1),
                     "rel_6a": round(r6, 1), "evre": ev, "evre_ad": EVRE_AD[ev],
                     "sma200": _sma(s, 200), "fiyat": round(float(s.iloc[-1]), 2),
                     "_kompozit": 0.5 * r1 + 0.3 * r3 + 0.2 * r6})
    if rows:
        ranks = pd.Series([r["_kompozit"] for r in rows]).rank(pct=True)
        for r, pr in zip(rows, ranks):
            r["skor"] = int(round(pr * 100))
            del r["_kompozit"]
    return sorted(rows, key=lambda r: -r["skor"])


# ------------------------------------------------------------------ hacim
def volume_panel(cfg: dict, raw: dict) -> dict:
    items = []
    for sym in cfg["teknik"]["hacim_sembolleri"]:
        v = _s(raw, sym, vol=True)
        c = _s(raw, sym)
        if v is None or len(v) < 22:
            continue
        v = v[v > 0]
        med = float(v.iloc[-21:-1].median())
        last, prev = float(v.iloc[-1]), float(v.iloc[-2])
        items.append({"sembol": sym, "ad": {"^IXIC": "Nasdaq", "^NYA": "NYSE"}.get(sym, sym),
                      "genel": sym.startswith("^"), "hacim": last, "degisim": _pct(last, prev),
                      "fark": last - prev, "oran": round(last / med * 100) if med else None,
                      "medyan": med, "bars": [float(x) for x in v.tail(20).values],
                      "tarih": v.index[-1].strftime("%Y-%m-%d"),
                      "fiyat_gun": _pct(c.iloc[-1], c.iloc[-2]) if c is not None and len(c) > 1 else None})
    genel = [i for i in items if i["genel"]]
    sonuc, ton = "Hacim verisi yetersiz.", "neu"
    if genel:
        top_oran = round(sum(i["hacim"] for i in genel) / sum(i["medyan"] for i in genel) * 100)
        spy_g = next((i["fiyat_gun"] for i in items if i["sembol"] == "SPY"), None)
        if top_oran >= 120 and spy_g is not None and spy_g > 0.3:
            sonuc, ton = "Alıcı baskın — yükseliş ortalama üstü hacimle geldi.", "pos"
        elif top_oran >= 120 and spy_g is not None and spy_g < -0.3:
            sonuc, ton = "Satıcı baskın — düşüş ortalama üstü hacimle geldi.", "neg"
        elif top_oran < 85:
            sonuc, ton = "İnce hacim — hareketin teyidi zayıf.", "neu"
        else:
            sonuc, ton = "Sessiz gün — ne alıcı ne satıcı baskın.", "neu"
        sonuc += f" Piyasa toplam hacmi (Nasdaq+NYSE) 20 günlük medyanın %{top_oran}'i"
        if spy_g is not None:
            sonuc += f" · SPY {'+' if spy_g >= 0 else '−'}%{fmt_num(abs(spy_g), 2)}"
        sonuc += "."
    return {"kalemler": items, "sonuc": sonuc, "ton": ton}


# ------------------------------------------------------------------ momentum stresi / duyarlılık
def momentum_stress(cfg: dict, raw: dict) -> dict | None:
    m, spy = _s(raw, cfg["teknik"].get("momentum_etf", "MTUM")), _s(raw, "SPY")
    if m is None or spy is None or len(m) < 70:
        return None
    vol = lambda s: float(s.pct_change().tail(60).std() * np.sqrt(252) * 100)
    vm, vs = vol(m), vol(spy)
    oran = vm / vs if vs else 0
    th = cfg["teknik"].get("momentum_stres", {"yuksek": 1.4, "asiri": 1.8})
    etiket = "aşırı stres" if oran >= th["asiri"] else ("yüksek" if oran >= th["yuksek"] else "normal")
    return {"mtum_vol": round(vm, 2), "spy_vol": round(vs, 2), "oran": round(oran, 2), "etiket": etiket,
            "esikler": th}


def vix_structure(cfg: dict, raw: dict) -> dict | None:
    v, v3 = _s(raw, "^VIX"), _s(raw, cfg["teknik"].get("vix3m", "^VIX3M"))
    if v is None:
        return None
    out = {"vix": round(float(v.iloc[-1]), 2)}
    if v3 is not None:
        r = float(v.iloc[-1] / v3.iloc[-1])
        out.update({"vix3m": round(float(v3.iloc[-1]), 2), "oran": round(r, 2),
                    "yapi": "contango (sakin)" if r < 0.95 else ("ters yapı (stres)" if r > 1.0 else "düz")})
    return out


# ------------------------------------------------------------------ takvim
def third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def calendar(cfg: dict, manuel: dict, today: date) -> dict:
    opex = third_friday(today.year, today.month)
    if opex < today:
        y, m = (today.year + (today.month == 12), today.month % 12 + 1)
        opex = third_friday(y, m)
    is_gunu = int(np.busday_count(today, opex))
    pencere = cfg["teknik"].get("vade_penceresi_gun", 3)
    ceyrek = opex.month in (3, 6, 9, 12)
    fomc = sorted(str(f["toplanti"]) for f in (manuel.get("fedwatch") or []) if str(f["toplanti"]) >= today.isoformat())
    fomc_gun = (date.fromisoformat(fomc[0]) - today).days if fomc else None
    return {"opex": opex.isoformat(), "opex_is_gunu": is_gunu, "opex_takvim_gunu": (opex - today).days,
            "ceyreklik": ceyrek, "pencere_acik": is_gunu <= pencere,
            "fomc": fomc[0] if fomc else None, "fomc_gun": fomc_gun}


# ------------------------------------------------------------------ sağlık skoru
def _clamp(x: float) -> float:
    return max(0.0, min(10.0, x))


def health(cfg: dict, idx: list[dict], rot: list[dict], breadth: dict | None, rsp_rel: float | None,
           mstress: dict | None, vixs: dict | None, bilanco: dict | None) -> dict:
    parts: dict[str, dict] = {}
    if idx:
        ev_puan = {2: 1.0, 1: 0.5, 3: 0.5, 4: 0.0}
        n2 = sum(r["evre"] == 2 for r in idx)
        parts["Trend"] = {"puan": _clamp(10 * np.mean([ev_puan[r["evre"]] for r in idx])),
                          "not": f"{len(idx)} endeksin {n2}'si Evre 2 yükselişte"}

        def mscore(r):
            rsi = r["rsi"] or 50
            a = 1.0 if 50 <= rsi < 70 else (0.7 if rsi >= 70 else (0.5 if rsi >= 40 else 0.0))
            return (a + (1.0 if r["ay"] > 0 else 0.0)) / 2
        m = 10 * np.mean([mscore(r) for r in idx])
        guclu = [r["sembol"] for r in idx if mscore(r) >= 0.85]
        if mstress and mstress["etiket"] != "normal":
            m -= 2 if mstress["etiket"] == "aşırı stres" else 1
        parts["Momentum"] = {"puan": _clamp(m), "not": ("Güçlü: " + ", ".join(guclu) if guclu else "Güçlü endeks yok")
                             + (f" · faktör stresi {mstress['etiket']}" if mstress and mstress["etiket"] != "normal" else "")}
    if breadth:
        sekt = breadth.get("sektorler", [])
        a200 = breadth["deger"] / 100
        a50 = np.mean([1.0 if r.get("ust50") else 0.0 for r in sekt]) if sekt else a200
        iwm = next((r for r in idx if r["sembol"] == "IWM"), None)
        iwm50 = 1.0 if iwm and 50 in iwm["ma_ust"] else 0.0
        g = 10 * (0.5 * a200 + 0.3 * a50 + 0.1 * (1.0 if (rsp_rel or 0) > 0 else 0.0) + 0.1 * iwm50)
        parts["Genişlik"] = {"puan": _clamp(g), "not": f"Sektörlerin %{round(a200 * 100)}'ı 200G, %{round(a50 * 100)}'ı 50G üstünde"}
    if bilanco and bilanco.get("hbk_tutturma") is not None:
        b, ort = bilanco["hbk_tutturma"], bilanco.get("hbk_5y_ort") or 77
        p = 9 if b >= ort + 5 else (7 if b >= ort else (4 if b >= ort - 5 else 2))
        if bilanco.get("ceyrek_buyume") is not None and bilanco.get("ceyrek_buyume_onceki") is not None:
            p += 1 if bilanco["ceyrek_buyume"] > bilanco["ceyrek_buyume_onceki"] else -1
        parts["Bilanço"] = {"puan": _clamp(p), "not": f"HBK tutturma %{fmt_num(b, 1)} (5Y ort. %{fmt_num(ort, 0)})"}
    if rot:
        saldiri = [r for r in rot if r["sembol"] in cfg["teknik"].get("saldirgan", [])]
        savunma = [r for r in rot if r["sembol"] in cfg["teknik"].get("savunmaci", [])]
        up = lambda rs: np.mean([r["kadran"] in ("lider", "gucl") for r in rs]) if rs else 0.5
        parts["Rotasyon"] = {"puan": _clamp(10 * (0.7 * up(saldiri) + 0.3 * (1 - up(savunma)))),
                             "not": f"{sum(r['kadran'] == 'lider' for r in rot)} lider · "
                                    f"{sum(r['kadran'] == 'gucl' for r in rot)} güçlenen · "
                                    f"{sum(r['kadran'] == 'zayif' for r in rot)} zayıflayan"}
    if vixs:
        v = vixs["vix"]
        d = 8 if v < 15 else (6 if v < 20 else (4 if v < 25 else 2))
        if vixs.get("oran") is not None:
            d += 1 if vixs["oran"] < 0.95 else (-2 if vixs["oran"] > 1.0 else 0)
        parts["Duyarlılık"] = {"puan": _clamp(d), "not": f"VIX {fmt_num(v, 2)}" + (f" · vade yapısı {vixs['yapi']}" if vixs.get("yapi") else "")}

    w = cfg["teknik"].get("agirliklar", {})
    tw = sum(w.get(k, 0) for k in parts)
    skor = round(sum(parts[k]["puan"] * w.get(k, 0) for k in parts) / tw * 10) if tw else 50
    etiket = ("Güçlü iyimserlik" if skor >= 75 else "Dikkatli iyimserlik" if skor >= 60 else
              "Kararsız" if skor >= 45 else "Temkinli" if skor >= 30 else "Zayıf")
    for k, v in parts.items():
        v["puan"] = round(float(v["puan"]), 1)
        v["agirlik"] = w.get(k, 0)
    return {"skor": skor, "etiket": etiket, "ayaklar": parts}


# ------------------------------------------------------------------ izleme sırası
def watchlist(idx: list[dict], rot: list[dict], mstress: dict | None, cal: dict,
              prev_rot: dict | None, portfolio: list[dict]) -> list[dict]:
    out = []
    kirik = [r for r in rot if r["evre"] == 4]
    if kirik:
        out.append({"seviye": "YÜKSEK", "metin": "Kırık trend (Evre 4): " + ", ".join(
            f"{r['sembol']} (200G {fmt_num(r['sma200'], 2)})" for r in kirik[:4] if r["sma200"])
            + " — 200 günlük ortalama geri alınana kadar zayıf kadro sayılır."})
    if mstress and mstress["etiket"] != "normal":
        out.append({"seviye": "ORTA", "metin": f"Momentum faktör stresi {mstress['etiket']}: MTUM/SPY oynaklık oranı "
                    f"{fmt_num(mstress['oran'], 2)} (eşik {fmt_num(mstress['esikler']['yuksek'], 1)}). Kalabalık momentum pozisyonlarında hareket sertleşebilir."})
    for r in idx:
        ma50 = r["ma"].get(50)
        if ma50 is None:
            continue
        if 50 in r["ma_ust"] and r["sembol"] in ("SPY", "QQQ"):
            out.append({"seviye": "ORTA", "metin": f"{r['sembol']} için {fmt_num(ma50, 2)} (50G) ilk izleme seviyesi; "
                        f"fiyat {fmt_num(r['fiyat'], 2)}, mesafe %{fmt_num(abs(_pct(r['fiyat'], ma50)), 1)}."})
        elif 50 not in r["ma_ust"]:
            out.append({"seviye": "İZLEME", "metin": f"{r['sembol']} 50G ({fmt_num(ma50, 2)}) altında; "
                        f"üstüne dönüş geniş katılım teyidi olur."})
    if prev_rot:
        yeni = [r["sembol"] for r in rot if r["kadran"] == "lider" and prev_rot.get(r["sembol"]) not in (None, "lider")]
        dusen = [r["sembol"] for r in rot if r["kadran"] != "lider" and prev_rot.get(r["sembol"]) == "lider"]
        if yeni:
            out.append({"seviye": "İZLEME", "metin": "Lider kadrana yeni girenler: " + ", ".join(yeni) + "."})
        if dusen:
            out.append({"seviye": "İZLEME", "metin": "Lider kadrodan çıkanlar: " + ", ".join(dusen) + "."})
    for h in portfolio:
        if h.get("ok") and h.get("sma200_uzaklik") is not None and abs(h["sma200_uzaklik"]) < 2:
            out.append({"seviye": "İZLEME", "metin": f"{h['sembol']} 200 günlük ortalamaya çok yakın "
                        f"(%{fmt_num(h['sma200_uzaklik'], 1)}) — portföy adayı için kritik seviye."})
    takvim = []
    if cal["opex_takvim_gunu"] <= 10:
        takvim.append(f"{cal['opex']} {'çeyreklik (üçlü) ' if cal['ceyreklik'] else 'aylık '}opsiyon vadesi")
    if cal.get("fomc_gun") is not None and cal["fomc_gun"] <= 10:
        takvim.append(f"{cal['fomc']} FOMC kararı")
    if takvim:
        out.append({"seviye": "İZLEME", "metin": "Takvim: " + " · ".join(takvim) + "."})
    order = {"YÜKSEK": 0, "ORTA": 1, "İZLEME": 2}
    return sorted(out, key=lambda x: order[x["seviye"]])


# ------------------------------------------------------------------ ana giriş
def analyze_technical(cfg: dict, raw: dict, derived: dict, manuel: dict, today: date,
                      prev_rec: dict | None, portfolio: list[dict]) -> dict:
    if "teknik" not in cfg:
        return {}
    # sektör 50G bilgisi genişliğe eklenir
    br = derived.get("breadth")
    if br:
        for r in br.get("sektorler", []):
            s = _s(raw, r["sembol"])
            r["ust50"] = bool(s is not None and len(s) >= 50 and s.iloc[-1] > s.tail(50).mean())
    idx = index_rows(cfg, raw)
    rot = rotation(cfg, raw)
    ms = momentum_stress(cfg, raw)
    vx = vix_structure(cfg, raw)
    cal = calendar(cfg, manuel, today)
    bil = manuel.get("bilanco")
    h = health(cfg, idx, rot, br, (derived.get("rsp_rel_3m") or {}).get("deger"), ms, vx, bil)
    prev_rot = (prev_rec or {}).get("rotasyon")
    return {"saglik": h, "endeksler": idx, "grafikler": chart_data(cfg, raw), "rotasyon": rot,
            "hacim": volume_panel(cfg, raw), "momentum_stres": ms, "vix": vx, "takvim": cal,
            "bilanco": bil, "izleme": watchlist(idx, rot, ms, cal, prev_rot, portfolio),
            "kayit": {"saglik": h["skor"], "rotasyon": {r["sembol"]: r["kadran"] for r in rot}}}
