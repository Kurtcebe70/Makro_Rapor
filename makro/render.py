"""HTML üretimi (Jinja2)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analyze import fmt_change, fmt_num, fmt_val

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
             "Eylül", "Ekim", "Kasım", "Aralık"]
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def spark_svg(values: list[float], w: int = 110, h: int = 28, cls: str = "") -> str:
    vals = [v for v in (values or []) if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    step = w / (len(vals) - 1)
    pts = " ".join(f"{i * step:.1f},{h - 2 - (v - lo) / rng * (h - 4):.1f}" for i, v in enumerate(vals))
    return (f'<svg class="spark {cls}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.5" '
            f'vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>')


LINE_COLORS = {"Fiyat": "var(--ink)", "10G": "var(--c1)", "21G": "var(--c2)", "50G": "var(--c3)", "200G": "var(--c4)"}


def line_chart_svg(seriler: dict, w: int = 640, h: int = 200) -> str:
    """Fiyat + hareketli ortalamalar. 200G görünür aralığın çok dışındaysa ölçeği bozmasın diye kırpılır."""
    price = [v for v in seriler["Fiyat"] if v is not None]
    lo, hi = min(price), max(price)
    pad = (hi - lo) * 0.25 or 1
    lo, hi = lo - pad, hi + pad
    for k, vals in seriler.items():
        vv = [v for v in vals if v is not None]
        if k != "Fiyat" and vv and min(vv) >= lo - pad * 2 and max(vv) <= hi + pad * 2:
            lo, hi = min(lo, min(vv)), max(hi, max(vv))
    rng = (hi - lo) or 1
    n = len(price)
    step = (w - 44) / max(n - 1, 1)
    y = lambda v: 8 + (hi - v) / rng * (h - 30)
    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="Fiyat ve hareketli ortalamalar">']
    for frac in (0, 0.5, 1):
        val = hi - frac * rng
        yy = y(val)
        parts.append(f'<line x1="40" x2="{w}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="var(--line)" stroke-dasharray="3 4"/>'
                     f'<text x="0" y="{yy + 4:.1f}" class="ax">{fmt_num(val, 0)}</text>')
    for k in ("200G", "50G", "21G", "10G", "Fiyat"):
        vals = seriler.get(k) or []
        pts = [(40 + i * step, y(v)) for i, v in enumerate(vals) if v is not None and lo <= v <= hi]
        if len(pts) < 2:
            continue
        d = " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
        sw = 2.2 if k == "Fiyat" else 1.4
        parts.append(f'<polyline points="{d}" fill="none" stroke="{LINE_COLORS[k]}" stroke-width="{sw}" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
    last = price[-1]
    parts.append(f'<circle cx="{40 + (n - 1) * step:.1f}" cy="{y(last):.1f}" r="3.5" fill="var(--ink)"/>')
    parts.append("</svg>")
    return "".join(parts)


def bars_svg(bars: list[float], median: float, w: int = 260, h: int = 70) -> str:
    if not bars:
        return ""
    mx = max(max(bars), median) or 1
    bw = w / len(bars)
    out = [f'<svg class="bars" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">']
    for i, b in enumerate(bars):
        bh = b / mx * (h - 6)
        col = "var(--acc)" if i == len(bars) - 1 else "var(--bar)"
        out.append(f'<rect x="{i * bw + 1:.1f}" y="{h - bh:.1f}" width="{bw - 2:.1f}" height="{bh:.1f}" rx="1.5" fill="{col}"/>')
    my = h - median / mx * (h - 6)
    out.append(f'<line x1="0" x2="{w}" y1="{my:.1f}" y2="{my:.1f}" stroke="var(--muted)" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>')
    out.append("</svg>")
    return "".join(out)


def rrg_svg(rows: list[dict], w: int = 420, h: int = 320) -> str:
    """Göreli rotasyon grafiği: x = göreli trend, y = göreli momentum."""
    if not rows:
        return ""
    xm = max(abs(r["trend"]) for r in rows) * 1.2 or 1
    ym = max(abs(r["mom"]) for r in rows) * 1.2 or 1
    cx, cy = w / 2, h / 2
    X = lambda v: cx + v / xm * (w / 2 - 20)
    Y = lambda v: cy - v / ym * (h / 2 - 20)
    col = {"lider": "var(--pos)", "zayif": "var(--warn)", "geride": "var(--neg)", "gucl": "var(--acc)"}
    out = [f'<svg class="rrg" viewBox="0 0 {w} {h}" role="img" aria-label="Rotasyon radarı">',
           f'<rect x="{cx}" y="0" width="{cx}" height="{cy}" fill="var(--pos-bg)"/>',
           f'<rect x="0" y="0" width="{cx}" height="{cy}" fill="var(--acc-bg)"/>',
           f'<rect x="0" y="{cy}" width="{cx}" height="{cy}" fill="var(--neg-bg)"/>',
           f'<rect x="{cx}" y="{cy}" width="{cx}" height="{cy}" fill="var(--warn-bg)"/>',
           f'<line x1="{cx}" x2="{cx}" y1="0" y2="{h}" stroke="var(--line)"/>',
           f'<line x1="0" x2="{w}" y1="{cy}" y2="{cy}" stroke="var(--line)"/>',
           f'<text x="{w - 6}" y="16" text-anchor="end" class="q">LİDER</text>',
           f'<text x="6" y="16" class="q">GÜÇLENEN</text>',
           f'<text x="6" y="{h - 8}" class="q">GERİDE</text>',
           f'<text x="{w - 6}" y="{h - 8}" text-anchor="end" class="q">ZAYIFLAYAN</text>']
    for r in rows:
        x, y = X(r["trend"]), Y(r["mom"])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{col[r["kadran"]]}"/>'
                   f'<text x="{x + 6:.1f}" y="{y + 4:.1f}" class="lbl">{r["sembol"]}</text>')
    out.append("</svg>")
    return "".join(out)


def big_num(x: float | None) -> str:
    if x is None:
        return "—"
    for lim, suf in ((1e12, " Tn"), (1e9, " Mr"), (1e6, " Mn"), (1e3, " B")):
        if abs(x) >= lim:
            return fmt_num(x / lim, 1) + suf
    return fmt_num(x, 0)


def tone(m: dict) -> str:
    """Değişimin piyasa için olumlu/olumsuz rengi."""
    c = m.get("degisim")
    if not c or m.get("iyi") in (None, "none"):
        return "neu"
    good = (c > 0) == (m["iyi"] == "up")
    return "pos" if good else "neg"


def pct_tone(x: float | None) -> str:
    if x is None or x == 0:
        return "neu"
    return "pos" if x > 0 else "neg"


def signed_pct(x: float | None, nd: int = 1) -> str:
    if x is None:
        return "—"
    sign = "+" if x > 0 else ("−" if x < 0 else "")
    return f"{sign}%{fmt_num(abs(x), nd)}"


def tr_date(iso: str) -> str:
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d.year} · {TR_DAYS[d.weekday()]}"


def short_date(iso: str | None) -> str:
    if not iso:
        return "—"
    y, m, d = iso.split("-")
    return f"{int(d)} {TR_MONTHS[int(m) - 1][:3]}"


def render(ctx: dict, template_dir: Path) -> str:
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    env.filters.update(num=fmt_num, val=fmt_val, chg=fmt_change, tone=tone, pct_tone=pct_tone,
                       spct=signed_pct, trdate=tr_date, sdate=short_date)
    env.globals.update(spark=spark_svg, line_chart=line_chart_svg, bars=bars_svg, rrg=rrg_svg,
)
    env.filters["big"] = big_num
    return env.get_template(ctx.pop("_sablon", "rapor.html.j2")).render(**ctx)


def render_index(entries: list[dict], template_dir: Path) -> str:
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    env.filters.update(trdate=tr_date)
    return env.get_template("arsiv.html.j2").render(entries=entries)
