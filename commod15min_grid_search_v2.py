"""
V25 Grid Search — sweep levers to maximize reversal win rate and total P&L.

Levers swept:
  1. entry_window_min: how many minutes before close to start looking
     (1.0 → 5.0, step 0.5 — replaces TRIGGER_MIN)
  2. entry_c: minimum ask price to qualify as favorite
     (70 → 90, step 1)
  3. stop_c: fixed stop/reversal level (favorite bid <= this → reverse)
     (55 → entry_c-5, step 1)
  4. reversal_enabled: per-market toggle — can also test a global
     "max reversals per window" cascade limiter

Fixed (per V25):
  - CONTRACTS = 10, 2x reversal (20 contracts opposite side, closes 10 + opens 10)
  - STOP_DEADBAND = 2s before close
  - Settlement = avg of final 60s of yes_mid
  - Entry grace = 2c above entry_c still triggers

Outputs:
  - grid_v2_overall.csv: (entry_window, entry_c, stop_c) → totals + breakdown
  - grid_v2_by_asset.csv: same but per asset
  - grid_v2_top.csv: top 100 combos ranked by total_net_c

Run in Colab where commod15min_ticks.csv is local.
"""
import pandas as pd
import numpy as np
from itertools import product
import time

TICK_CSV = "/content/drive/MyDrive/commod15min_ticks.csv"
OUT_OVERALL = "/content/drive/MyDrive/grid_v2_overall.csv"
OUT_BY_ASSET = "/content/drive/MyDrive/grid_v2_by_asset.csv"
OUT_TOP = "/content/drive/MyDrive/grid_v2_top.csv"

CONTRACTS = 10
REVERSAL_MULT = 2
STOP_DEADBAND_MIN = 2.0 / 60.0
SETTLE_WINDOW_SEC = 60.0
ENTRY_GRACE_C = 2

# markets where reversals historically lose money — tested as a toggle
REVERSAL_BLACKLIST = {"XRP", "DOGE", "ETH"}

# max reversals per 15-min window across all markets (0 = unlimited)
MAX_REVERSALS_PER_WINDOW = 0


def fee_c(px):
    """Kalshi fee in cents per contract."""
    px = np.clip(px, 0, 100)
    return np.ceil(7.0 * (px / 100.0) * (1.0 - px / 100.0))


def simulate_one(minute, yb, ya, ymid, entry_c, entry_cap_c, stop_c,
                  entry_start_min, allow_reversal=True):
    """Simulate one window+ticker under given parameters.

    Returns dict with keys:
      outcome: 'no_trade' | 'fav_win' | 'fav_loss' | 'rev_win' | 'rev_loss'
      entry_px, stop_px, rev_px, settle_px, net_c, entry_min, stop_min
    """
    n = len(minute)
    if n == 0:
        return None

    window_len = 15.0
    arm_start = window_len - entry_start_min

    sec_to_close = (window_len - minute) * 60.0
    settle_mask = sec_to_close <= SETTLE_WINDOW_SEC
    settle_yes = ymid[settle_mask].mean() if settle_mask.any() else ymid[-1]

    yes_ask = ya
    no_ask = 100.0 - yb
    yes_bid = yb
    no_bid = 100.0 - ya

    entry_i = None
    entry_is_yes = None

    for i in range(n):
        if minute[i] < arm_start:
            continue
        if sec_to_close[i] <= STOP_DEADBAND_MIN * 60:
            break
        if yes_ask[i] >= entry_c and yes_ask[i] <= entry_cap_c:
            entry_i = i
            entry_is_yes = True
            break
        if no_ask[i] >= entry_c and no_ask[i] <= entry_cap_c:
            entry_i = i
            entry_is_yes = False
            break

    if entry_i is None:
        return None

    entry_px = ya[entry_i] if entry_is_yes else (100.0 - yb[entry_i])
    entry_min_val = minute[entry_i]

    own_bid_arr = yes_bid if entry_is_yes else no_bid

    stop_i = None
    if allow_reversal:
        for i in range(entry_i + 1, n):
            if sec_to_close[i] <= STOP_DEADBAND_MIN * 60:
                break
            if own_bid_arr[i] <= stop_c:
                stop_i = i
                break

    entry_fee = fee_c(entry_px) * CONTRACTS

    if stop_i is not None:
        stop_px = own_bid_arr[stop_i]
        stop_min_val = minute[stop_i]
        exit_fee = fee_c(stop_px) * CONTRACTS
        leg1_net = (stop_px - entry_px) * CONTRACTS - entry_fee - exit_fee

        rev_entry_px = 100.0 - stop_px
        rev_is_yes = not entry_is_yes
        rev_settle = settle_yes if rev_is_yes else (100.0 - settle_yes)
        rev_entry_fee = fee_c(rev_entry_px) * CONTRACTS
        rev_exit_fee = fee_c(rev_settle) * CONTRACTS if rev_settle > 0 else 0
        leg2_net = (rev_settle - rev_entry_px) * CONTRACTS - rev_entry_fee - rev_exit_fee

        net = leg1_net + leg2_net

        if rev_settle >= 50:
            outcome = "rev_win"
        else:
            outcome = "rev_loss"

        return {
            "outcome": outcome,
            "entry_px": entry_px, "stop_px": stop_px,
            "rev_px": rev_entry_px, "settle_yes": settle_yes,
            "net_c": net, "entry_min": entry_min_val,
            "stop_min": stop_min_val,
        }
    else:
        final_px = settle_yes if entry_is_yes else (100.0 - settle_yes)
        exit_fee = fee_c(final_px) * CONTRACTS if final_px > 0 else 0
        net = (final_px - entry_px) * CONTRACTS - entry_fee - exit_fee

        outcome = "fav_win" if final_px >= 50 else "fav_loss"
        return {
            "outcome": outcome,
            "entry_px": entry_px, "settle_yes": settle_yes,
            "net_c": net, "entry_min": entry_min_val,
            "stop_px": None, "rev_px": None, "stop_min": None,
        }


def run(tick_csv=TICK_CSV, use_blacklist=False, max_rev_per_window=0):
    t0 = time.time()

    df = pd.read_csv(tick_csv, usecols=[
        "ticker", "asset", "yes_bid", "yes_ask", "yes_mid", "sec_to_close"
    ])
    df = df.dropna(subset=["yes_bid", "yes_ask", "yes_mid", "sec_to_close"])
    df["minute"] = 15.0 - df["sec_to_close"] / 60.0
    df = df[(df["minute"] >= 0) & (df["minute"] <= 15)]

    windows = {}
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.sort_values("minute")
        asset = g["asset"].iloc[0]
        windows[ticker] = (
            asset,
            g["minute"].to_numpy(),
            g["yes_bid"].to_numpy(dtype=float),
            g["yes_ask"].to_numpy(dtype=float),
            g["yes_mid"].to_numpy(dtype=float),
            (15.0 - g["minute"].to_numpy()) * 60.0,
        )
    print(f"loaded {len(windows)} windows in {time.time()-t0:.1f}s")

    entry_window_grid = np.arange(1.0, 5.5, 0.5)
    entry_c_grid = np.arange(70, 91, 1)
    stop_offsets = np.arange(5, 21, 1)

    total_combos = len(entry_window_grid) * len(entry_c_grid)
    print(f"sweeping {len(entry_window_grid)} windows x {len(entry_c_grid)} "
          f"entries x variable stops = ~{total_combos} major combos across "
          f"{len(windows)} windows")

    results = []
    combo_count = 0

    for ew in entry_window_grid:
        for ec in entry_c_grid:
            ec = float(ec)
            entry_cap = ec + ENTRY_GRACE_C

            for so in stop_offsets:
                sc = ec - float(so)
                if sc < 30 or sc > ec - 3:
                    continue

                combo_count += 1
                asset_agg = {}

                tickers_by_window_label = {}
                for ticker, (asset, minute, yb, ya, ymid, stc) in windows.items():
                    label = ticker.rsplit("-", 1)[0] if "-" in ticker else ticker
                    if label not in tickers_by_window_label:
                        tickers_by_window_label[label] = []
                    tickers_by_window_label[label].append(
                        (ticker, asset, minute, yb, ya, ymid, stc))

                for wlabel, window_tickers in tickers_by_window_label.items():
                    rev_count_this_window = 0

                    for ticker, asset, minute, yb, ya, ymid, stc in window_tickers:
                        allow_rev = True
                        if use_blacklist and asset in REVERSAL_BLACKLIST:
                            allow_rev = False
                        if max_rev_per_window > 0 and rev_count_this_window >= max_rev_per_window:
                            allow_rev = False

                        r = simulate_one(minute, yb, ya, ymid, ec,
                                         entry_cap, sc, ew, allow_rev)
                        if r is None:
                            continue

                        if r["outcome"] in ("rev_win", "rev_loss"):
                            rev_count_this_window += 1

                        if asset not in asset_agg:
                            asset_agg[asset] = {
                                "fav_win": 0, "fav_loss": 0,
                                "rev_win": 0, "rev_loss": 0,
                                "net_c": 0.0, "n": 0,
                            }
                        a = asset_agg[asset]
                        a[r["outcome"]] = a.get(r["outcome"], 0) + 1
                        a["net_c"] += r["net_c"]
                        a["n"] += 1

                for asset, a in asset_agg.items():
                    total_rev = a["rev_win"] + a["rev_loss"]
                    results.append({
                        "entry_window_min": ew,
                        "entry_c": ec,
                        "stop_c": sc,
                        "stop_offset": so,
                        "asset": asset,
                        "n_trades": a["n"],
                        "fav_win": a["fav_win"],
                        "fav_loss": a["fav_loss"],
                        "rev_win": a["rev_win"],
                        "rev_loss": a["rev_loss"],
                        "rev_win_rate": round(a["rev_win"] / total_rev, 4) if total_rev else None,
                        "net_c": round(a["net_c"], 1),
                        "avg_net_c": round(a["net_c"] / a["n"], 2) if a["n"] else None,
                    })

            if combo_count % 100 == 0:
                print(f"  {combo_count} combos done ({time.time()-t0:.0f}s)")

    detail = pd.DataFrame(results)
    detail.to_csv(OUT_BY_ASSET, index=False)
    print(f"\nwrote {OUT_BY_ASSET} ({len(detail)} rows)")

    overall = (detail.groupby(["entry_window_min", "entry_c", "stop_c", "stop_offset"])
               .agg(
                   n_trades=("n_trades", "sum"),
                   fav_win=("fav_win", "sum"),
                   fav_loss=("fav_loss", "sum"),
                   rev_win=("rev_win", "sum"),
                   rev_loss=("rev_loss", "sum"),
                   net_c=("net_c", "sum"),
               ).reset_index())
    overall["total_rev"] = overall["rev_win"] + overall["rev_loss"]
    overall["rev_win_rate"] = (overall["rev_win"] / overall["total_rev"]).round(4)
    overall["win_rate"] = ((overall["fav_win"] + overall["rev_win"]) / overall["n_trades"]).round(4)
    overall["avg_net_c"] = (overall["net_c"] / overall["n_trades"]).round(2)
    overall = overall.sort_values("net_c", ascending=False)
    overall.to_csv(OUT_OVERALL, index=False)
    print(f"wrote {OUT_OVERALL} ({len(overall)} rows)")

    top = overall.head(100)
    top.to_csv(OUT_TOP, index=False)
    print(f"wrote {OUT_TOP} (100 rows)")

    print(f"\n{'='*80}")
    print("TOP 20 COMBOS BY TOTAL NET P&L:")
    print(f"{'='*80}")
    cols = ["entry_window_min", "entry_c", "stop_c", "stop_offset",
            "n_trades", "fav_win", "rev_win", "rev_loss",
            "rev_win_rate", "net_c", "avg_net_c"]
    print(top[cols].head(20).to_string(index=False))

    print(f"\n{'='*80}")
    print("TOP 20 COMBOS BY REVERSAL WIN RATE (min 20 reversals):")
    print(f"{'='*80}")
    rev_filtered = overall[overall["total_rev"] >= 20].sort_values(
        "rev_win_rate", ascending=False)
    print(rev_filtered[cols].head(20).to_string(index=False))

    print(f"\n{'='*80}")
    print("TOP 20 COMBOS BY AVG NET PER TRADE (min 50 trades):")
    print(f"{'='*80}")
    avg_filtered = overall[overall["n_trades"] >= 50].sort_values(
        "avg_net_c", ascending=False)
    print(avg_filtered[cols].head(20).to_string(index=False))

    print(f"\n\nfinished in {time.time()-t0:.0f}s, {combo_count} combos x {len(windows)} windows")


if __name__ == "__main__":
    run()
