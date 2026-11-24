"""FreshLens dashboard (day / night themes).

    uv run --extra dashboard streamlit run dashboard/app.py

Reads the gold Delta tables directly with delta-rs (no Spark needed). Every number on the page
comes from the marts at render time; nothing is hard-coded.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yaml

ROOT = Path(os.environ.get("FPR_DATA_ROOT", Path(__file__).resolve().parents[1] / "data"))
GOLD = ROOT / "lake" / "gold"
SNAPSHOT = Path(__file__).resolve().parent / "snapshot"  # hosted app: slim parquet from `freshlens export`
HUB = "Azadpur"

st.set_page_config(page_title="FreshLens", page_icon="🥬", layout="wide", initial_sidebar_state="collapsed")

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Design tokens. Categorical slots are assigned in fixed order and follow the entity, not its rank.
# Dark mode is its own selected set of steps, not an automatic inversion.
# ════════════════════════════════════════════════════════════════════════════════════════════════
THEMES = {
    "day": {
        "page": "#f6f5f1",
        "surface": "#fcfcfb",
        "surface2": "#f1f0ec",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "border": "rgba(11,11,11,0.10)",
        "accent": "#2a78d6",
        "accent_soft": "rgba(42,120,214,0.10)",
        "up": "#b42318",  # price up = bad for a buyer
        "down": "#006300",  # price down = good for a buyer
        "good": "#0ca30c",
        "critical": "#d03b3b",
        "warning": "#b07800",
        "div_neg": "#e34948",
        "div_mid": "#f0efec",
        "div_pos": "#2a78d6",
        "shadow": "0 1px 2px rgba(11,11,11,0.04), 0 4px 16px rgba(11,11,11,0.04)",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    },
    "night": {
        "page": "#0d0d0d",
        "surface": "#1a1a19",
        "surface2": "#232322",
        "ink": "#f0efec",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "border": "rgba(255,255,255,0.10)",
        "accent": "#3987e5",
        "accent_soft": "rgba(57,135,229,0.16)",
        "up": "#e66767",
        "down": "#0ca30c",
        "good": "#0ca30c",
        "critical": "#e66767",
        "warning": "#fab219",
        "div_neg": "#e66767",
        "div_mid": "#383835",
        "div_pos": "#3987e5",
        "shadow": "0 1px 2px rgba(0,0,0,0.4), 0 6px 20px rgba(0,0,0,0.25)",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"],
    },
}
_CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "settings.yaml").read_text())
DISPLAY = {c: (_CFG.get("display_names") or {}).get(c, c) for c in _CFG["commodities"]}
CATEGORY = {DISPLAY[c]: cat for c, cat in _CFG["commodities"].items()}
COMMODITY_ORDER = list(DISPLAY.values())
CITIES = list(
    (_CFG.get("cities") or {"Delhi NCR": ["Azadpur"]}).keys()
)  # config order; display names (e.g. "Cucumbar(Kheera)" → "Cucumber")
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

# ── theme state: ?theme=night survives a refresh and makes links shareable ─────────────────────
if "night" not in st.session_state:
    st.session_state.night = st.query_params.get("theme", "day") == "night"


def T() -> dict:
    return THEMES["night" if st.session_state.night else "day"]


def inject_css(t: dict) -> None:
    night = st.session_state.night
    sheen = "rgba(255,255,255,0.07)" if night else "rgba(255,255,255,0.75)"  # shimmer highlight
    veil = "rgba(26,26,25,0.55)" if night else "rgba(255,255,255,0.5)"  # fades stale content under it
    st.markdown(
        f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {{ color-scheme: {"dark" if st.session_state.night else "light"}; }}
html, body, .stApp, [data-testid="stAppViewContainer"] {{ background: {t["page"]} !important; }}
.stApp, .stApp p, .stApp span, .stApp label, .stApp div {{ font-family: {FONT}; }}
.stApp, .stMarkdown, .stMarkdown p, label, [data-testid="stWidgetLabel"] p {{ color: {t["ink"]}; }}
[data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer, [data-testid="stDecoration"],
[data-testid="stStatusWidget"] {{ display: none !important; }}
[data-testid="stMainBlockContainer"], .block-container {{ padding: 1.4rem 2.2rem 3rem; max-width: 1360px; }}
@media (max-width: 640px) {{ [data-testid="stMainBlockContainer"], .block-container {{ padding: 1rem 16px 2rem; }} }}

/* ── cards (st.container(key="card-…")) ── */
[class*="st-key-card"] {{
  background: {t["surface"]}; border: 1px solid {t["border"]}; border-radius: 14px;
  padding: 18px 20px 14px; box-shadow: {t["shadow"]};
}}
.fpr-h {{ font-size: 15px; font-weight: 600; color: {t["ink"]}; margin: 0 0 2px; letter-spacing: -0.01em; }}
.fpr-sub {{ font-size: 12.5px; color: {t["muted"]}; margin: 0 0 10px; }}

/* ── header ── */
.fpr-brand {{ display: flex; align-items: center; gap: 12px; }}
.fpr-logo {{ width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center;
  background: linear-gradient(135deg, {t["series"][2]}, {t["series"][0]}); color: #fff; font-size: 19px; }}
.fpr-title {{ font-size: 22px; font-weight: 700; letter-spacing: -0.02em; color: {t["ink"]}; line-height: 1.1; }}
.fpr-tag {{ font-size: 13px; color: {t["ink2"]}; margin-top: 2px; }}
.fpr-chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
.fpr-chip {{ font-size: 12px; color: {t["ink2"]}; background: {t["surface2"]}; border: 1px solid {t["border"]};
  padding: 3px 10px; border-radius: 999px; white-space: nowrap; }}
.fpr-chip b {{ color: {t["ink"]}; font-weight: 600; }}
.fpr-dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px;
  vertical-align: 1px; }}

/* ── stat tiles ── */
.fpr-tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }}
.fpr-tile {{ background: {t["surface"]}; border: 1px solid {t["border"]}; border-radius: 14px;
  padding: 16px 18px; box-shadow: {t["shadow"]}; }}
.fpr-tile-label {{ font-size: 12.5px; color: {t["ink2"]}; display: flex; align-items: center; gap: 6px; }}
.fpr-tile-value {{ font-size: 28px; font-weight: 650; letter-spacing: -0.02em; color: {t["ink"]};
  margin-top: 6px; font-variant-numeric: tabular-nums; }}
.fpr-tile-value small {{ font-size: 14px; font-weight: 500; color: {t["muted"]}; margin-left: 4px; }}
.fpr-tile-foot {{ font-size: 12px; color: {t["muted"]}; margin-top: 4px; }}
.fpr-up {{ color: {t["up"]}; font-weight: 600; }}
.fpr-down {{ color: {t["down"]}; font-weight: 600; }}

/* ── insight list ── */
.fpr-insight {{ display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid {t["grid"]}; }}
.fpr-insight:first-child {{ border-top: none; padding-top: 2px; }}
.fpr-insight .n {{ flex: 0 0 26px; height: 26px; border-radius: 8px; background: {t["accent_soft"]};
  color: {t["accent"]}; font-weight: 700; font-size: 13px; display: grid; place-items: center; }}
.fpr-insight p {{ margin: 0; font-size: 14px; line-height: 1.5; color: {t["ink2"]}; }}
.fpr-insight b {{ color: {t["ink"]}; }}

/* ── tables ── */
.fpr-table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
.fpr-table th {{ text-align: left; font-weight: 500; color: {t["muted"]}; font-size: 12px; padding: 8px 10px;
  border-bottom: 1px solid {t["axis"]}; white-space: nowrap; }}
.fpr-table td {{ padding: 9px 10px; border-bottom: 1px solid {t["grid"]}; color: {t["ink"]}; }}
.fpr-table td.num, .fpr-table th.num {{ text-align: right; }}
.fpr-table tr:last-child td {{ border-bottom: none; }}
.fpr-scroll {{ overflow-x: auto; }}
.fpr-status {{ white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; font-weight: 600; font-size: 12.5px; }}
.fpr-pass {{ color: {t["good"]}; }} .fpr-fail {{ color: {t["critical"]}; }} .fpr-warn {{ color: {t["warning"]}; }}
.fpr-badge {{ font-size: 11px; color: {t["ink2"]}; background: {t["surface2"]}; border: 1px solid {t["border"]};
  padding: 1px 8px; border-radius: 999px; }}

/* ── alert cards ── */
.fpr-alerts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }}
.fpr-alert {{ border: 1px solid {t["border"]}; border-radius: 12px; padding: 12px 14px; background: {t["surface2"]}; }}
.fpr-alert.on {{ border-color: {t["critical"]}; }}
.fpr-alert .lane {{ font-size: 13px; font-weight: 600; color: {t["ink"]}; }}
.fpr-alert .chg {{ font-size: 22px; font-weight: 650; margin: 4px 0 2px; font-variant-numeric: tabular-nums; }}
.fpr-alert .msg {{ font-size: 12.5px; color: {t["ink2"]}; line-height: 1.45; }}

/* ── vertical nav (st.radio styled as a menu) ── */
.st-key-navcard {{ background: {t["surface"]}; border: 1px solid {t["border"]}; border-radius: 14px;
  padding: 10px 8px; box-shadow: {t["shadow"]}; position: sticky; top: 16px; }}
.fpr-navlabel {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: {t["muted"]}; padding: 4px 12px 6px; }}
.st-key-page, .st-key-page [data-testid="stRadio"] {{ width: 100% !important; }}
[data-testid="stRadioGroup"] {{ gap: 2px !important; width: 100%; }}
[data-testid="stRadioGroup"] > div, [data-testid="stRadioGroup"] label {{ width: 100% !important; }}
@media (max-width: 640px) {{
  .st-key-navcard {{ position: static; padding: 6px; }}
  .fpr-navlabel {{ display: none; }}
  [data-testid="stRadioGroup"] {{ flex-direction: row !important; flex-wrap: nowrap !important; overflow-x: auto; }}
  [data-testid="stRadioGroup"] > div, [data-testid="stRadioGroup"] label {{ width: auto !important; }}
}}
[data-testid="stRadioGroup"] > div {{ width: 100%; }}
[data-testid="stRadioOption"] {{ width: 100%; padding: 9px 12px !important; border-radius: 10px; cursor: pointer;
  margin: 0 !important; transition: background .12s ease; }}
[data-testid="stRadioOption"] > div > div:first-child {{ display: none !important; }}
[data-testid="stRadioOption"] p {{ display: flex; align-items: center; gap: 10px; margin: 0;
  font-size: 14px !important; font-weight: 500; color: {t["ink2"]} !important; white-space: nowrap; }}
[data-testid="stRadioOption"] p span[role="img"] {{ font-size: 19px; color: {t["muted"]}; }}
[data-testid="stRadioOption"]:hover {{ background: {t["surface2"]}; }}
[data-testid="stRadioOption"][data-selected="true"] {{ background: {t["accent_soft"]}; }}
[data-testid="stRadioOption"][data-selected="true"] p,
[data-testid="stRadioOption"][data-selected="true"] p span[role="img"] {{ color: {t["accent"]} !important; font-weight: 600; }}

/* ── inputs ── */
[data-baseweb="select"] > div {{ background: {t["surface"]} !important; border-color: {t["border"]} !important;
  border-radius: 10px !important; color: {t["ink"]} !important; }}
[data-baseweb="select"] * {{ color: {t["ink"]}; }}
[data-baseweb="select"] svg {{ fill: {t["muted"]}; }}
[data-baseweb="popover"] ul, [data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] {{
  background: {t["surface"]} !important; border: 1px solid {t["border"]}; }}
[data-baseweb="popover"] li {{ color: {t["ink"]} !important; background: transparent; }}
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] {{ background: {t["accent_soft"]} !important; }}
[data-baseweb="tag"] {{ background: {t["accent_soft"]} !important; border-radius: 8px !important; }}
[data-baseweb="tag"] span {{ color: {t["accent"]} !important; }}
/* react-aria selects (Streamlit ≥1.60) */
.react-aria-ComboBox > [role="group"] {{ background: {t["surface"]} !important; border: 1px solid {t["border"]} !important;
  border-radius: 10px !important; }}
.react-aria-ComboBox input {{ color: {t["ink"]} !important; background: transparent !important; }}
.react-aria-ComboBox button, .react-aria-ComboBox svg {{ color: {t["muted"]} !important; }}
[data-tag] {{ background: {t["accent_soft"]} !important; border-radius: 8px !important; border: none !important; }}
[data-tag] span, [data-tag] button {{ color: {t["accent"]} !important; }}
.react-aria-Popover, [role="listbox"] {{ background: {t["surface"]} !important; border: 1px solid {t["border"]} !important;
  border-radius: 10px !important; box-shadow: {t["shadow"]} !important; }}
[role="option"] {{ color: {t["ink"]} !important; background: transparent !important; }}
[role="option"][data-focused], [role="option"][data-hovered], [role="option"][aria-selected="true"] {{
  background: {t["accent_soft"]} !important; }}
[data-testid="stButtonGroup"] button {{ background: {t["surface"]}; color: {t["ink2"]}; border-color: {t["border"]}; }}
[data-testid="stButtonGroup"] button[kind*="Active"], [data-testid="stButtonGroup"] button[aria-checked="true"] {{
  background: {t["accent_soft"]}; color: {t["accent"]}; border-color: {t["accent"]}; }}
[data-testid="stButtonGroup"] button p {{ color: inherit; }}
[data-testid="stToggle"] label p, .st-key-night label p {{ color: {t["ink2"]} !important; font-size: 13px; }}

/* ── chart tooltips ── */
#vg-tooltip-element {{ background: {t["surface"]} !important; color: {t["ink"]} !important;
  border: 1px solid {t["border"]} !important; border-radius: 10px !important; box-shadow: {t["shadow"]} !important;
  font-family: {FONT} !important; font-size: 12px !important; padding: 8px 10px !important; }}
#vg-tooltip-element td.key {{ color: {t["muted"]} !important; }}
#vg-tooltip-element td.value {{ color: {t["ink"]} !important; font-variant-numeric: tabular-nums; }}
.vega-embed summary {{ display: none !important; }}

/* ── loading shimmer ──
   First visit: a skeleton of the page while the tables load.
   Reruns (switching page / city / item): Streamlit marks old elements data-stale; instead of
   dimming them, sweep a shimmer over the cards. Delayed 250 ms so fast reruns never flicker. */
@keyframes fpr-sweep {{ from {{ background-position: 150% 0; }} to {{ background-position: -50% 0; }} }}
@keyframes fpr-in {{ to {{ opacity: 1; }} }}
.fpr-skel {{ border-radius: 7px; background-color: {t["surface2"]};
  background-image: linear-gradient(100deg, transparent 30%, {sheen} 50%, transparent 70%);
  background-size: 200% 100%; animation: fpr-sweep 1.3s linear infinite; }}
.fpr-boot {{ display: grid; grid-template-columns: 1fr 5.2fr; gap: 16px; margin-top: 18px; }}
.fpr-boot-col {{ display: flex; flex-direction: column; gap: 14px; }}
.fpr-boot .fpr-tile {{ display: flex; flex-direction: column; gap: 10px; }}
@media (max-width: 640px) {{ .fpr-boot {{ grid-template-columns: 1fr; }} }}
.fpr-later {{ opacity: 0; animation: fpr-in .2s .25s forwards; }}
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}
[class*="st-key-card"], .fpr-tile, .fpr-alert {{ position: relative; }}
[class*="st-key-card"]:has([data-stale="true"])::after,
[data-stale="true"] .fpr-tile::after, [data-stale="true"] .fpr-alert::after {{
  content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; z-index: 5;
  background-color: {veil};
  background-image: linear-gradient(100deg, transparent 30%, {sheen} 50%, transparent 70%);
  background-size: 200% 100%; opacity: 0;
  animation: fpr-in .2s .25s forwards, fpr-sweep 1.3s linear infinite; }}
</style>""",
        unsafe_allow_html=True,
    )


def style(chart: alt.Chart, height: int = 300) -> alt.Chart:
    """Recessive axes and grid; text in ink tokens, never series colors."""
    t = T()
    return (
        chart.properties(height=height, background="transparent")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=t["muted"],
            titleColor=t["ink2"],
            gridColor=t["grid"],
            domainColor=t["axis"],
            tickColor=t["axis"],
            labelFont=FONT,
            titleFont=FONT,
            labelFontSize=11,
            titleFontSize=11,
            titleFontWeight=500,
            labelPadding=6,
            gridDash=[2, 3],
        )
        .configure_axisX(grid=False)
        .configure_legend(
            labelColor=t["ink2"],
            titleColor=t["muted"],
            labelFont=FONT,
            titleFont=FONT,
            labelFontSize=12,
            orient="top",
            direction="horizontal",
            symbolType="stroke",
            symbolStrokeWidth=3,
            title=None,
        )
        .configure_header(labelColor=t["ink2"], labelFont=FONT, titleColor=t["ink2"])
        .configure_text(font=FONT)
    )


def show(chart: alt.Chart, height: int = 300) -> None:
    st.altair_chart(style(chart, height), theme=None, width="stretch")


def line_chart(df: pd.DataFrame, series: str, value: str, domain: list[str], y_title: str, fmt: str = ",.1f"):
    """Lines + a hover crosshair whose tooltip lists every series at that date."""
    t = T()
    colors = [t["series"][i % 8] for i in range(len(domain))]
    color = alt.Color(f"{series}:N", scale=alt.Scale(domain=domain, range=colors), sort=domain)
    base = alt.Chart(df).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0)))
    lines = base.mark_line(strokeWidth=2, interpolate="monotone").encode(
        y=alt.Y(f"{value}:Q", title=y_title, axis=alt.Axis(format=",.0f")), color=color
    )
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["date"], empty=False, clear="pointerout")
    present = [d for d in domain if d in set(df[series])]
    rule = (
        base.transform_pivot(series, value=value, groupby=["date"])
        .mark_rule(color=t["axis"], strokeWidth=1)
        .encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[alt.Tooltip("date:T", title="Date", format="%d %b %Y")]
            + [alt.Tooltip(f"{d}:Q", title=d, format=fmt) for d in present],
        )
        .add_params(hover)
    )
    points = lines.mark_point(filled=True, size=46, stroke=t["surface"], strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0))
    )
    return alt.layer(lines, points, rule)


def card_head(title: str, sub: str = "") -> None:
    st.html(f'<div class="fpr-h">{html.escape(title)}</div>' + (f'<div class="fpr-sub">{sub}</div>' if sub else ""))


def rs(x: float) -> str:
    return f"−₹{abs(x):,.1f}" if x < 0 else f"₹{x:,.1f}"


def pct_delta(now: float, then: float | None) -> str:
    if then is None or pd.isna(then) or then == 0:
        return '<span class="fpr-badge">no comparison</span>'
    d = (now / then - 1) * 100
    cls, arrow = ("fpr-up", "▲") if d > 0 else ("fpr-down", "▼")
    return f'<span class="{cls}">{arrow} {abs(d):.1f}%</span> vs 4 weeks earlier'


def skeleton(content_only: bool = False) -> str:
    """Page-shaped placeholder: menu + stat tiles + chart card (content_only: just the right side)."""

    def bar(w: str, h: int) -> str:
        return f'<div class="fpr-skel" style="width:{w};height:{h}px"></div>'

    nav = "".join(bar(w, 14) for w in ("40%", "90%", "35%", "80%", "75%", "85%", "70%", "80%"))
    tile = f'<div class="fpr-tile">{bar("55%", 12)}{bar("65%", 28)}{bar("85%", 10)}</div>'
    chart = f'<div class="fpr-tile">{bar("30%", 15)}{bar("45%", 11)}{bar("100%", 300)}</div>'
    main = f'<div class="fpr-boot-col"><div class="fpr-tiles">{tile * 4}</div>{chart}</div>'
    if content_only:
        return f'<div class="fpr-boot fpr-later" style="display:block;margin-top:0">{main}</div>'
    return f'<div class="fpr-boot"><div class="fpr-tile" style="gap:18px">{nav}</div>{main}</div>'


# ════════════════════════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600)
def load(name: str) -> pd.DataFrame:
    """A gold table: the local Delta lake when present (dev), else the exported snapshot (hosted)."""
    delta, snap = GOLD / name, SNAPSHOT / f"{name}.parquet"
    if (delta / "_delta_log").exists():
        from deltalake import DeltaTable  # local only; the hosted app never needs delta-rs

        df = DeltaTable(str(delta)).to_pyarrow_table().to_pandas()
    elif snap.exists():
        df = pd.read_parquet(snap)
    else:
        return pd.DataFrame()
    for c in ("date", "week_of"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    if "commodity" in df.columns:
        df["commodity"] = df["commodity"].map(lambda c: DISPLAY.get(c, c))
    if "checked_at" in df.columns:  # stored as UTC
        ts = pd.to_datetime(df["checked_at"])
        ts = ts.dt.tz_localize("UTC") if ts.dt.tz is None else ts
        df["checked_at"] = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return df


# ── header ────────────────────────────────────────────────────────────────────────────────────────
head_l, head_r = st.columns([5, 1.2], vertical_alignment="center")
with head_r:
    st.toggle("🌙  Night mode", key="night")
st.query_params["theme"] = "night" if st.session_state.night else "day"
t = T()
inject_css(t)

boot = st.empty()  # first visit only: a shimmering skeleton until the tables are in memory
if not st.session_state.get("booted"):
    boot.html(skeleton())
daily = load("mart_mandi_daily")
cityd = load("mart_city_daily")  # one price per city × item × day (median of the city's markets)
cityv = load("mart_city_volatility")
vol = load("mart_volatility")
spread = load("mart_sourcing_spread")
llw = load("mart_lead_lag_weekly")
lld = load("mart_lead_lag")
bt = load("mart_alert_backtest")
alerts = load("mart_alerts")
boot.empty()
st.session_state.booted = True

if daily.empty:
    st.warning(f"No gold tables under {GOLD}. Run `uv run fpr backfill` first.")
    st.stop()

hist = daily[daily["date"] < "2026-01-01"]
live = daily[daily["date"] >= "2026-01-01"]
with head_l:
    st.html(
        f"""
<div class="fpr-brand"><div class="fpr-logo">🥬</div><div>
  <div class="fpr-title">FreshLens</div>
  <div class="fpr-tag">Wholesale market prices → sourcing signals for quick-commerce dark stores across India</div></div></div>
<div class="fpr-chips">
  <span class="fpr-chip"><span class="fpr-dot" style="background:{t["good"]}"></span>
    Live feed <b>{live["date"].max():%d %b %Y}</b></span>
  <span class="fpr-chip">History <b>{hist["date"].min():%Y}–{hist["date"].max():%Y}</b></span>
  <span class="fpr-chip"><b>{len(CITIES)}</b> cities · <b>{daily["market"].nunique():,}</b> markets · <b>{len(daily):,}</b> market-days</span>
  <span class="fpr-chip">Prices in <b>₹/kg</b> (modal, median across varieties)</span>
</div>"""
    )

PAGES = {
    "Overview": ":material/space_dashboard:",
    "India": ":material/public:",
    "Prices": ":material/show_chart:",
    "Volatility": ":material/ssid_chart:",
    "Sourcing": ":material/local_shipping:",
    "Signals": ":material/notifications_active:",
}
if "page" not in st.session_state:
    st.session_state.page = st.query_params.get("page", "Overview")
    if st.session_state.page not in PAGES:
        st.session_state.page = "Overview"
if "city" not in st.session_state:
    st.session_state.city = st.query_params.get("city", CITIES[0])
    if st.session_state.city not in CITIES:
        st.session_state.city = CITIES[0]
nav, content = st.columns([1, 5.2], gap="medium")
with nav, st.container(key="navcard"):
    st.html('<div class="fpr-navlabel">City</div>')
    CITY = st.selectbox("City", CITIES, key="city", label_visibility="collapsed")
    st.html('<div class="fpr-navlabel" style="margin-top:10px">Menu</div>')
    PAGE = st.radio(
        "Navigate",
        list(PAGES),
        key="page",
        label_visibility="collapsed",
        format_func=lambda name: f"{PAGES[name]}  {name}",
    )
st.query_params["page"] = PAGE
st.query_params["city"] = CITY
pending = content.empty()  # new page: a skeleton holds its place until the page is built
if st.session_state.get("shown_page") != PAGE:
    pending.html(skeleton(content_only=True))

ALL_LANES = list(dict.fromkeys(spread["lane"])) if not spread.empty else []
ALL_LANES = sorted(
    ALL_LANES,
    key=lambda x: (
        CITIES.index(x.split("→")[-1].strip()) if x.split("→")[-1].strip() in CITIES else 99,
        COMMODITY_ORDER.index(x.split(":")[0]) if x.split(":")[0] in COMMODITY_ORDER else 99,
        x,
    ),
)
LANES = [ln for ln in ALL_LANES if ln.split("→")[-1].strip() == CITY]  # lanes into the selected city
LANE_CITIES = sorted({ln.split("→")[-1].strip() for ln in ALL_LANES}, key=CITIES.index)
hubd = cityd[cityd["city"] == CITY]  # the selected city's price series
HUB = CITY  # used in titles


def no_lanes() -> None:
    with st.container(key="card-nolanes"):
        card_head(
            f"No sourcing lanes into {CITY} yet",
            "Lanes compare a city's price with a source market's price plus freight. Configured for: "
            + ", ".join(LANE_CITIES)
            + ". Add one in config/settings.yaml → lanes.",
        )


def hub_latest(commodity: str) -> tuple[float, float | None, pd.Timestamp] | None:
    s = hubd[hubd["commodity"] == commodity].sort_values("date")
    if s.empty:
        return None
    last = s.iloc[-1]
    prior = s[s["date"] <= last["date"] - pd.Timedelta(days=28)]
    return last["modal_price_kg"], (prior.iloc[-1]["modal_price_kg"] if len(prior) else None), last["date"]


# ════════════════════════════════════════════════════════════════════════════════════════════════
# Overview
# ════════════════════════════════════════════════════════════════════════════════════════════════
if PAGE == "Overview" and hubd.empty:
    with content, st.container(key="card-nodata"):
        card_head(
            f"No price history for {CITY} yet",
            "Its markets are configured; data appears after the next backfill or nightly run.",
        )
elif PAGE == "Overview":
    with content:
        TOP3 = ["Tomato", "Onion", "Potato"]

        # ── row 1: today's prices + best warning lane ──────────────────────────────────────────
        tiles = []
        for i, c in enumerate(TOP3):
            got = hub_latest(c)
            if got:
                now, then, d = got
                tiles.append(
                    f'<div class="fpr-tile"><div class="fpr-tile-label"><span class="fpr-dot" '
                    f'style="background:{t["series"][i]}"></span>{c} · {HUB}</div>'
                    f'<div class="fpr-tile-value">{rs(now)}<small>/kg</small></div>'
                    f'<div class="fpr-tile-foot">{pct_delta(now, then)} · {d:%d %b %Y}</div></div>'
                )
        if not bt.empty:
            cb = bt[bt["lane"].isin(LANES)]  # this city's lanes, else the best in India
            where = "" if not cb.empty else " · India"
            cb = cb if not cb.empty else bt
            b = cb.assign(edge=cb["hit_rate_pct"] - cb["base_rate_up_pct"]).sort_values("edge", ascending=False).iloc[0]
            tiles.append(
                f'<div class="fpr-tile"><div class="fpr-tile-label">Best early-warning lane{where}</div>'
                f'<div class="fpr-tile-value">+{b["edge"]:.1f}<small>pp</small></div>'
                f'<div class="fpr-tile-foot">{html.escape(b["lane"])}: {b["hit_rate_pct"]:.0f}% vs '
                f"{b['base_rate_up_pct']:.0f}% base</div></div>"
            )
        st.html(f'<div class="fpr-tiles">{"".join(tiles)}</div>')
        st.html('<div style="height:14px"></div>')

        # ── row 2: headline stats ───────────────────────────────────────────────────────────────
        stats = []
        if not vol.empty:
            v = (
                cityv[(cityv["city"] == CITY) & cityv["log_return"].notna()].groupby("commodity")["log_return"].std()
                * 100
            )
            v = v.sort_values(ascending=False)
        if not vol.empty and len(v):
            stats.append(
                (
                    "Most volatile item",
                    f"{v.iloc[0]:.1f}<small>% / day</small>",
                    f"{v.index[0]} · least volatile: {v.index[-1]} ({v.iloc[-1]:.1f}%)",
                )
            )
        wk3 = pd.DataFrame(columns=["date", "commodity", "modal_price_kg"])
        h3 = hubd[(hubd["commodity"].isin(TOP3)) & (hubd["date"] >= hubd["date"].max() - pd.Timedelta(days=3 * 365))]
        if not h3.empty:
            wk3 = (
                h3.assign(date=h3["date"].dt.to_period("W").dt.start_time)
                .groupby(["commodity", "date"], as_index=False)["modal_price_kg"]
                .median()
            )
            peak = wk3.loc[wk3["modal_price_kg"].idxmax()]
            typical = wk3[wk3["commodity"] == peak["commodity"]]["modal_price_kg"].median()
            stats.append(
                (
                    "Biggest spike, last 3 years",
                    f"{rs(peak['modal_price_kg'])}<small>/kg</small>",
                    f"{peak['commodity']} · {peak['date']:%b %Y} · {peak['modal_price_kg'] / typical:.1f}× its usual price",
                )
            )
        if not spread.empty:
            sp_ = spread[spread["lane"].isin(LANES)]
            in_city = not sp_.empty
            sp_ = sp_ if in_city else spread
            sh = sp_.groupby("lane")["direct_sourcing_cheaper"].mean().sort_values(ascending=False) * 100
            stats.append(
                (
                    "Best lane to buy direct" + ("" if in_city else " · India"),
                    f"{sh.iloc[0]:.0f}%<small>of days</small>",
                    f"{html.escape(sh.index[0])} · worst: {html.escape(sh.index[-1].split(':')[0])} "
                    f"{html.escape(sh.index[-1].split(':')[1].split('→')[0].strip())} ({sh.iloc[-1]:.0f}%)",
                )
            )
        stats.append(
            (
                f"Prices analysed · {CITY}",
                f"{len(hubd):,}<small>item-days</small>",
                f"{daily.loc[daily['city'] == CITY, 'market'].nunique()} markets · "
                f"{hubd['date'].min():%Y}–{hubd['date'].max():%Y}",
            )
        )
        st.html(
            '<div class="fpr-tiles">'
            + "".join(
                f'<div class="fpr-tile"><div class="fpr-tile-label">{a}</div><div class="fpr-tile-value">{b_}</div>'
                f'<div class="fpr-tile-foot">{c_}</div></div>'
                for a, b_, c_ in stats
            )
            + "</div>"
        )
        st.html('<div style="height:14px"></div>')

        # ── row 3: 3-year trend + "is it expensive right now?" ─────────────────────────────────
        left, right = st.columns([1.6, 1], gap="medium")
        with left, st.container(key="card-ov-trend"):
            card_head(f"{HUB} prices, last 3 years", "Weekly median price · hover for values")
            if wk3.empty:
                st.info(f"No tomato, onion or potato history for {CITY} in the last 3 years.")
            else:
                show(line_chart(wk3, "commodity", "modal_price_kg", TOP3, "₹/kg"), 290)

        with right, st.container(key="card-ov-now"):
            last_month = hubd["date"].max()
            card_head(
                "Is it expensive right now?",
                f"The 10 items furthest from their usual {last_month:%B} price (previous 5 years)",
            )
            rows = []
            for c in [x for x in COMMODITY_ORDER if x in set(hubd["commodity"])]:
                s_ = hubd[hubd["commodity"] == c].sort_values("date")
                cur = s_.iloc[-1]
                m = cur["date"].month
                past = s_[
                    (s_["date"].dt.month == m)
                    & (s_["date"].dt.year < cur["date"].year)
                    & (s_["date"].dt.year >= cur["date"].year - 5)
                ]
                if past["date"].dt.year.nunique() < 3:  # need ≥3 past years for a fair range
                    continue
                by_year = past.groupby(past["date"].dt.year)["modal_price_kg"].median()
                rows.append(
                    {
                        "commodity": c,
                        "low": by_year.min(),
                        "typical": by_year.median(),
                        "high": by_year.max(),
                        "now": cur["modal_price_kg"],
                    }
                )
            if rows:
                bdf = pd.DataFrame(rows)
                bdf = bdf.assign(gap=(bdf["now"] / bdf["typical"] - 1).abs()).nlargest(10, "gap")
                for c_ in ("low", "high", "now"):  # everything relative to the usual price (= 100)
                    bdf[c_ + "_i"] = bdf[c_] / bdf["typical"] * 100
                bdf["label"] = bdf["now_i"].map(lambda v: f"{v - 100:+.0f}%")
                bdf["label_x"] = bdf[["high_i", "now_i"]].max(axis=1)  # label sits clear of band and dot
                order = bdf["commodity"].tolist()
                y = alt.Y("commodity:N", sort=order, title=None)
                xs = alt.Scale(domain=[0, max(200, float(bdf[["high_i", "now_i"]].max().max()) + 20)])
                tips = [
                    alt.Tooltip("commodity:N", title="Item"),
                    alt.Tooltip("now:Q", title="Latest ₹/kg", format=",.1f"),
                    alt.Tooltip("typical:Q", title="Typical ₹/kg", format=",.1f"),
                    alt.Tooltip("low:Q", title="5-yr low ₹/kg", format=",.1f"),
                    alt.Tooltip("high:Q", title="5-yr high ₹/kg", format=",.1f"),
                ]
                band = (
                    alt.Chart(bdf)
                    .mark_bar(height=14, cornerRadius=7, color=t["grid"])
                    .encode(
                        y=y,
                        x=alt.X("low_i:Q", title="% of the usual price for this month", scale=xs),
                        x2="high_i:Q",
                        tooltip=tips,
                    )
                )
                usual = (
                    alt.Chart(pd.DataFrame({"x": [100]}))
                    .mark_rule(color=t["muted"], strokeDash=[3, 3])
                    .encode(x=alt.X("x:Q", scale=xs))
                )
                dot = (
                    alt.Chart(bdf)
                    .mark_point(filled=True, size=120, stroke=t["surface"], strokeWidth=2)
                    .encode(
                        y=y,
                        x=alt.X("now_i:Q", scale=xs),
                        color=alt.condition("datum.now_i > 100", alt.value(t["up"]), alt.value(t["down"])),
                        tooltip=tips,
                    )
                )
                lbl = (
                    alt.Chart(bdf)
                    .mark_text(align="left", dx=12, fontSize=11.5, color=t["ink2"])
                    .encode(y=y, x=alt.X("label_x:Q", scale=xs), text="label:N")
                )
                show(alt.layer(band, usual, dot, lbl), 30 * len(bdf) + 50)
                st.html(
                    '<div class="fpr-sub">Grey band = 5-year range · dashed line = usual price · dot = latest '
                    '(<span class="fpr-up">red</span> pricier than usual, <span class="fpr-down">green</span> cheaper)</div>'
                )

        st.html('<div style="height:14px"></div>')

        # ── row 4: seasonality + long-term trend ────────────────────────────────────────────────
        left, right = st.columns([1, 1], gap="medium")
        with left, st.container(key="card-ov-season"):
            card_head("When do prices peak?", "Average price by month as % of that year's average (100 = normal)")
            hs = hubd[hubd["commodity"].isin(TOP3)].copy()
            hs["year"], hs["month"] = hs["date"].dt.year, hs["date"].dt.month
            mon = hs.groupby(["commodity", "year", "month"], as_index=False)["modal_price_kg"].median()
            mon["idx"] = (
                mon["modal_price_kg"] / mon.groupby(["commodity", "year"])["modal_price_kg"].transform("mean") * 100
            )
            season = mon.groupby(["commodity", "month"], as_index=False)["idx"].mean()
            season["mon"] = pd.to_datetime(season["month"], format="%m").dt.strftime("%b")
            months = pd.date_range("2024-01-01", periods=12, freq="MS").strftime("%b").tolist()
            color = alt.Color("commodity:N", scale=alt.Scale(domain=TOP3, range=t["series"][:3]), sort=TOP3)
            x = alt.X("mon:N", sort=months, title=None, axis=alt.Axis(labelAngle=0))
            lines = (
                alt.Chart(season)
                .mark_line(strokeWidth=2, interpolate="monotone")
                .encode(x=x, y=alt.Y("idx:Q", title="% of yearly average", scale=alt.Scale(zero=False)), color=color)
            )
            pts = (
                alt.Chart(season)
                .mark_point(filled=True, size=40, stroke=t["surface"], strokeWidth=1.5)
                .encode(
                    x=x,
                    y="idx:Q",
                    color=color,
                    tooltip=[
                        alt.Tooltip("commodity:N", title="Item"),
                        alt.Tooltip("mon:N", title="Month"),
                        alt.Tooltip("idx:Q", title="% of yearly avg", format=".0f"),
                    ],
                )
            )
            base100 = (
                alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(color=t["muted"], strokeDash=[3, 3]).encode(y="y:Q")
            )
            show(alt.layer(base100, lines, pts), 280)

        with right, st.container(key="card-ov-years"):
            card_head("Long-term price trend", f"Yearly median price at {HUB} · hover for values")
            yr = (
                hubd[hubd["commodity"].isin(TOP3) & (hubd["date"].dt.year < hubd["date"].max().year)]
                .assign(date=lambda d: pd.to_datetime(d["date"].dt.year.astype(str) + "-01-01"))
                .groupby(["date", "commodity"], as_index=False)["modal_price_kg"]
                .median()
            )
            ch = line_chart(yr, "commodity", "modal_price_kg", TOP3, "₹/kg")
            ch.layer[0].encoding.x = alt.X("date:T", title=None, axis=alt.Axis(format="%Y", labelAngle=0))
            show(ch, 280)

        # ── row 5: seasonal calendar for every item ─────────────────────────────────────────────
        st.html('<div style="height:14px"></div>')
        with st.container(key="card-ov-calendar"):
            card_head(
                "Seasonal price calendar",
                f"Each item's typical price by month at {HUB}, as % of its yearly average · "
                f'<span style="color:{t["div_pos"]};font-weight:600">blue = cheaper</span> · '
                f'<span style="color:{t["div_neg"]};font-weight:600">red = pricier</span>',
            )
            ha = hubd.copy()
            ha["year"], ha["month"] = ha["date"].dt.year, ha["date"].dt.month
            m_ = ha.groupby(["commodity", "year", "month"], as_index=False)["modal_price_kg"].median()
            yearly = m_.groupby(["commodity", "year"])["modal_price_kg"].transform("mean")
            full_years = m_.groupby(["commodity", "year"])["month"].transform("nunique") >= 9  # skip partial years
            m_ = m_[full_years].assign(idx=lambda d: d["modal_price_kg"] / yearly[full_years] * 100)
            calv = m_.groupby(["commodity", "month"], as_index=False).agg(
                idx=("idx", "mean"), years=("year", "nunique")
            )
            calv = calv[calv.groupby("commodity")["years"].transform("min") >= 3]
            calv["mon"] = pd.to_datetime(calv["month"], format="%m").dt.strftime("%b")
            calv["label"] = calv["idx"].round().astype(int).astype(str)
            # order items by the month they peak, so the calendar reads as a diagonal sweep
            peak = calv.loc[calv.groupby("commodity")["idx"].idxmax()].set_index("commodity")["month"]
            items = peak.sort_values().index.tolist()
            months = pd.date_range("2024-01-01", periods=12, freq="MS").strftime("%b").tolist()
            y = alt.Y("commodity:N", sort=items, title=None, axis=alt.Axis(labelLimit=160))
            x = alt.X("mon:N", sort=months, title=None, axis=alt.Axis(orient="top", labelAngle=0))
            heat = (
                alt.Chart(calv)
                .mark_rect(cornerRadius=3, stroke=t["surface"], strokeWidth=2)
                .encode(
                    x=x,
                    y=y,
                    color=alt.Color(
                        "idx:Q",
                        title="% of yearly avg",
                        scale=alt.Scale(
                            domain=[60, 100, 140],
                            range=[t["div_pos"], t["div_mid"], t["div_neg"]],
                            interpolate="lab",
                            clamp=True,
                        ),
                        legend=alt.Legend(orient="right", direction="vertical", gradientLength=160),
                    ),
                    tooltip=[
                        alt.Tooltip("commodity:N", title="Item"),
                        alt.Tooltip("mon:N", title="Month"),
                        alt.Tooltip("idx:Q", title="% of yearly avg", format=".0f"),
                        alt.Tooltip("years:Q", title="Years of data"),
                    ],
                )
            )
            txt = (
                alt.Chart(calv)
                .mark_text(fontSize=10)
                .encode(
                    x=x,
                    y=y,
                    text="label:N",
                    color=alt.condition(
                        "datum.idx > 128 || datum.idx < 72", alt.value("#ffffff"), alt.value(t["ink2"])
                    ),
                )
            )
            show(alt.layer(heat, txt), 24 * len(items) + 30)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# India: compare cities
# ════════════════════════════════════════════════════════════════════════════════════════════════
def comparison_window(cd: pd.DataFrame, min_cities: int = 5) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The latest 4-week window that at least `min_cities` cities have data in, so cities compare like-for-like."""
    ends = sorted(cd["date"].dt.normalize().unique(), reverse=True)
    checked = set()
    for end in ends:
        end = pd.Timestamp(end)
        key = end.to_period("W")
        if key in checked:
            continue
        checked.add(key)
        w = cd[(cd["date"] > end - pd.Timedelta(days=28)) & (cd["date"] <= end)]
        if w["city"].nunique() >= min(min_cities, cd["city"].nunique()):
            return end - pd.Timedelta(days=27), end
        if len(checked) > 120:
            break
    end = cd["date"].max()
    return end - pd.Timedelta(days=27), end


if PAGE == "India" and not cityd.empty:
    with content:
        lo, hi = comparison_window(cityd[["date", "city"]].drop_duplicates())
        win = cityd[(cityd["date"] >= lo) & (cityd["date"] <= hi)]
        cur = win.groupby(["commodity", "city"], as_index=False).agg(
            price=("modal_price_kg", "median"), days=("date", "nunique")
        )
        spread_x = cur.groupby("commodity")["price"].agg(lambda p: p.max() / p.min() if p.min() > 0 else float("inf"))
        MIXED_UNITS = set(spread_x[spread_x > 8].index)  # e.g. coriander: some markets quote per bunch
        items = [c for c in COMMODITY_ORDER if c in set(cur["commodity"])]

        with st.container(key="card-in-pick"):
            f1, f2 = st.columns([1, 2.4], vertical_alignment="bottom")
            with f1:
                item = st.selectbox("Item", items, index=0, key="in_item")
            with f2:
                st.html(
                    f'<div class="fpr-sub" style="margin:0 0 8px">Comparing the 4 weeks {lo:%d %b} – {hi:%d %b %Y}: '
                    "the latest window most cities report in. A city's price is the median of its markets.</div>"
                )
            ci = cur[cur["commodity"] == item].sort_values("price")
            if item in MIXED_UNITS:
                st.warning(
                    f"{item}: markets quote this item in different units (per kg vs per bunch), so a "
                    "cross-city comparison isn't meaningful. The city pages still show each city's own trend."
                )
                ci = ci.iloc[0:0]
            if len(ci) >= 2:
                lo_c, hi_c = ci.iloc[0], ci.iloc[-1]
                nat = ci["price"].median()
                mine = ci[ci["city"] == CITY]
                mine_txt = f"{rs(mine['price'].iloc[0])}<small>/kg</small>" if len(mine) else "–"
                mine_foot = (
                    f"{(mine['price'].iloc[0] / nat - 1) * 100:+.0f}% vs India median {rs(nat)}"
                    if len(mine)
                    else "no recent data for this city"
                )
                st.html(f"""<div class="fpr-tiles" style="margin-top:6px">
<div class="fpr-tile"><div class="fpr-tile-label">Cheapest city</div><div class="fpr-tile-value">{rs(lo_c["price"])}<small>/kg</small></div>
  <div class="fpr-tile-foot">{html.escape(lo_c["city"])}</div></div>
<div class="fpr-tile"><div class="fpr-tile-label">Priciest city</div><div class="fpr-tile-value">{rs(hi_c["price"])}<small>/kg</small></div>
  <div class="fpr-tile-foot">{html.escape(hi_c["city"])}</div></div>
<div class="fpr-tile"><div class="fpr-tile-label">Price gap across India</div>
  <div class="fpr-tile-value">{(hi_c["price"] / lo_c["price"] - 1) * 100:.0f}%</div>
  <div class="fpr-tile-foot">priciest vs cheapest · {len(ci)} cities reporting</div></div>
<div class="fpr-tile"><div class="fpr-tile-label">{html.escape(CITY)}</div><div class="fpr-tile-value">{mine_txt}</div>
  <div class="fpr-tile-foot">{mine_foot}</div></div></div>""")
        st.html('<div style="height:14px"></div>')

        left, right = st.columns([1, 1.5], gap="medium")
        with left, st.container(key="card-in-rank"):
            card_head(f"{item}: price by city", "Median over the comparison window · selected city highlighted")
            if not ci.empty:
                ci = ci.assign(
                    sel=ci["city"].eq(CITY).map({True: "Selected city", False: "Other cities"}), lbl=ci["price"].map(rs)
                )
                bars = (
                    alt.Chart(ci)
                    .mark_bar(cornerRadiusEnd=4, height=16)
                    .encode(
                        y=alt.Y("city:N", sort=ci["city"].tolist(), title=None),
                        x=alt.X("price:Q", title="₹/kg"),
                        color=alt.Color(
                            "sel:N",
                            scale=alt.Scale(
                                domain=["Selected city", "Other cities"], range=[t["series"][0], t["axis"]]
                            ),
                            legend=None,
                        ),
                        tooltip=[
                            alt.Tooltip("city:N", title="City"),
                            alt.Tooltip("price:Q", title="₹/kg", format=",.1f"),
                            alt.Tooltip("days:Q", title="Days with data"),
                        ],
                    )
                )
                lbl = (
                    alt.Chart(ci)
                    .mark_text(align="left", dx=6, fontSize=11.5, color=t["ink2"])
                    .encode(
                        y=alt.Y("city:N", sort=ci["city"].tolist()),
                        x="price:Q",
                        text="lbl:N",
                    )
                )
                show(alt.layer(bars, lbl), 30 * len(ci) + 40)

        with right, st.container(key="card-in-trend"):
            card_head(
                f"{item}: price trend by city", "Weekly median · last 3 years of each city's data · hover to compare"
            )
            have = [c for c in CITIES if c in set(cityd.loc[cityd["commodity"] == item, "city"])]
            default = [c for c in [CITY, "Delhi NCR", "Mumbai", "Bengaluru", "Kolkata"] if c in have]
            pick = st.multiselect(
                "Cities (up to 4)", have, default=list(dict.fromkeys(default))[:4], max_selections=4, key="in_cities"
            )
            tr = cityd[(cityd["commodity"] == item) & cityd["city"].isin(pick)]
            tr = tr[tr["date"] >= tr["date"].max() - pd.Timedelta(days=3 * 365)] if not tr.empty else tr
            trw = (
                tr.assign(date=tr["date"].dt.to_period("W").dt.start_time)
                .groupby(["date", "city"], as_index=False)["modal_price_kg"]
                .median()
            )
            if not trw.empty:
                show(line_chart(trw, "city", "modal_price_kg", [c for c in CITIES if c in pick], "₹/kg"), 300)

        st.html('<div style="height:14px"></div>')
        with st.container(key="card-in-heat"):
            card_head(
                "Where each item is cheap or expensive right now",
                "Each city's price vs the India median for that item, same 4-week window · "
                f'<span style="color:{t["div_pos"]};font-weight:600">blue = cheaper</span> · '
                f'<span style="color:{t["div_neg"]};font-weight:600">red = pricier</span>',
            )
            hm = cur[~cur["commodity"].isin(MIXED_UNITS)].copy()
            hm["nat"] = hm.groupby("commodity")["price"].transform("median")
            hm = hm[hm.groupby("commodity")["city"].transform("nunique") >= 3]  # need a few cities to compare
            hm["vs"] = (hm["price"] / hm["nat"] - 1) * 100
            hm["label"] = hm["vs"].map(lambda v: f"{v:+.0f}")
            rows = [c for c in COMMODITY_ORDER if c in set(hm["commodity"])]
            cols = [c for c in CITIES if c in set(hm["city"])]
            x = alt.X("city:N", sort=cols, title=None, axis=alt.Axis(orient="top", labelAngle=0))
            y = alt.Y("commodity:N", sort=rows, title=None, axis=alt.Axis(labelLimit=160))
            heat = (
                alt.Chart(hm)
                .mark_rect(cornerRadius=3, stroke=t["surface"], strokeWidth=2)
                .encode(
                    x=x,
                    y=y,
                    color=alt.Color(
                        "vs:Q",
                        title="% vs India",
                        scale=alt.Scale(
                            domain=[-50, 0, 50],
                            range=[t["div_pos"], t["div_mid"], t["div_neg"]],
                            interpolate="lab",
                            clamp=True,
                        ),
                        legend=alt.Legend(orient="right", direction="vertical", gradientLength=160),
                    ),
                    tooltip=[
                        alt.Tooltip("commodity:N", title="Item"),
                        alt.Tooltip("city:N", title="City"),
                        alt.Tooltip("price:Q", title="₹/kg", format=",.1f"),
                        alt.Tooltip("nat:Q", title="India median ₹/kg", format=",.1f"),
                        alt.Tooltip("vs:Q", title="% vs India", format="+.0f"),
                    ],
                )
            )
            txt = (
                alt.Chart(hm)
                .mark_text(fontSize=10)
                .encode(
                    x=x,
                    y=y,
                    text="label:N",
                    color=alt.condition("datum.vs > 32 || datum.vs < -32", alt.value("#ffffff"), alt.value(t["ink2"])),
                )
            )
            show(alt.layer(heat, txt), 24 * len(rows) + 40)
            if MIXED_UNITS:
                st.html(
                    f'<div class="fpr-sub">Not compared: {", ".join(sorted(MIXED_UNITS))}, because markets quote '
                    "them in different units (per kg vs per bunch).</div>"
                )

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Prices
# ════════════════════════════════════════════════════════════════════════════════════════════════
if PAGE == "Prices":
    with content, st.container(key="card-prices"):
        commodities = [c for c in COMMODITY_ORDER if c in set(daily["commodity"])]
        f1, f2, f3 = st.columns([1, 2, 1.3], vertical_alignment="bottom")
        with f1:
            commodity = st.selectbox("Item", commodities, index=0)
        sub = daily[daily["commodity"] == commodity]
        # stable order (and so stable colors): the selected city's markets first, then every other market
        city_markets = sorted(sub.loc[sub["city"] == CITY, "market"].unique())
        all_mandis = city_markets + sorted(m for m in sub["market"].unique() if m not in city_markets)
        with f2:
            sources = [ln.split(":")[1].split("→")[0].strip() for ln in LANES if ln.startswith(commodity + ":")]
            default = [m for m in [*city_markets, *sources] if m in all_mandis][:4] or all_mandis[:2]
            mandis = st.multiselect("Markets (up to 4)", all_mandis, default=default, max_selections=4)
        with f3:
            period = st.segmented_control("Period", ["1Y", "3Y", "5Y", "All"], default="3Y")
        years = {"1Y": 1, "3Y": 3, "5Y": 5}.get(period or "3Y")
        view = sub[sub["market"].isin(mandis)]
        if years and not view.empty:
            view = view[view["date"] >= view["date"].max() - pd.Timedelta(days=365 * years)]
        weekly = (
            view.assign(date=view["date"].dt.to_period("W").dt.start_time)
            .groupby(["date", "market"], as_index=False)["modal_price_kg"]
            .median()
        )
        card_head(f"{commodity} · weekly median price", "Hover to compare markets on the same week")
        if weekly.empty:
            st.info("Pick at least one market.")
        else:
            domain = [m for m in all_mandis if m in mandis]
            # colors follow the mandi's position in the stable list, not the selection order
            chart = line_chart(weekly, "market", "modal_price_kg", domain, "₹/kg")
            show(chart, 340)

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Volatility
# ════════════════════════════════════════════════════════════════════════════════════════════════
if PAGE == "Volatility":
    with content:
        if not vol.empty:
            hubv = cityv[(cityv["city"] == CITY) & cityv["log_return"].notna()]
            with st.container(key="card-vol-roll"):
                card_head("Rolling 30-day volatility", "Spikes mark supply shocks: monsoon, festivals, export bans")
                pick = st.multiselect(
                    "Items (up to 4)",
                    [c for c in COMMODITY_ORDER if c in set(hubv["commodity"])],
                    default=[c for c in ["Tomato", "Onion", "Potato"] if c in set(hubv["commodity"])],
                    max_selections=4,
                    key="volpick",
                )
                rv = hubv[hubv["commodity"].isin(pick) & (hubv["obs_30d"] >= 10)]
                rv = rv[rv["date"] >= rv["date"].max() - pd.Timedelta(days=5 * 365)] if not rv.empty else rv
                rvw = (
                    rv.assign(date=rv["date"].dt.to_period("W").dt.start_time)
                    .groupby(["date", "commodity"], as_index=False)["vol_30d_pct"]
                    .median()
                )
                domain = [c for c in COMMODITY_ORDER if c in pick]
                if not rvw.empty:
                    show(line_chart(rvw, "commodity", "vol_30d_pct", domain, "30-day volatility, %"), 280)
            st.html('<div style="height:14px"></div>')
            with st.container(key="card-vol-rank"):
                card_head(f"How much each item's price swings at {HUB}", "Average daily price change, all history")
                rank = (hubv.groupby("commodity")["log_return"].std() * 100).reset_index(name="vol")
                rank["category"] = rank["commodity"].map(lambda c: CATEGORY.get(c, "other").capitalize())
                rank = rank.sort_values("vol", ascending=False)
                cats = [c for c in ["Vegetable", "Fruit", "Herb"] if c in set(rank["category"])]
                bars = (
                    alt.Chart(rank)
                    .mark_bar(cornerRadiusEnd=4, height=14)
                    .encode(
                        y=alt.Y("commodity:N", sort=rank["commodity"].tolist(), title=None),
                        x=alt.X("vol:Q", title="average daily price change, %", axis=alt.Axis(format=".0f")),
                        color=alt.Color(
                            "category:N",
                            scale=alt.Scale(domain=cats, range=t["series"][: len(cats)]),
                            legend=alt.Legend(symbolType="square"),
                        ),
                        tooltip=[
                            alt.Tooltip("commodity:N", title="Item"),
                            alt.Tooltip("category:N", title="Category"),
                            alt.Tooltip("vol:Q", title="Daily swing %", format=".1f"),
                        ],
                    )
                )
                labels = (
                    alt.Chart(rank)
                    .mark_text(align="left", dx=6, color=t["ink2"], fontSize=11.5)
                    .encode(
                        y=alt.Y("commodity:N", sort=rank["commodity"].tolist()),
                        x="vol:Q",
                        text=alt.Text("vol:Q", format=".1f"),
                    )
                )
                show(alt.layer(bars, labels), 22 * len(rank) + 40)

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Sourcing
# ════════════════════════════════════════════════════════════════════════════════════════════════
if PAGE == "Sourcing":
    with content:
        if not LANES:
            no_lanes()
        elif not spread.empty:
            top_l, top_r = st.columns([1.7, 1], gap="medium")
            with top_l, st.container(key="card-src-lane"):
                f1, f2 = st.columns([1.4, 1], vertical_alignment="bottom")
                with f1:
                    lane = st.selectbox("Lane", LANES, key="lane")
                with f2:
                    sp_period = st.segmented_control("Period", ["1Y", "3Y", "All"], default="3Y", key="spp")
                s = spread[spread["lane"] == lane].sort_values("date")
                yrs = {"1Y": 1, "3Y": 3}.get(sp_period or "3Y")
                if yrs:
                    s = s[s["date"] >= s["date"].max() - pd.Timedelta(days=365 * yrs)]
                freight = s["freight_per_kg"].iloc[0] if len(s) else 0
                card_head(
                    f"{HUB} price vs landed cost from {lane.split(':')[1].split('→')[0].strip()}",
                    f"Landed cost = source modal + ₹{freight:.1f}/kg assumed freight · weekly medians",
                )
                long = s.melt("date", ["dst_price_kg", "landed_cost_kg"], "series", "rs").replace(
                    {"dst_price_kg": f"{HUB} price", "landed_cost_kg": "Landed cost"}
                )
                long = (
                    long.assign(date=long["date"].dt.to_period("W").dt.start_time)
                    .groupby(["date", "series"], as_index=False)["rs"]
                    .median()
                )
                show(line_chart(long, "series", "rs", [f"{HUB} price", "Landed cost"], "₹/kg"), 290)
            with top_r:
                all_s = spread[spread["lane"] == lane]
                share = all_s["direct_sourcing_cheaper"].mean() * 100
                st.html(
                    f"""<div class="fpr-tiles" style="grid-template-columns:1fr">
<div class="fpr-tile"><div class="fpr-tile-label">Direct sourcing cheaper</div>
  <div class="fpr-tile-value">{share:.0f}%<small>of days</small></div>
  <div class="fpr-tile-foot">{len(all_s):,} days compared, all history</div></div>
<div class="fpr-tile"><div class="fpr-tile-label">Median saving if bought direct</div>
  <div class="fpr-tile-value">{rs(all_s["spread_kg"].median())}<small>/kg</small></div>
  <div class="fpr-tile-foot">Negative = {HUB} is cheaper · 90th pct {rs(all_s["spread_kg"].quantile(0.9))}</div></div>
</div>"""
                )
        st.html('<div style="height:14px"></div>')
        with st.container(key="card-src-all"):
            card_head(
                "Every lane in India: how often buying direct beats the city price",
                "Share of days the landed cost (source + freight) was lower",
            )
            sh = (spread.groupby("lane")["direct_sourcing_cheaper"].mean() * 100).reset_index(name="share")
            bars = (
                alt.Chart(sh)
                .mark_bar(cornerRadiusEnd=4, height=18, color=t["series"][0])
                .encode(
                    y=alt.Y("lane:N", sort=ALL_LANES, title=None, axis=alt.Axis(labelLimit=260)),
                    x=alt.X("share:Q", title="% of days direct is cheaper", scale=alt.Scale(domain=[0, 100])),
                    tooltip=[
                        alt.Tooltip("lane:N", title="Lane"),
                        alt.Tooltip("share:Q", title="% of days", format=".1f"),
                    ],
                )
            )
            labels = bars.mark_text(align="left", dx=6, color=t["ink2"], fontSize=12).encode(
                text=alt.Text("share:Q", format=".0f")
            )
            even = alt.Chart(pd.DataFrame({"x": [50]})).mark_rule(color=t["muted"], strokeDash=[3, 3]).encode(x="x:Q")
            show(alt.layer(bars, labels, even), 26 * len(ALL_LANES) + 50)

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Signals
# ════════════════════════════════════════════════════════════════════════════════════════════════
if PAGE == "Signals":
    with content:
        if not LANES:
            no_lanes()
        else:
            if not alerts.empty:
                with st.container(key="card-sig-now"):
                    card_head(
                        "Latest weekly signal per lane", "Alert = source market's weekly price up ≥10% week-on-week"
                    )
                    cards = []
                    for _, a in (
                        alerts.set_index("lane").reindex(LANES).dropna(subset=["message"]).reset_index().iterrows()
                    ):
                        on = bool(a["alert"])
                        chg = a["source_week_change_pct"]
                        cls = "fpr-up" if on else ""  # red only when the rule fires
                        chip = (
                            '<span class="fpr-status fpr-fail">▲ Alert</span>'
                            if on
                            else '<span class="fpr-status fpr-pass">● Calm</span>'
                        )
                        cards.append(
                            f'<div class="fpr-alert {"on" if on else ""}"><div class="lane">{html.escape(a["lane"])}</div>'
                            f'<div class="chg {cls}">{chg:+.1f}%</div>'
                            f'<div class="msg">{chip} · week of {a["week_of"]:%d %b %Y}<br>{html.escape(a["message"].replace(">=", "≥"))}</div></div>'
                        )
                    st.html(f'<div class="fpr-alerts">{"".join(cards)}</div>')
            st.html('<div style="height:14px"></div>')
            left, right = st.columns([1, 1], gap="medium")
            with left, st.container(key="card-sig-bt"):
                card_head("Does the alert work?", "% of weeks Delhi rose the week after a source spike vs in any week")
                if not bt.empty:
                    d = bt[bt["lane"].isin(LANES)].copy()
                    d["lane"] = pd.Categorical(d["lane"], LANES)
                    long = d.melt(["lane", "n_spikes"], ["hit_rate_pct", "base_rate_up_pct"], "kind", "rate").replace(
                        {"hit_rate_pct": "After a spike", "base_rate_up_pct": "Any week"}
                    )
                    y = alt.Y("lane:N", sort=LANES, title=None, axis=alt.Axis(labelLimit=230))
                    x = alt.X("rate:Q", title="% of weeks Delhi rose", scale=alt.Scale(domain=[30, 70]))
                    link = (
                        alt.Chart(d)
                        .mark_rule(color=t["axis"], strokeWidth=3)
                        .encode(
                            y=y, x=alt.X("base_rate_up_pct:Q", scale=alt.Scale(domain=[30, 70])), x2="hit_rate_pct:Q"
                        )
                    )
                    dots = (
                        alt.Chart(long)
                        .mark_point(filled=True, size=120, strokeWidth=2)
                        .encode(
                            y=y,
                            x=x,
                            color=alt.Color(
                                "kind:N",
                                scale=alt.Scale(
                                    domain=["After a spike", "Any week"], range=[t["series"][0], t["muted"]]
                                ),
                                legend=alt.Legend(symbolType="circle", symbolSize=90),
                            ),
                            tooltip=[
                                alt.Tooltip("lane:N", title="Lane"),
                                alt.Tooltip("kind:N", title=""),
                                alt.Tooltip("rate:Q", title="% weeks up", format=".1f"),
                                alt.Tooltip("n_spikes:Q", title="Spike episodes"),
                            ],
                        )
                    )
                    edge = (
                        alt.Chart(
                            d.assign(
                                edge=d["hit_rate_pct"] - d["base_rate_up_pct"],
                                xpos=d[["hit_rate_pct", "base_rate_up_pct"]].max(axis=1),
                            )
                        )
                        .mark_text(align="left", dx=10, fontSize=12, color=t["ink2"])
                        .encode(
                            y=y,
                            x=alt.X("xpos:Q", scale=alt.Scale(domain=[30, 70])),
                            text=alt.Text("edge:Q", format="+.1f"),
                        )
                    )
                    show(alt.layer(link, dots, edge), 46 * len(LANES) + 90)
            with right, st.container(key="card-sig-ll"):
                card_head(
                    "Does the source lead Delhi?",
                    "Correlation of week-on-week price changes, source leading by N weeks",
                )
                if not llw.empty:
                    h = llw[llw["lane"].isin(LANES)].copy()
                    h["txt"] = h["corr"].map(lambda v: f"{v:.2f}")
                    y = alt.Y("lane:N", sort=LANES, title=None, axis=alt.Axis(labelLimit=230))
                    x = alt.X("lag_weeks:O", title="source leads by (weeks)", axis=alt.Axis(labelAngle=0))
                    heat = (
                        alt.Chart(h)
                        .mark_rect(cornerRadius=4, stroke=t["surface"], strokeWidth=2)
                        .encode(
                            y=y,
                            x=x,
                            color=alt.Color(
                                "corr:Q",
                                title="corr",
                                scale=alt.Scale(
                                    domain=[-0.45, 0, 0.45],
                                    range=[t["div_neg"], t["div_mid"], t["div_pos"]],
                                    interpolate="lab",
                                ),
                                legend=alt.Legend(
                                    orient="right", direction="vertical", gradientLength=120, symbolType="square"
                                ),
                            ),
                            tooltip=[
                                alt.Tooltip("lane:N", title="Lane"),
                                alt.Tooltip("lag_weeks:O", title="Lead (weeks)"),
                                alt.Tooltip("corr:Q", title="Correlation", format=".3f"),
                                alt.Tooltip("n_weeks:Q", title="Paired weeks"),
                                alt.Tooltip("reliable:N", title="Reliable"),
                            ],
                        )
                    )
                    txt = (
                        alt.Chart(h)
                        .mark_text(fontSize=11.5)
                        .encode(
                            y=y,
                            x=x,
                            text="txt:N",
                            color=alt.condition("datum.corr > 0.25", alt.value("#ffffff"), alt.value(t["ink"])),
                        )
                    )
                    show(alt.layer(heat, txt), 40 * len(LANES) + 60)

# ════════════════════════════════════════════════════════════════════════════════════════════════
# Data quality
# ════════════════════════════════════════════════════════════════════════════════════════════════

pending.empty()
st.session_state.shown_page = PAGE
