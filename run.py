#!/usr/bin/env python3
"""Günlük makro raporu üretir.

Kullanım:
  python run.py                      # veriyi çek, raporu üret (docs/ klasörüne)
  python run.py --snapshot veri.json # ağ yerine kayıtlı ham veriyle çalış (test)
  python run.py --save-raw           # çekilen ham veriyi data/raw_latest.json'a da kaydet
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from makro.analyze import analyze
from makro.fetch import fetch_all, load_snapshot, save_snapshot
from makro.narrative import narrative
from makro.render import render, render_index
from makro.technical import analyze_technical

ROOT = Path(__file__).parent
DOCS, DATA, TPL = ROOT / "docs", ROOT / "data", ROOT / "templates"


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_panels(cfg: dict, a: dict) -> list[dict]:
    order: list[str] = []
    for g in cfg["gostergeler"]:
        if g["panel"] not in order:
            order.append(g["panel"])
    d = a["derived"]
    extra = {
        "Piyasa": [d[k] for k in ("spx_vs_200", "breadth", "rsp_rel_3m") if k in d],
        "Likidite": [d[k] for k in ("net_liq", "net_liq_4w") if k in d],
    }
    panels = []
    for name in order:
        panels.append({
            "ad": name,
            "satirlar": [a["metrics"][g["anahtar"]] for g in cfg["gostergeler"] if g["panel"] == name],
            "turetilmis": extra.get(name, []),
            "sektorler": d.get("breadth", {}).get("sektorler") if name == "Piyasa" else None,
        })
    return panels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path)
    ap.add_argument("--save-raw", action="store_true")
    ap.add_argument("--date", help="Rapor tarihi (YYYY-MM-DD), varsayılan bugün")
    args = ap.parse_args()

    cfg = load_yaml(ROOT / "config.yaml")
    manuel = load_yaml(ROOT / "manuel.yaml")
    tz = ZoneInfo(cfg["rapor"].get("saat_dilimi", "Europe/Istanbul"))
    now = datetime.now(tz)
    today = date.fromisoformat(args.date) if args.date else now.date()

    print("1/4 Veri çekiliyor…")
    raw = load_snapshot(args.snapshot) if args.snapshot else fetch_all(cfg)
    print(f"    {len(raw)} seri alındı")
    if args.save_raw:
        save_snapshot(raw, DATA / "raw_latest.json")

    hist_path = DATA / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    prev_dates = sorted(k for k in history if k < today.isoformat())
    prev_date = prev_dates[-1] if prev_dates else None

    print("2/4 Analiz…")
    a = analyze(cfg, raw, today, history.get(prev_date) if prev_date else None)
    a["manuel"] = manuel
    a["teknik"] = analyze_technical(cfg, raw, a["derived"], manuel, today,
                                    history.get(prev_date) if prev_date else None, a["portfolio"]["hisseler"])
    a["kayit"].update(a["teknik"].get("kayit", {}))

    print("3/4 Yorum…")
    yorum = narrative(a, cfg)

    print("4/4 HTML…")
    manuel_bayat = False
    if manuel.get("guncelleme"):
        manuel_bayat = (today - date.fromisoformat(str(manuel["guncelleme"]))).days > 7
    hizli = [a["metrics"][g["anahtar"]] for g in cfg["gostergeler"] if g.get("hizli")]
    html = render({"cfg": cfg, "a": a, "tarih": today.isoformat(), "uretim": now.strftime("%H:%M"),
                   "yorum": yorum, "hizli": hizli, "t": a.get("teknik") or None, "paneller": build_panels(cfg, a),
                   "manuel": manuel, "manuel_bayat": manuel_bayat, "onceki_tarih": prev_date}, TPL)

    (DOCS / "arsiv").mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(html.replace('href="arsiv/index.html"', 'href="arsiv/index.html"'), encoding="utf-8")
    (DOCS / "arsiv" / f"{today.isoformat()}.html").write_text(
        html.replace('href="arsiv/index.html"', 'href="index.html"'), encoding="utf-8")

    history[today.isoformat()] = a["kayit"]
    DATA.mkdir(exist_ok=True)
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=0))
    (DATA / "son_analiz.json").write_text(json.dumps({"analiz": a, "yorum": yorum}, ensure_ascii=False, default=str, indent=1))

    entries = [{"tarih": k, **v} for k, v in sorted(history.items(), reverse=True)]
    (DOCS / "arsiv" / "index.html").write_text(render_index(entries, TPL), encoding="utf-8")
    tek = a["teknik"].get("saglik", {})
    print(f"Tamam → docs/index.html  (makro rejim {a['regime']['skor']}/100 · teknik sağlık {tek.get('skor', '—')}/100)")


if __name__ == "__main__":
    main()
