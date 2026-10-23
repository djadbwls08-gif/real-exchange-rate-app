"""
Real Exchange Rate (RER) Explorer
=================================

Streamlit app that pulls monthly CPI and exchange-rate data from the IMF
SDMX 3.0 API and computes a bilateral real exchange rate.

Definitions
-----------
S(t)        units of Country 2 currency per 1 unit of Country 1 currency
P1(t), P2(t) monthly CPI of Country 1 and Country 2
RER(t)      S(t) * P1(t) / P2(t)
RER*        average of RER(t) over valid months in the selected sample
Real Index  100 * RER(t) / RER*

IMF exchange rates (XDC_USD) are local currency units per USD, so
    S(t) = E2(t) / E1(t)
where E_i(t) is Country i currency per USD.

Run:  streamlit run app.py      (Python 3.12)
"""

from __future__ import annotations

import io
import os
import re
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "https://api.imf.org/external/sdmx/3.0"
AGENCY = "IMF.STA"
CPI_FLOW = "CPI"
ER_FLOW = "ER"
CPI_KEY = "{iso3}.CPI._T.IX.M"          # monthly CPI index, all items
ER_KEY = "{iso3}.XDC_USD.PA_RT.M"       # monthly avg, domestic currency per USD
FIRST_MONTH = pd.Timestamp("1976-01-01")
EURO_AREA = "G163"
REQUEST_TIMEOUT = 60
# A month-on-month move in a per-USD exchange rate larger than this factor
# usually signals a currency redenomination or a currency changeover.
BREAK_FACTOR = 5.0

# IMF member countries (ISO3) plus the Euro area and a few other IMF-reported
# economies. Any other IMF code can be typed in the sidebar.
ECONOMIES: dict[str, str] = {
    EURO_AREA: "Euro area",
    "AFG": "Afghanistan", "ALB": "Albania", "DZA": "Algeria", "AND": "Andorra",
    "AGO": "Angola", "ATG": "Antigua and Barbuda", "ARG": "Argentina",
    "ARM": "Armenia", "ABW": "Aruba", "AUS": "Australia", "AUT": "Austria",
    "AZE": "Azerbaijan", "BHS": "Bahamas", "BHR": "Bahrain",
    "BGD": "Bangladesh", "BRB": "Barbados", "BLR": "Belarus", "BEL": "Belgium",
    "BLZ": "Belize", "BEN": "Benin", "BTN": "Bhutan", "BOL": "Bolivia",
    "BIH": "Bosnia and Herzegovina", "BWA": "Botswana", "BRA": "Brazil",
    "BRN": "Brunei Darussalam", "BGR": "Bulgaria", "BFA": "Burkina Faso",
    "BDI": "Burundi", "CPV": "Cabo Verde", "KHM": "Cambodia",
    "CMR": "Cameroon", "CAN": "Canada", "CAF": "Central African Republic",
    "TCD": "Chad", "CHL": "Chile", "CHN": "China", "COL": "Colombia",
    "COM": "Comoros", "COD": "Congo, Dem. Rep.", "COG": "Congo, Rep.",
    "CRI": "Costa Rica", "CIV": "Côte d'Ivoire", "HRV": "Croatia",
    "CUW": "Curaçao", "CYP": "Cyprus", "CZE": "Czech Republic",
    "DNK": "Denmark", "DJI": "Djibouti", "DMA": "Dominica",
    "DOM": "Dominican Republic", "ECU": "Ecuador", "EGY": "Egypt",
    "SLV": "El Salvador", "GNQ": "Equatorial Guinea", "ERI": "Eritrea",
    "EST": "Estonia", "SWZ": "Eswatini", "ETH": "Ethiopia", "FJI": "Fiji",
    "FIN": "Finland", "FRA": "France", "GAB": "Gabon", "GMB": "Gambia",
    "GEO": "Georgia", "DEU": "Germany", "GHA": "Ghana", "GRC": "Greece",
    "GRD": "Grenada", "GTM": "Guatemala", "GIN": "Guinea",
    "GNB": "Guinea-Bissau", "GUY": "Guyana", "HTI": "Haiti",
    "HND": "Honduras", "HKG": "Hong Kong SAR", "HUN": "Hungary",
    "ISL": "Iceland", "IND": "India", "IDN": "Indonesia", "IRN": "Iran",
    "IRQ": "Iraq", "IRL": "Ireland", "ISR": "Israel", "ITA": "Italy",
    "JAM": "Jamaica", "JPN": "Japan", "JOR": "Jordan", "KAZ": "Kazakhstan",
    "KEN": "Kenya", "KIR": "Kiribati", "KOR": "Korea", "KWT": "Kuwait",
    "KGZ": "Kyrgyz Republic", "LAO": "Lao P.D.R.", "LVA": "Latvia",
    "LBN": "Lebanon", "LSO": "Lesotho", "LBR": "Liberia", "LBY": "Libya",
    "LIE": "Liechtenstein", "LTU": "Lithuania", "LUX": "Luxembourg",
    "MAC": "Macao SAR", "MDG": "Madagascar", "MWI": "Malawi",
    "MYS": "Malaysia", "MDV": "Maldives", "MLI": "Mali", "MLT": "Malta",
    "MHL": "Marshall Islands", "MRT": "Mauritania", "MUS": "Mauritius",
    "MEX": "Mexico", "FSM": "Micronesia", "MDA": "Moldova",
    "MNG": "Mongolia", "MNE": "Montenegro", "MAR": "Morocco",
    "MOZ": "Mozambique", "MMR": "Myanmar", "NAM": "Namibia", "NRU": "Nauru",
    "NPL": "Nepal", "NLD": "Netherlands", "NZL": "New Zealand",
    "NIC": "Nicaragua", "NER": "Niger", "NGA": "Nigeria",
    "MKD": "North Macedonia", "NOR": "Norway", "OMN": "Oman",
    "PAK": "Pakistan", "PLW": "Palau", "PAN": "Panama",
    "PNG": "Papua New Guinea", "PRY": "Paraguay", "PER": "Peru",
    "PHL": "Philippines", "POL": "Poland", "PRT": "Portugal", "QAT": "Qatar",
    "ROU": "Romania", "RUS": "Russia", "RWA": "Rwanda",
    "KNA": "St. Kitts and Nevis", "LCA": "St. Lucia",
    "VCT": "St. Vincent and the Grenadines", "WSM": "Samoa",
    "SMR": "San Marino", "STP": "São Tomé and Príncipe",
    "SAU": "Saudi Arabia", "SEN": "Senegal", "SRB": "Serbia",
    "SYC": "Seychelles", "SLE": "Sierra Leone", "SGP": "Singapore",
    "SVK": "Slovak Republic", "SVN": "Slovenia", "SLB": "Solomon Islands",
    "SOM": "Somalia", "ZAF": "South Africa", "SSD": "South Sudan",
    "ESP": "Spain", "LKA": "Sri Lanka", "SDN": "Sudan", "SUR": "Suriname",
    "SWE": "Sweden", "CHE": "Switzerland", "SYR": "Syria",
    "TJK": "Tajikistan", "TZA": "Tanzania", "THA": "Thailand",
    "TLS": "Timor-Leste", "TGO": "Togo", "TON": "Tonga",
    "TTO": "Trinidad and Tobago", "TUN": "Tunisia", "TUR": "Türkiye",
    "TKM": "Turkmenistan", "TUV": "Tuvalu", "UGA": "Uganda",
    "UKR": "Ukraine", "ARE": "United Arab Emirates",
    "GBR": "United Kingdom", "USA": "United States", "URY": "Uruguay",
    "UZB": "Uzbekistan", "VUT": "Vanuatu", "VEN": "Venezuela",
    "VNM": "Vietnam", "YEM": "Yemen", "ZMB": "Zambia", "ZWE": "Zimbabwe",
}
CUSTOM_OPTION = "Other IMF code…"


# ---------------------------------------------------------------------------
# HTTP + SDMX parsing
# ---------------------------------------------------------------------------
def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "rer-explorer/1.0 (python-requests)"
    key = os.environ.get("IMF_API_KEY")  # optional; the public API needs none
    if key:
        s.headers["Ocp-Apim-Subscription-Key"] = key
    return s


_PERIOD_RE = re.compile(r"^\s*(\d{4})-?M?(\d{1,2})")


def parse_period(value) -> pd.Timestamp | None:
    """Parse IMF monthly periods: '2024-M01', '2024M01', '2024-01', '2024-01-01'."""
    if value is None:
        return None
    m = _PERIOD_RE.match(str(value))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    return pd.Timestamp(year=year, month=month, day=1)


def _to_series(pairs: dict) -> pd.Series:
    """Map {period string: value} -> float Series indexed by month-start date."""
    data = {}
    for period, val in pairs.items():
        ts = parse_period(period)
        if ts is None:
            continue
        num = pd.to_numeric(val, errors="coerce")
        if pd.notna(num):
            data[ts] = float(num)
    s = pd.Series(data, dtype="float64").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s[s.index >= FIRST_MONTH]


def _dim_value(dim: dict, idx: int) -> str | None:
    values = dim.get("values", [])
    if idx >= len(values):
        return None
    v = values[idx]
    return v.get("id") or v.get("value") or v.get("start")


def parse_sdmx_json(payload: dict) -> pd.Series:
    """Parse SDMX-JSON (1.0 or 2.0) data messages into one monthly Series.

    If several series come back, the one with the most observations is used.
    """
    data = payload.get("data", payload)
    structures = data.get("structures")
    if not structures and "structure" in data:
        structures = [data["structure"]]
    datasets = data.get("dataSets") or []
    if not structures or not datasets:
        return pd.Series(dtype="float64")

    dims = structures[0].get("dimensions", {})
    series_dims = dims.get("series", [])
    obs_dims = dims.get("observation", [])

    def time_pos(dim_list):
        for i, d in enumerate(dim_list):
            if d.get("id") in ("TIME_PERIOD", "TIME") or d.get("role") == "time":
                return i
        return None

    candidates: list[dict] = []
    for ds in datasets:
        # Layout 1: series -> observations, time at the observation level
        if isinstance(ds.get("series"), dict):
            t = time_pos(obs_dims)
            if t is None:
                t = 0
            for s in ds["series"].values():
                pairs = {}
                for okey, oval in (s.get("observations") or {}).items():
                    parts = str(okey).split(":")
                    period = _dim_value(obs_dims[t], int(parts[t])) if obs_dims else None
                    val = oval[0] if isinstance(oval, list) and oval else oval
                    if period is not None:
                        pairs[period] = val
                candidates.append(pairs)
        # Layout 2: flat observations, all dimensions in the key
        elif isinstance(ds.get("observations"), dict):
            t = time_pos(obs_dims)
            if t is None:
                continue
            pairs = {}
            for okey, oval in ds["observations"].items():
                parts = str(okey).split(":")
                period = _dim_value(obs_dims[t], int(parts[t]))
                val = oval[0] if isinstance(oval, list) and oval else oval
                if period is not None:
                    pairs[period] = val
            candidates.append(pairs)
    _ = series_dims  # series dims are not needed: the key pins one series
    if not candidates:
        return pd.Series(dtype="float64")
    best = max(candidates, key=len)
    return _to_series(best)


def parse_sdmx_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    cols = {c.upper(): c for c in df.columns}
    tcol, vcol = cols.get("TIME_PERIOD"), cols.get("OBS_VALUE")
    if tcol is None or vcol is None:
        return pd.Series(dtype="float64")
    return _to_series(dict(zip(df[tcol], df[vcol])))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_imf_series(flow: str, key: str) -> tuple[pd.Series, str]:
    """Download one IMF series. Returns (series, note). Never raises."""
    url = f"{BASE_URL}/data/dataflow/{AGENCY}/{flow}/+/{key}"
    sess = _session()
    attempts = [
        ("json", {"Accept": "application/vnd.sdmx.data+json;version=2.0.0, application/json;q=0.9"},
         {"dimensionAtObservation": "TIME_PERIOD", "attributes": "none", "measures": "all"}),
        ("csv", {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0, text/csv;q=0.9"},
         {"attributes": "none", "measures": "all"}),
    ]
    last_note = ""
    for fmt, headers, params in attempts:
        try:
            r = sess.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_note = f"network error: {exc.__class__.__name__}"
            continue
        if r.status_code == 404:
            return pd.Series(dtype="float64"), "no data published by the IMF for this key"
        if r.status_code != 200:
            last_note = f"HTTP {r.status_code}"
            continue
        try:
            ctype = r.headers.get("Content-Type", "").lower()
            looks_json = "json" in ctype or r.text.lstrip().startswith("{")
            if looks_json:
                s = parse_sdmx_json(r.json())
            else:
                s = parse_sdmx_csv(r.text)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            last_note = f"could not parse {fmt} response ({exc.__class__.__name__})"
            continue
        if not s.empty:
            return s, "ok"
        last_note = "response contained no observations"
    return pd.Series(dtype="float64"), last_note or "unknown error"


def get_exchange_rate(iso3: str) -> tuple[pd.Series, str]:
    """Domestic currency per USD. The US dollar is 1 per USD by definition."""
    if iso3 == "USA":
        idx = pd.date_range(FIRST_MONTH, pd.Timestamp(date.today()).to_period("M").to_timestamp(), freq="MS")
        return pd.Series(1.0, index=idx), "USD per USD = 1 (by definition)"
    return fetch_imf_series(ER_FLOW, ER_KEY.format(iso3=iso3))


def get_cpi(iso3: str) -> tuple[pd.Series, str]:
    return fetch_imf_series(CPI_FLOW, CPI_KEY.format(iso3=iso3))


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def build_panel(e1: pd.Series, e2: pd.Series, p1: pd.Series, p2: pd.Series) -> pd.DataFrame:
    """Full monthly panel from Jan-1976 with S(t) and RER(t)."""
    pieces = [s for s in (e1, e2, p1, p2) if not s.empty]
    if not pieces:
        return pd.DataFrame()
    last = max(s.index.max() for s in pieces)
    idx = pd.date_range(FIRST_MONTH, last, freq="MS")
    df = pd.DataFrame(index=idx)
    df.index.name = "month"
    df["E1_per_USD"] = e1.reindex(idx)
    df["E2_per_USD"] = e2.reindex(idx)
    df["P1_CPI"] = p1.reindex(idx)
    df["P2_CPI"] = p2.reindex(idx)
    # Non-positive values are invalid for rates and price indices.
    for c in df.columns:
        df.loc[df[c] <= 0, c] = np.nan
    df["S"] = df["E2_per_USD"] / df["E1_per_USD"]
    df["RER"] = df["S"] * df["P1_CPI"] / df["P2_CPI"]
    df["valid"] = df["RER"].notna() & np.isfinite(df["RER"])
    return df


def apply_sample(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, float]:
    """Slice to [start, end], compute RER* over valid months, and the Real Index."""
    out = df.loc[start:end].copy()
    rer_star = float(out.loc[out["valid"], "RER"].mean()) if out["valid"].any() else float("nan")
    out["RER_star"] = rer_star
    out["Real_Index"] = 100.0 * out["RER"] / rer_star
    return out, rer_star


def find_breaks(s: pd.Series) -> list[str]:
    """Months where a per-USD rate jumps by more than BREAK_FACTOR month on month."""
    s = s.dropna()
    if len(s) < 2:
        return []
    ratio = s / s.shift(1)
    mask = (ratio > BREAK_FACTOR) | (ratio < 1 / BREAK_FACTOR)
    return [d.strftime("%Y-%m") for d in s.index[mask.fillna(False)]]


def coverage_row(label: str, s: pd.Series, note: str) -> dict:
    if s.empty:
        return {"Series": label, "First": "—", "Last": "—", "Months": 0, "Status": note}
    return {
        "Series": label,
        "First": s.index.min().strftime("%Y-%m"),
        "Last": s.index.max().strftime("%Y-%m"),
        "Months": int(s.notna().sum()),
        "Status": note,
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
REAL_COLOR = "#2563eb"
NOMINAL_COLOR = "#d97706"


def make_chart(sample: pd.DataFrame, view: str, name1: str, name2: str, log_nominal: bool) -> go.Figure:
    x = sample.index
    real_label = "Real Index (sample avg = 100)"
    nom_label = f"S: {name2} currency per 1 {name1} currency"
    real_trace = go.Scatter(
        x=x, y=sample["Real_Index"], name="Real Index", mode="lines",
        line=dict(color=REAL_COLOR, width=2), connectgaps=False,
        hovertemplate="%{x|%b %Y}<br>Real Index: %{y:.2f}<extra></extra>",
    )
    nom_trace = go.Scatter(
        x=x, y=sample["S"], name="Nominal S", mode="lines",
        line=dict(color=NOMINAL_COLOR, width=2), connectgaps=False,
        hovertemplate="%{x|%b %Y}<br>S: %{y:,.6g}<extra></extra>",
    )

    if view == "Both":
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(real_trace, secondary_y=False)
        fig.add_trace(nom_trace, secondary_y=True)
        fig.add_hline(y=100, line=dict(color="gray", dash="dot", width=1))
        fig.update_yaxes(title_text=real_label, secondary_y=False,
                         title_font=dict(color=REAL_COLOR), tickfont=dict(color=REAL_COLOR))
        fig.update_yaxes(title_text=nom_label, secondary_y=True, showgrid=False,
                         type="log" if log_nominal else "linear",
                         title_font=dict(color=NOMINAL_COLOR), tickfont=dict(color=NOMINAL_COLOR))
    elif view == "Real":
        fig = go.Figure(real_trace)
        fig.add_hline(y=100, line=dict(color="gray", dash="dot", width=1))
        fig.update_yaxes(title_text=real_label)
    else:
        fig = go.Figure(nom_trace)
        fig.update_yaxes(title_text=nom_label, type="log" if log_nominal else "linear")

    fig.update_layout(
        height=520,
        hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(title_text="Month", rangeslider=dict(visible=True, thickness=0.06))
    return fig


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def label_for(code: str) -> str:
    return f"{ECONOMIES[code]} ({code})" if code in ECONOMIES else code


def pick_economy(slot: str, default: str) -> tuple[str, str]:
    options = sorted(ECONOMIES, key=lambda c: (c != EURO_AREA, ECONOMIES[c])) + [CUSTOM_OPTION]
    choice = st.sidebar.selectbox(
        slot, options, index=options.index(default),
        format_func=lambda c: c if c == CUSTOM_OPTION else label_for(c),
        key=f"sel_{slot}",
    )
    if choice == CUSTOM_OPTION:
        code = st.sidebar.text_input(
            f"{slot}: IMF area code", value="", max_chars=8, key=f"txt_{slot}",
            help="ISO3 country code (e.g. TWN) or an IMF aggregate code such as G163.",
        ).strip().upper()
        return code, code
    return choice, ECONOMIES[choice]


def main() -> None:
    st.set_page_config(page_title="RER Explorer", page_icon="📈", layout="wide")
    st.title("Real Exchange Rate Explorer")
    st.caption(
        "Monthly IMF data (CPI and exchange rates, SDMX 3.0 API). "
        "S(t) = Country 2 currency per 1 unit of Country 1 currency · "
        "RER(t) = S(t) × P1(t) / P2(t) · Real Index = 100 × RER(t) / RER*"
    )

    st.sidebar.header("Countries")
    c1, name1 = pick_economy("Country 1", "USA")
    c2, name2 = pick_economy("Country 2", "KOR")
    if not c1 or not c2:
        st.info("Enter an IMF area code for each country to continue.")
        st.stop()
    if c1 == c2:
        st.warning("Country 1 and Country 2 are the same, so S(t) = 1 and RER(t) = 1 by construction.")

    with st.spinner("Downloading IMF data…"):
        e1, n_e1 = get_exchange_rate(c1)
        e2, n_e2 = get_exchange_rate(c2)
        p1, n_p1 = get_cpi(c1)
        p2, n_p2 = get_cpi(c2)

    coverage = pd.DataFrame([
        coverage_row(f"Exchange rate, {name1} ({c1}) per USD", e1, n_e1),
        coverage_row(f"Exchange rate, {name2} ({c2}) per USD", e2, n_e2),
        coverage_row(f"CPI, {name1} ({c1})", p1, n_p1),
        coverage_row(f"CPI, {name2} ({c2})", p2, n_p2),
    ])

    df = build_panel(e1, e2, p1, p2)
    if df.empty or not df["valid"].any():
        st.error(
            "No month has all four inputs (both exchange rates and both CPIs), "
            "so RER(t) cannot be computed for this pair."
        )
        st.dataframe(coverage, hide_index=True, width="stretch")
        st.stop()

    valid_months = df.index[df["valid"]]
    first_valid, last_valid = valid_months.min(), valid_months.max()

    # Sample period ---------------------------------------------------------
    st.sidebar.header("Sample period")
    month_opts = [d.strftime("%Y-%m") for d in pd.date_range(first_valid, last_valid, freq="MS")]
    pair_key = f"{c1}_{c2}"
    start_lbl, end_lbl = st.sidebar.select_slider(
        "Start and end month",
        options=month_opts,
        value=(month_opts[0], month_opts[-1]),
        key=f"range_{pair_key}",  # resets when the country pair changes
        help="RER* is recomputed as the average RER over valid months in this window.",
    )
    start, end = pd.Timestamp(start_lbl), pd.Timestamp(end_lbl)

    st.sidebar.header("Chart")
    view = st.sidebar.radio("Series to plot", ["Real", "Nominal", "Both"], index=2, horizontal=True)
    log_nominal = st.sidebar.checkbox(
        "Log scale for nominal S", value=False,
        help="Useful for high-inflation currencies. The values stay in actual currency units.",
    )

    sample, rer_star = apply_sample(df, start, end)
    n_valid = int(sample["valid"].sum())
    n_total = len(sample)

    # Headline metrics ------------------------------------------------------
    latest = sample.loc[sample["valid"]].iloc[-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("RER* (sample average)", f"{rer_star:,.6g}")
    m2.metric(f"Real Index, {latest.name:%b %Y}", f"{latest['Real_Index']:.1f}")
    m3.metric(f"Nominal S, {latest.name:%b %Y}", f"{latest['S']:,.6g}",
              help=f"{name2} currency per 1 {name1} currency")
    m4.metric("Valid months in sample", f"{n_valid} / {n_total}")

    st.plotly_chart(make_chart(sample, view, name1, name2, log_nominal), width="stretch")
    st.caption(
        f"A higher Real Index means a **real appreciation of {name1}'s currency** against {name2}'s: "
        f"{name1} goods become more expensive relative to {name2} goods. "
        "Gaps in the lines are months where an input is missing; they are excluded from RER*."
    )

    # Data-quality notes ----------------------------------------------------
    notes = []
    if n_valid < n_total:
        notes.append(f"{n_total - n_valid} month(s) in the sample are missing at least one input and are excluded from RER*.")
    for nm, code, s in ((name1, c1, e1), (name2, c2, e2)):
        brks = find_breaks(s.loc[start:end])
        if brks:
            notes.append(
                f"{nm} ({code}) exchange rate moves more than {BREAK_FACTOR:g}× in one month at "
                f"{', '.join(brks[:6])}{'…' if len(brks) > 6 else ''}. This often reflects a "
                "redenomination or currency changeover, so RER levels across that date may not be comparable."
            )
    if notes:
        with st.expander("Data notes", expanded=True):
            for n in notes:
                st.markdown(f"- {n}")

    # Download --------------------------------------------------------------
    export = sample.reset_index()
    export.insert(0, "month_str", export["month"].dt.strftime("%Y-%m"))
    export = export.drop(columns="month").rename(columns={"month_str": "month"})
    export.insert(1, "country1", c1)
    export.insert(2, "country2", c2)
    export = export.rename(columns={
        "E1_per_USD": f"E1_{c1}_per_USD",
        "E2_per_USD": f"E2_{c2}_per_USD",
        "P1_CPI": f"P1_CPI_{c1}",
        "P2_CPI": f"P2_CPI_{c2}",
        "S": f"S_{c2}_per_{c1}",
        "valid": "valid_month",
    })
    export["sample_start"] = start_lbl
    export["sample_end"] = end_lbl
    csv_bytes = export.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV (selected sample)",
        data=csv_bytes,
        file_name=f"rer_{c1}_{c2}_{start_lbl}_{end_lbl}.csv",
        mime="text/csv",
        type="primary",
    )

    with st.expander("Data table (selected sample)"):
        st.dataframe(export, hide_index=True, width="stretch")
    with st.expander("IMF data coverage"):
        st.dataframe(coverage, hide_index=True, width="stretch")
        st.caption(
            f"Source: IMF SDMX 3.0 API ({BASE_URL}). CPI key `{{ISO3}}.CPI._T.IX.M`, "
            f"exchange-rate key `{{ISO3}}.XDC_USD.PA_RT.M` (period average, domestic currency per USD). "
            f"Data requested from {FIRST_MONTH:%b %Y} where available."
        )


if __name__ == "__main__":
    main()
