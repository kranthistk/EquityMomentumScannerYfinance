import streamlit as st
import pandas as pd
import yfinance as yf
import time
from datetime import datetime
import pytz

st.set_page_config(page_title="NSE Watchlist Scanner", layout="wide")

st.title("📊 NSE Watchlist Momentum Scanner")
st.markdown("Auto-updates every **30 seconds** | Tracking select equity stocks")

# ── Watchlist ──────────────────────────────────────────────────────────────────
# NSE symbols on Yahoo Finance use the ".NS" suffix
WATCHLIST = {
    "GODREJPROP": "Godrej Properties",
    "OFSS":       "Oracle Financial Services",
    "ZYDUSLIFE":  "Zydus Life Sciences",
    "VOLTAS":     "Voltas Limited",
    "POLICYBZR":  "Policy Bazaar",
    "ASTRAL":     "Astral Limited",
    "AMBER":      "Amber Enterprises",
}
# ──────────────────────────────────────────────────────────────────────────────


def fetch_quote(symbol: str) -> dict | None:
    """
    Fetch live quote data for a single NSE symbol via yfinance.
    Returns a flat dict of fields we care about, or None on failure.
    """
    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        info   = ticker.fast_info          # lightweight — fewer network calls

        ltp        = info.last_price
        open_p     = info.open
        day_high   = info.day_high
        day_low    = info.day_low
        week52_h   = info.year_high          # FastInfo uses year_high, not fifty_two_week_high
        week52_l   = info.year_low           # FastInfo uses year_low, not fifty_two_week_low
        prev_close = info.previous_close

        # % Change vs previous close (same as NSE's "% Change")
        pchange = ((ltp - prev_close) / prev_close * 100) if prev_close else None

        # VWAP — computed from today's 1-minute bars
        vwap = None
        try:
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                tp   = (hist["High"] + hist["Low"] + hist["Close"]) / 3
                vwap = (tp * hist["Volume"]).cumsum().iloc[-1] / hist["Volume"].cumsum().iloc[-1]
        except Exception:
            pass

        # ── Open-based % changes ───────────────────────────────────────────
        def pct_from_open(val):
            try:
                if open_p and open_p != 0 and val is not None:
                    return ((val - open_p) / open_p) * 100
            except (TypeError, ValueError):
                pass
            return None

        return {
            "Symbol":     symbol,
            "Company":    WATCHLIST[symbol],
            "LTP":        ltp,
            "% Change":   pchange,
            "Open":       open_p,
            "Open→LTP %": pct_from_open(ltp),
            "High→LTP %": ((ltp - day_high) / day_high * 100) if day_high and ltp else None,
            "Low→LTP %":  ((ltp - day_low)  / day_low  * 100) if day_low  and ltp else None,
            "VWAP":       vwap,
            "High":       day_high,
            "Low":        day_low,
            "52W High":   week52_h,
            "52W Low":    week52_l,
        }

    except Exception as exc:
        st.warning(f"⚠️ Could not fetch {symbol}: {exc}")
        return None


# ── Styling helpers ────────────────────────────────────────────────────────────

def color_pchange(val):
    if pd.isna(val):
        return ""
    color = "#1a7a1a" if val > 0 else "#c0392b" if val < 0 else "#555"
    return f"color: {color}; font-weight: bold"


def color_open_move(val):
    if pd.isna(val):
        return ""
    if val > 0:
        return "color: #1a7a1a; font-weight: bold"
    elif val < 0:
        return "color: #c0392b; font-weight: bold"
    return ""


def color_vs_52w_high(val):
    if pd.isna(val):
        return ""
    if val >= -5:
        return "background-color: #d4edda; color: #155724; font-weight: bold"
    elif val >= -15:
        return "background-color: #fff3cd; color: #856404; font-weight: bold"
    else:
        return "background-color: #f8d7da; color: #721c24; font-weight: bold"


def color_vs_52w_low(val):
    if pd.isna(val):
        return ""
    if val >= 30:
        return "background-color: #d4edda; color: #155724; font-weight: bold"
    elif val >= 10:
        return "background-color: #fff3cd; color: #856404; font-weight: bold"
    else:
        return "background-color: #f8d7da; color: #721c24; font-weight: bold"


def dist_from_52w(row, col_ltp, col_ref):
    ltp = row[col_ltp]
    ref = row[col_ref]
    if pd.isna(ltp) or pd.isna(ref) or ref == 0:
        return None
    return ((ltp - ref) / ref) * 100


# ── Main fragment (auto-refreshes every 30 s) ──────────────────────────────────

@st.fragment(run_every=30)
def watchlist_fragment():
    ist          = pytz.timezone("Asia/Kolkata")
    current_time = datetime.now(ist).strftime("%H:%M:%S")
    st.caption(f"🔄 Last refreshed: **{current_time} IST**  *(~15 min delayed via Yahoo Finance)*")

    with st.spinner("Fetching quotes…"):
        rows = []
        for symbol in WATCHLIST:
            quote = fetch_quote(symbol)
            if quote:
                rows.append(quote)
            time.sleep(0.2)   # small courtesy delay

    if not rows:
        st.error("❌ Could not fetch any data. Check your internet connection or try again later.")
        return

    df = pd.DataFrame(rows)

    # ── Numeric coercion ──────────────────────────────────────────────────────
    numeric_cols = [
        "LTP", "% Change", "Open", "Open→LTP %", "High→LTP %", "Low→LTP %",
        "VWAP", "High", "Low", "52W High", "52W Low",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Derived 52W distance columns ──────────────────────────────────────────
    df["vs 52W High %"] = df.apply(lambda r: dist_from_52w(r, "LTP", "52W High"), axis=1)
    df["vs 52W Low %"]  = df.apply(lambda r: dist_from_52w(r, "LTP", "52W Low"),  axis=1)

    # ── Sort by % Change descending ───────────────────────────────────────────
    df = df.sort_values("% Change", ascending=False).reset_index(drop=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1 – Compact snapshot cards
    # ═══════════════════════════════════════════════════════════════════════════
    st.subheader("📌 Live Snapshot")
    card_cols = st.columns(len(df))
    for i, row in df.iterrows():
        pchg  = row["% Change"]
        arrow = "▲" if pchg > 0 else "▼" if pchg < 0 else "■"
        bg    = "#d4edda" if pchg > 0 else "#f8d7da" if pchg < 0 else "#e9ecef"
        txt   = "#155724" if pchg > 0 else "#721c24" if pchg < 0 else "#495057"

        with card_cols[i]:
            st.markdown(
                f"""
                <div style="background:{bg};border-radius:10px;padding:14px 10px;text-align:center;">
                  <div style="font-size:13px;font-weight:700;color:#333;">{row['Symbol']}</div>
                  <div style="font-size:11px;color:#666;margin-bottom:6px;">{row['Company']}</div>
                  <div style="font-size:20px;font-weight:800;color:{txt};">₹{row['LTP']:,.2f}</div>
                  <div style="font-size:15px;font-weight:700;color:{txt};">{arrow} {pchg:+.2f}%</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2 – Full detail table
    # ═══════════════════════════════════════════════════════════════════════════
    st.subheader("📋 Detailed Table  *(sorted by % Change)*")

    display_cols = [
        "Symbol", "Company",
        "LTP", "% Change", "Open", "VWAP",
        "Open→LTP %", "High→LTP %", "Low→LTP %",
        "High", "Low",
        "52W High", "52W Low", "vs 52W High %", "vs 52W Low %",
    ]

    fmt = {
        "LTP":           "₹{:.2f}",
        "% Change":      "{:+.2f}%",
        "Open":          "₹{:.2f}",
        "VWAP":          "₹{:.2f}",
        "High":          "₹{:.2f}",
        "Low":           "₹{:.2f}",
        "Open→LTP %":    "{:+.2f}%",
        "High→LTP %":    "{:+.2f}%",
        "Low→LTP %":     "{:+.2f}%",
        "52W High":      "₹{:.2f}",
        "52W Low":       "₹{:.2f}",
        "vs 52W High %": "{:+.2f}%",
        "vs 52W Low %":  "{:+.2f}%",
    }

    styled = (
        df[display_cols]
        .style
        .format(fmt, na_rep="—")
        .applymap(color_pchange,     subset=["% Change"])
        .applymap(color_open_move,   subset=["Open→LTP %", "High→LTP %", "Low→LTP %"])
        .applymap(color_vs_52w_high, subset=["vs 52W High %"])
        .applymap(color_vs_52w_low,  subset=["vs 52W Low %"])
        .set_properties(**{"text-align": "center"})
    )

    st.dataframe(styled, use_container_width=True, hide_index=True, height=280)

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3 – Intraday range meter
    # ═══════════════════════════════════════════════════════════════════════════
    st.subheader("📏 Intraday Range Position")
    range_cols = st.columns(len(df))
    for i, row in df.iterrows():
        low, high, ltp = row["Low"], row["High"], row["LTP"]
        if pd.isna(low) or pd.isna(high) or high == low:
            with range_cols[i]:
                st.caption(f"{row['Symbol']}: range N/A")
            continue

        pct_pos = int(((ltp - low) / (high - low)) * 100)

        with range_cols[i]:
            st.markdown(f"**{row['Symbol']}** — {pct_pos}% of range")
            st.progress(pct_pos / 100)
            st.caption(f"L ₹{low:.1f}  |  ₹{ltp:.1f}  |  H ₹{high:.1f}")


# ── Entry point ────────────────────────────────────────────────────────────────
watchlist_fragment()
