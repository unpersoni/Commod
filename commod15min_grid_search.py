"""
Grid search over ENTRY_START (window-open offset), REVERSAL_START
(stop-arm offset), and ENTRY_THRESHOLD (favorite-price trigger) against
the recorded tick log, replaying the actual observed price paths for
each historical 15-min window.

Run this in Colab (where commod15min_ticks.csv is local via Drive mount) --
it's too large to pull through the Drive API from outside. Writes two
result CSVs back to Drive when done. ~1256 windows x 85 x 85 x 21 combos
-- expect roughly 15-20 min to run.

Parameters swept (fixed: STOP_OFFSET_C=10, STOP_DEADBAND_SEC=2.0 --
unchanged, per current strategy):
  - entry_start:      0 min -> 14 min, step 10s  (minutes elapsed since window
                       open; 0 = watch from open, higher = narrower/later entry)
  - reversal_start:   14 min -> 0 min, step 10s  (minutes elapsed since window
                       open at which the stop-loss check arms; higher = later)
  - entry_threshold:  50% -> 90%, step 2%  (favorite price that triggers entry;
                       band is [threshold, threshold+5c], same 5c width as the
                       current 55-60c design, just sliding the base -- capped
                       at 90 to match the old ENTRY_CAP_C ceiling from V19-V21)

For each (entry_start, reversal_start, entry_threshold) combo and each
historical window+ticker, replays: first band-touch at or after entry_start
= entry; first stop-breach (own bid < entry-10c) at or after reversal_start
= stop+reverse; otherwise the leg rides to Kalshi's settlement estimate (avg
yes_mid over the final 60s of ticks, approximating the real final-minute-
average mechanism).
"""
import pandas as pd
import numpy as np

TICK_CSV = "/content/drive/MyDrive/commod15min_ticks.csv"
OUT_DETAIL = "/content/drive/MyDrive/grid_search_detail.csv"      # per (entry_start, reversal_start, entry_threshold) x asset
OUT_OVERALL = "/content/drive/MyDrive/grid_search_overall.csv"    # per (entry_start, reversal_start, entry_threshold), all assets combined

BAND_WIDTH_C = 5.0                 # entry band = [threshold, threshold + BAND_WIDTH_C], matches 55-60
STOP_OFFSET_C = 10.0
STOP_DEADBAND_MIN = 2.0 / 60.0     # 2s, matches STOP_DEADBAND_SEC
SETTLE_WINDOW_SEC = 60.0           # Kalshi settles crypto on avg of final 60s
LOTS = 10

STEP_MIN = 10.0 / 60.0             # 10 seconds, in minutes
entry_grid = np.arange(0.0, 14.0 + 1e-9, STEP_MIN)
reversal_grid = np.arange(0.0, 14.0 + 1e-9, STEP_MIN)      # evaluated 14 -> 0 in the loop order
price_grid = np.arange(50.0, 90.0 + 1e-9, 2.0)              # 50% -> 90%, step 2%

def fee_est(px):
    px = np.clip(px, 0, 100)
    return np.ceil(7 * (px / 100) * (1 - px / 100))

def simulate_window(minute, yb, ya, ymid, entry_c, entry_cap_c):
    """minute, yb, ya, ymid: 1-D numpy arrays, time-sorted, for one window+ticker.
    Returns a dict (entry_start, reversal_start) -> net_c for this one
    entry_threshold (entry_c/entry_cap_c passed in by the caller)."""
    n = len(minute)
    if n == 0:
        return {}

    sec_to_close = (15.0 - minute) * 60.0
    settle_mask = sec_to_close <= SETTLE_WINDOW_SEC
    settle_yes = ymid[settle_mask].mean() if settle_mask.any() else ymid[-1]

    yes_band = (ymid >= entry_c) & (ymid <= entry_cap_c)
    no_band = (ymid <= (100 - entry_c)) & (ymid >= (100 - entry_cap_c))
    band_hit = yes_band | no_band
    if not band_hit.any():
        return {}
    band_idx = np.where(band_hit)[0]
    band_minutes = minute[band_idx]
    band_is_yes = yes_band[band_idx]

    out = {}
    for es in entry_grid:
        pos = np.searchsorted(band_minutes, es, side="left")
        if pos >= len(band_idx):
            continue
        entry_i = band_idx[pos]
        entry_min = minute[entry_i]
        entry_is_yes = band_is_yes[pos]
        entry_px = ymid[entry_i] if entry_is_yes else (100.0 - ymid[entry_i])

        own_bid = yb if entry_is_yes else (100.0 - ya)
        stop_thresh = entry_px - STOP_OFFSET_C

        idxs = np.arange(n)
        valid_zone = (idxs >= entry_i) & (minute <= 15.0 - STOP_DEADBAND_MIN)
        breach = (own_bid < stop_thresh) & valid_zone
        breach_idx = np.where(breach)[0]
        breach_minutes = minute[breach_idx] if len(breach_idx) else np.array([])

        entry_fee = fee_est(entry_px) * LOTS

        for rs in reversal_grid:
            rs_eff = max(rs, entry_min)
            if len(breach_idx):
                bpos = np.searchsorted(breach_minutes, rs_eff, side="left")
            else:
                bpos = len(breach_idx)

            if bpos < len(breach_idx):
                stop_i = breach_idx[bpos]
                stop_px = own_bid[stop_i]
                exit_fee = fee_est(stop_px) * LOTS
                leg1_net = (stop_px - entry_px) * LOTS - entry_fee - exit_fee

                reverse_entry_px = 100.0 - stop_px
                reverse_is_yes = not entry_is_yes
                final_reversal_px = settle_yes if reverse_is_yes else (100.0 - settle_yes)
                reverse_entry_fee = fee_est(reverse_entry_px) * LOTS
                leg2_net = (final_reversal_px - reverse_entry_px) * LOTS - reverse_entry_fee

                net = leg1_net + leg2_net
            else:
                final_px = settle_yes if entry_is_yes else (100.0 - settle_yes)
                net = (final_px - entry_px) * LOTS - entry_fee

            out[(round(es, 4), round(rs, 4))] = net
    return out


def run(tick_csv=TICK_CSV, out_detail=OUT_DETAIL, out_overall=OUT_OVERALL):
    df = pd.read_csv(tick_csv, usecols=[
        "ticker", "asset", "yes_bid", "yes_ask", "yes_mid", "sec_to_close"
    ])
    df = df.dropna(subset=["yes_bid", "yes_ask", "yes_mid", "sec_to_close"])
    df["minute_in_cycle"] = 15.0 - df["sec_to_close"] / 60.0
    df = df[(df["minute_in_cycle"] >= 0) & (df["minute_in_cycle"] <= 15)]

    # load every window's arrays into memory once, so the price-threshold
    # sweep doesn't have to re-group the dataframe on every pass
    windows = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.sort_values("minute_in_cycle")
        windows.append((
            g["asset"].iloc[0],
            g["minute_in_cycle"].to_numpy(),
            g["yes_bid"].to_numpy(dtype=float),
            g["yes_ask"].to_numpy(dtype=float),
            g["yes_mid"].to_numpy(dtype=float),
        ))
    print(f"loaded {len(windows)} windows, sweeping {len(price_grid)} price thresholds...")

    # agg[(entry_start, reversal_start, entry_threshold, asset)] = [n, wins, net_sum]
    agg = {}

    for pi, thresh in enumerate(price_grid):
        entry_c = float(thresh)
        entry_cap_c = min(entry_c + BAND_WIDTH_C, 99.0)
        for asset, minute, yb, ya, ymid in windows:
            res = simulate_window(minute, yb, ya, ymid, entry_c, entry_cap_c)
            for (es, rs), net in res.items():
                key = (es, rs, entry_c, asset)
                if key not in agg:
                    agg[key] = [0, 0, 0.0]
                agg[key][0] += 1
                if net > 0:
                    agg[key][1] += 1
                agg[key][2] += net
        print(f"  threshold {entry_c:.0f}% done ({pi+1}/{len(price_grid)})")

    rows = []
    for (es, rs, thresh, asset), (n, wins, net_sum) in agg.items():
        rows.append({
            "entry_start_min": es, "reversal_start_min": rs,
            "entry_threshold_c": thresh, "asset": asset,
            "n_trades": n, "wins": wins, "win_rate": round(wins / n, 4) if n else None,
            "total_net_c": round(net_sum, 1),
            "avg_net_c": round(net_sum / n, 2) if n else None,
        })
    detail = pd.DataFrame(rows)
    detail.to_csv(out_detail, index=False)
    print(f"wrote {out_detail} ({len(detail)} rows)")

    overall = (detail.groupby(["entry_start_min", "reversal_start_min", "entry_threshold_c"])
               .agg(n_trades=("n_trades", "sum"),
                    wins=("wins", "sum"),
                    total_net_c=("total_net_c", "sum"))
               .reset_index())
    overall["win_rate"] = (overall["wins"] / overall["n_trades"]).round(4)
    overall["avg_net_c"] = (overall["total_net_c"] / overall["n_trades"]).round(2)
    overall = overall.sort_values("total_net_c", ascending=False)
    overall.to_csv(out_overall, index=False)
    print(f"wrote {out_overall} ({len(overall)} rows)")
    print("\ntop 10 combos by total_net_c:")
    print(overall.head(10).to_string(index=False))

    # compact summaries -- the full detail/overall files can run tens of MB,
    # too big to pull back through the Drive API, so also write small
    # top-N files that are easy to hand off for review.
    out_top_overall = out_overall.replace(".csv", "_top200.csv")
    overall.head(200).to_csv(out_top_overall, index=False)
    print(f"wrote {out_top_overall} (200 rows)")

    out_top_by_asset = out_detail.replace(".csv", "_top20_per_asset.csv")
    top_by_asset = (detail.sort_values("total_net_c", ascending=False)
                     .groupby("asset", group_keys=False)
                     .head(20)
                     .sort_values(["asset", "total_net_c"], ascending=[True, False]))
    top_by_asset.to_csv(out_top_by_asset, index=False)
    print(f"wrote {out_top_by_asset} ({len(top_by_asset)} rows)")

if __name__ == "__main__":
    run()
