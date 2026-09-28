"""Veri çekme katmanı: FRED (anahtarsız CSV) + Yahoo Finance.

Tüm seriler {"kaynak:kod": pandas.Series} biçiminde döner.
"""
from __future__ import annotations

import io
import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (makro-rapor; kisisel kullanim)"}
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"


def _get(url: str, tries: int = 3) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} {url}")
        except requests.RequestException as e:  # ağ hatası
            last = e
        time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def fred(series_id: str, start: str) -> pd.Series:
    r = _get(FRED_CSV.format(id=series_id, start=start))
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.dropna().set_index(pd.to_datetime(df.dropna()["date"]))["value"]
    return s.astype(float)


def _yahoo_raw(symbol: str, rng: str = "2y") -> tuple[pd.Series, pd.Series]:
    r = _get(YAHOO_CHART.format(sym=requests.utils.quote(symbol), rng=rng))
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(ts, unit="s").normalize()
    close = pd.Series(q.get("close") or [None] * len(ts), index=idx, dtype=float)
    vol = pd.Series(q.get("volume") or [None] * len(ts), index=idx, dtype=float)
    close, vol = close[~idx.duplicated(keep="last")], vol[~idx.duplicated(keep="last")]
    return close.dropna(), vol.dropna()


def yahoo_many(symbols: list[str], rng: str = "2y") -> dict[str, pd.Series]:
    """Kapanış ('yahoo:SYM') ve hacim ('yahoo_vol:SYM') serileri.
    Önce yfinance dener, olmazsa doğrudan chart API."""
    out: dict[str, pd.Series] = {}
    try:
        import yfinance as yf  # type: ignore

        data = yf.download(symbols, period=rng, interval="1d", auto_adjust=False,
                           progress=False, group_by="ticker", threads=True)
        for sym in symbols:
            try:
                df = data[sym] if len(symbols) > 1 else data
                for col, key in (("Close", "yahoo"), ("Volume", "yahoo_vol")):
                    s = df[col]
                    if isinstance(s, pd.DataFrame):
                        s = s.iloc[:, 0]
                    s = s.dropna()
                    if len(s):
                        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                        out[f"{key}:{sym}"] = s.astype(float)
            except Exception:
                pass
    except Exception:
        pass
    for sym in symbols:
        if f"yahoo:{sym}" not in out:
            try:
                c, v = _yahoo_raw(sym, rng)
                out[f"yahoo:{sym}"] = c
                if len(v):
                    out[f"yahoo_vol:{sym}"] = v
            except Exception as e:
                print(f"  ! Yahoo {sym} alınamadı: {e}")
    return out


def needed_sources(cfg: dict) -> tuple[set[str], set[str]]:
    fred_ids, yahoo_syms = set(), set()
    for g in cfg["gostergeler"]:
        for src in g["kaynak"].split("|"):
            kind, code = src.split(":", 1)
            (fred_ids if kind == "fred" else yahoo_syms).add(code)
    gen = cfg.get("genislik", {})
    yahoo_syms.update(gen.get("sektor_etfleri", []))
    for k in ("esit_agirlik", "piyasa"):
        if gen.get(k):
            yahoo_syms.add(gen[k])
    port = cfg.get("portfoy", {})
    yahoo_syms.update(h["sembol"] for h in port.get("hisseler", []))
    if port.get("benchmark"):
        yahoo_syms.add(port["benchmark"])
    tek = cfg.get("teknik", {})
    for k in ("trend_endeksleri", "rotasyon_evreni", "hacim_sembolleri", "grafikler"):
        yahoo_syms.update(tek.get(k, []))
    for k in ("momentum_etf", "vix3m"):
        if tek.get(k):
            yahoo_syms.add(tek[k])
    # Net likidite hesabı için
    fred_ids.update({"WALCL", "WTREGEN", "RRPONTSYD"})
    return fred_ids, yahoo_syms


def fetch_all(cfg: dict) -> dict[str, pd.Series]:
    start = (date.today() - timedelta(days=800)).isoformat()
    fred_ids, yahoo_syms = needed_sources(cfg)
    raw: dict[str, pd.Series] = {}
    for sid in sorted(fred_ids):
        try:
            raw[f"fred:{sid}"] = fred(sid, start)
        except Exception as e:
            print(f"  ! FRED {sid} alınamadı: {e}")
    raw.update(yahoo_many(sorted(yahoo_syms)))
    return raw


# ---- Anlık görüntü (snapshot): ham veriyi diske yaz / oku ----
def save_snapshot(raw: dict[str, pd.Series], path: Path) -> None:
    obj = {k: [[d.strftime("%Y-%m-%d"), round(float(v), 6)] for d, v in s.items()] for k, s in raw.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


def load_snapshot(path: Path) -> dict[str, pd.Series]:
    obj = json.loads(path.read_text())
    out = {}
    for k, rows in obj.items():
        if rows:
            out[k] = pd.Series([r[1] for r in rows], index=pd.to_datetime([r[0] for r in rows]), dtype=float)
    return out
