# ============================================================
# Commod15min V33 — CONTRARIAN strategy, PAPER mode (LIVE = False).
#   Built on V31 mechanics with inverted entry logic:
#     - When the favorite's ask reaches 51-55c, buy the OPPOSITE side
#       (~45-49c) instead. Tag which side was the favorite.
#     - Reversal: when the tagged favorite's bid dips to 23-27c (meaning
#       the held opposite is ~73-77c), buy 2x contracts of the FAVORITE
#       at ~23-27c. Closes the opposite position + opens the favorite.
#     - Below 23c: don't reverse (REV_SKIP_BELOW_C).
#     - Window: last 7 minutes. Full-window reversal armed.
#   Logs: commod15min_v33_trades.csv, _ticks.csv, _settlements.csv
#
# ============================================================
# Commod15min V29 — V25 (Sep 27) mechanics unchanged; parameters only:
#   last 7 min, favorite's ask 88-92c, reverse at 70c ONLY in the last 90s
#   (a dip to 70c earlier than that is ignored — the favorite is held).
# (V25 header:) back to the 80/70 reversal strategy (parameter tuning
# comes later). All V23/V24 speed fixes kept; order price limits still OFF.
#   - Armed for the last 3 minutes of each market (TRIGGER_MIN = 3).
#   - Favorite = first side to reach 80c (ENTRY_C; 81-82c also buys via
#     ENTRY_CAP_GRACE_C). Buy CONTRACTS (10).
#   - Fixed stop: Favorite's bid <= 70c (STOP_C) -> one combined order
#     buys 2x (20) of the opposite side: closes the 10 held + opens 10 new.
#     Stop is live the whole time the Favorite is held (STOP_ACTIVATE_SEC
#     = the full 3-min window), not just the last 90s as in V19-V24.
#   - Reversal held to settlement. No second stop/reversal.
#   - Settlement rows now label the 3 outcomes: settle_win (Favorite won),
#     rev_settle_win (reversal won), rev_settle_loss (reversed, but the
#     Favorite won). settle_loss = Favorite lost without the stop firing.
#
# Commod15min V24 — two switches on top of V23:
#   - USE_PRICE_LIMITS (default False): turns V23's order price limits
#     off, so orders go out at 99c/1c exactly like V22 while every other
#     V23 speed fix stays on (event-driven entries, no balance round trips,
#     no wasted arm cycle, ask-based band, per-trade slippage/ms logging).
#     That isolates how much of the 87-91c problem was reaction time alone.
#     Flip to True to test the limits on top.
#   - ENTRY_CAP_GRACE_C (default 2): an ask 1-2c over ENTRY_CAP_C still
#     triggers the buy instead of being skipped, and (with limits on) the
#     entry limit is no longer clamped at ENTRY_CAP_C — a missed trade over
#     one cent is worse than paying that cent.
#   An entry that doesn't fill (FOK killed) now goes back to armed and
#   retries on the next tick (V22 gave up on the market for the window).
#
# Commod15min V23 — ORDER PRICE ACCURACY / LATENCY. Fills were landing
# 7-11c past the target (e.g. 87-91c on an 80c trigger). Causes, and
# what changed for each:
#   1. NO PRICE LIMIT ON ORDERS (biggest cause). place_order() sent every
#      buy at a 99c limit and every sell at 1c — a FOK market order in
#      disguise. Whenever the best price didn't have all 10 contracts,
#      the order walked up the book and filled at whatever the deeper
#      levels were. Now every order carries a real limit: entries pay at
#      most the ask seen at trigger + MAX_ENTRY_SLIPPAGE_C (never above
#      ENTRY_CAP_C); stops/reversals accept at most MAX_STOP_SLIPPAGE_C
#      worse than the bid seen at trigger. If the book can't fill 10
#      contracts inside that, FOK kills it (no fill, no fee) and the bot
#      retries on the next tick instead of taking a bad price.
#   2. ENTRIES WERE POLL-DRIVEN. Stops already fired off WS ticks, but
#      entries only got checked once per main-loop cycle — after 11 REST
#      /markets calls, the settle checks, and a 0.5s sleep — so the
#      price had often run well past the target by the time the bot
#      looked. Entries are now event-driven off the same WS tick handler
#      as stops (handle_tick), with the order placed on a worker thread.
#   3. EXTRA REST ROUND TRIPS BEFORE/AFTER THE BUY. The entry path did a
#      live balance check (ensure_shard_funds, plus up to ~1.5s of
#      transfer retry-sleeps if short) before ordering, and a
#      get_balance() call after (its result was never used). Entries now
#      use ShardCash's local balance like stops already did.
#   4. A WASTED CYCLE ON ARM. The first cycle a market entered the watch
#      window only flipped it watch->armed and `continue`d, so a market
#      already at the target waited an extra full cycle to be bought.
#   5. ENTRY BAND WAS CHECKED ON MID, NOT THE PRICE ACTUALLY PAID. A buy
#      fills at the ask, which sits above mid by half the spread. The
#      band is now checked against the favorite's ask, so the target is
#      the price you pay.
#   6. ONE ENTRY PER CYCLE (entered_this_cycle) made a second market that
#      hit its target at the same moment wait a full cycle; removed —
#      open_assets + ShardCash still guard against double-buys/overspend.
#   PAPER mode now simulates fills at the ask/bid seen at execution time
#   (and simulates a FOK kill if that's past the limit) instead of
#   always filling at mid, so paper results reflect real fill prices.
#   Every BUY/STOP line now prints target, seen, fill, slippage, and
#   trigger->fill milliseconds so accuracy can be checked directly.
#
# Commod15min V22 — new strategy, workshopped over several rounds:
#   - TRIGGER_MIN 5.0 -> 15.0: watch the full market lifetime (window
#     open to close), not just a trailing slice — otherwise a favorite
#     that already crossed 55-60c earlier in its life, before a narrower
#     window opened, gets missed entirely instead of bought.
#   - ENTRY_C/ENTRY_CAP_C 51-90 -> 55-60: entries are now a fixed, cheap
#     ~55c buy (whichever side first reaches it), not "whoever's ahead,
#     wherever that price is." Every win now pays ~45c/contract instead
#     of the old design's often-10-20c win off a late, expensive,
#     high-conviction entry — the trade-off is a much weaker signal at
#     entry time (55c vs. often 80-90c before), so a lower win rate is
#     expected; that's exactly what this wider window + bigger data set
#     is for figuring out.
#   - STOP_ACTIVATE_SEC left at 90 (unchanged) per explicit instruction —
#     the reversal check still only arms in the final 90s before close.
#   - Twelve Data commodity spot sourcing REMOVED — see the note where
#     TWELVEDATA_API_KEY used to be defined. Free-tier credits ran out
#     and no free source covers all 6 commodities long term anyway.
#     Trading is unaffected (it never used spot price); only the
#     optional spot_px/pct_from_strike tick-log columns for those 6 lose
#     their data, and floor_strike (from Kalshi directly) is unaffected.
#   With entries now capped at 60c, STOP_FLOOR_C=70 (from V20) never
#   actually engages — every stop is a flat 10c below entry. Left in
#   place rather than removed in case entries widen again later.
#
# Commod15min V21 — two latency changes aimed at tightening stop-loss
# execution toward the intended offset: (1) PAPER mode's do_stop now runs
# synchronously in handle_tick instead of via the worker pool — it does
# no real network I/O there, so the only thing the pool hop was buying
# was queuing/scheduling delay before the "fresh" price re-read, which
# is pure added slippage with zero upside; (2) order_executor's worker
# pool widened from a flat 4 to one per market, so several markets
# stopping at the same moment (a broad move hitting correlated assets)
# never queue behind each other in LIVE mode. Some slippage beyond the
# nominal stop distance is still expected regardless — Kalshi's book
# moves in whatever increments the next real trade prints, not smoothly,
# so a fast move can gap past the stop between two consecutive ticks
# even with zero reaction delay; these changes remove the added,
# non-market-driven delay, not all of it.
#
# Commod15min V20 — floored stop: entries 80c+ get a flat 70c exit
# instead of a flat 10c-below-entry stop (a dip from 90 to 80 isnt nearly
# as strong a flip signal as the same 10c dip off a 55c entry) — one
# formula, stop_price(entry) = min(entry - STOP_OFFSET_C, STOP_FLOOR_C),
# entries under 80c are unaffected (still flat 10c). Built on V19 — three changes, all confirmed against Kalshi's own
# settlement docs (crypto 15-min markets settle on the AVERAGE of 60
# one-second readings of the underlying index during the final minute
# before close — not the instantaneous price at close; commodities use
# a different source, Pyth, not CF Benchmarks). That means everything
# before roughly the last minute is largely noise relative to what
# actually decides the outcome, which motivates all three changes:
#   1. TRIGGER_MIN 3.0 -> 5.0 — watch/entry window widened so a
#      favorite can be caught before it runs past ENTRY_CAP_C (90c),
#      which was shutting platinum/palladium out of ~88% of windows.
#   2. NEW STOP_ACTIVATE_SEC = 90.0 — the stop-loss check (handle_tick)
#      now only arms in the final 90 seconds before close, not from the
#      moment of entry. A position entered early just rides until that
#      window opens; this concentrates stop/reversal decisions on the
#      stretch of time that's actually close to what the real
#      settlement average is being computed over, instead of reacting
#      to mid-window noise that has time to fully mean-revert before
#      close (see the run's own data: a GOLD/BTC window that was
#      genuinely winning the whole time still got stopped+reversed on
#      an early dip — see item 3 below for a related, separate bug).
#   3. FAIL-SAFE HARDENING — both handle_tick's and do_stop's deadband
#      checks used to read `if ct is not None and (ct-now()) <= ...:
#      bail`, which means a ticker whose close_at somehow isn't known
#      yet (ct is None, for whatever reason — race condition, a bad
#      REST read, anything) FAILED OPEN: with ct None the whole
#      condition was False, so it did NOT bail, and a stop could fire
#      with no time-to-close information at all. Now `ct is None` bails
#      too — unknown-timing means "don't act," not "assume it's safe to
#      act." This is the best explanation found so far for the BTC/GOLD
#      case in V18's own collected data (a "stop" recorded 1.17s AFTER
#      the window's actual close on a position confirmed a winner by
#      its own reversal losing) even though the deadband's time-based
#      arithmetic alone should have blocked it — root cause not fully
#      pinned down, but this closes the exact failure mode the data
#      shows regardless of what triggered ct being unset.
#   Also: run_net's day-rollover reset is now gated by LIVE, same as
#   the halt check already was in V18 — in PAPER mode the running total
#   stays continuous across UTC midnight instead of silently dropping
#   to 0, so a printed total spanning a day boundary still adds up.
#   (DAILY_LOSS_LIMIT_C/MAX_TRADES_DAY themselves were already LIVE-only
#   as of V18.)
#
# Built on top of V17 — 11 markets total: adds XRP/DOGE to the crypto
# side (BTC/ETH/SOL/XRP/DOGE) alongside all 6 commodities (gold/
# silver/WTI/copper/platinum/palladium — see section 4 below), and
# adds ENTRY_CAP_C (90c): the entry rule is now a BAND, not just a
# floor — buy the first side to become the favorite, but only between
# ENTRY_C (51c) and ENTRY_CAP_C (90c). A favorite already at 91c+ the
# moment the window opens just gets watched, not bought — no point
# risking a 10c stop to protect a position that's already a near-lock
# with almost no upside left. If it later falls back to 90c or below
# before close, it gets bought then, same as any other entry; if it
# never comes back down, no trade happens on that market that cycle.
# Also reverted the V15 detour into Pyth Hermes back to Twelve Data
# for commodity spot prices: Pyth's real API access turned out to
# require a $500+/month "Starter" plan — what looked like a free key
# was a 14-day trial of that paid plan, not a permanent free tier.
# Twelve Data's real free tier (already in use, already has a working
# key) is the actual free option; not every symbol on it is confirmed
# available yet (silver already known not to be — see COMMOD_SYMBOL_MAP)
# but the per-symbol error handling reports exactly which ones aren't,
# live, instead of failing silently. Built on top of V14, a
# dry-run experiment: enter much earlier (whoever's
# ahead the instant a real favorite exists, not just once it crosses
# 80c) with a stop measured relative to entry instead of a fixed floor,
# to see whether earlier entries are actually better or just add more
# whipsaw. Built on top of V13, which reverted V12's "hold-the-favorite"
# entry split back to ONE unified trading rule, per the account owner's
# exact spec after V12's split caused a real misunderstanding (and real
# losses): the 92% clean-hold stat only ever applied to markets already
# priced >=80c the instant their window opened, but V12 used it to skip
# the stop for those entries specifically — not what was actually asked
# for.
#
# 1. UNIFIED TRADING LOGIC (this is the whole strategy, nothing else):
#    - Watch the last TRIGGER_MIN minutes of each window.
#    - Buy the FIRST side to become the favorite, within the band
#      [ENTRY_C, ENTRY_CAP_C] = [51c, 90c] — 51 means "buy the instant
#      either side is ahead at all, even by a single cent," 90 means
#      "but never above this." A dead-even 50/50 open isn't a favorite
#      yet, so the bot just keeps watching until one side actually
#      breaks out; a favorite already above the cap ALSO just keeps
#      getting watched, whether that's true from window open or it
#      ran up past 90c later, until/unless it falls back into the
#      band — same watch-and-wait treatment either direction. Buys
#      THAT side — whether it was already in-band the moment the
#      window opened, broke into the band from below, or fell back
#      into it from above, same rule every way — CONTRACTS (10), FOK.
#    - If that position dips STOP_OFFSET_C (10c) below what it was
#      bought at (not a fixed floor — e.g. bought at 55c stops at 45c,
#      bought at 92c stops at 82c): stop out — sell everything held and
#      buy 2x the held contracts on the OPPOSITE side in one combined
#      order (falls back to sell-then-buy if the combined order can't
#      fill). Net result: 1x the opposite side, priced wherever
#      100 - (entry - STOP_OFFSET_C) lands — closer to even money for
#      low-entry positions than for high-entry ones, since the stop
#      distance is now the same 10c everywhere instead of scaling with
#      how confident the entry was.
#    - That reversed position is held to settlement. No second stop,
#      no second reversal, ever.
#    That's it. The old GATE_MAX/HOLD_MAX split and the no-stop "hold"
#    phase from V12 are removed — every entry gets the same stop+
#    reverse treatment now.
#
# 2. LOG-SPAM FIX (kept from V12): ShardCash.maybe_topup's periodic
#    balance check is silent (quiet=True) on its ~10s hot-path call;
#    startup, the test cell, and entry-time funds checks still print.
#
# 3. SPOT PRICE + STRIKE TRACKING (kept from V12, data collection
#    only, no effect on trading): every tick log row also records the
#    underlying asset's live price, the window's floor_strike (Kalshi's
#    settlement threshold — the price that decides UP/DOWN), and the %
#    distance between them. Crypto (BTC/ETH/SOL) via a public, no-auth
#    Coinbase feed (instant, free, no signup).
#
# 4. ALL 11 MARKETS ACTIVE, ALL PAPER MODE: BTC/ETH/SOL/XRP/DOGE plus
#    gold/silver/WTI/copper/platinum/palladium are all in SERIES now,
#    so they all go through the exact same watch/buy/stop/reverse/
#    settle simulation — no real orders either way while LIVE=False.
#    XRP and DOGE's spot prices ride the existing crypto path (nothing
#    new needed there beyond adding their tickers). The 6 commodities'
#    spot price tracking is on Twelve Data with the free key already in
#    hand (TWELVEDATA_API_KEY below) — silver is confirmed NOT
#    available on the free plan (blank column, already seen live);
#    platinum/copper/palladium are unconfirmed but the feed will
#    report each one's real status the first time it polls, instead of
#    failing silently. 6 symbols, so COMMOD_POLL_SEC is slower (5 min)
#    to stay inside the free plan's 800-req/day cap.
#
# 5. REAL BUG FIX — false stop at window close: a dry run caught BTC and
#    GOLD both "stopping out" at bid=0 (a total loss) one second AFTER
#    their window's close, immediately followed by a reversal buy at
#    100c (the worst possible price) — and that reversal then ALSO lost
#    at real settlement, which is a contradiction: the two sides of a
#    market can't both lose. The real settlement result showed YES had
#    actually won both markets the whole time. What happened: Kalshi's
#    WS ticker feed sends one last, degenerate tick right at close (the
#    order book empties out, so bid snaps toward 0 / ask toward 100) —
#    that's an artifact of the book closing, not a real price, but the
#    event-driven stop logic had no way to tell the difference and
#    fired on it instantly. Fix: handle_tick() and do_stop()'s recheck
#    now both refuse to act within STOP_DEADBAND_SEC of a window's
#    close (or after) — a position still open that close just rides to
#    the real REST settlement result instead, exactly like it already
#    does for any position that never gets stopped. This pattern (a
#    "clean" position suddenly showing a full-loss stop right near
#    close) matches this morning's real-money losses closely enough
#    that it's the leading suspect for at least some of them.
#
# LIVE = False right now — paper mode, paused after real live losses.
# Flip back to True only when explicitly told to.
#
# Kept from V11: event-driven stop off WS ticks, recheck fail-safe,
# ShardCash local balance tracking, bad-fill P&L recording, full-window
# tick log, WebSocket price feed with REST fallback, and the shard-
# transfer fix. Entry-side timing is still on the poll loop, not
# event-driven — flagged, not yet built.
# ============================================================
LIVE     = False  # LIVE TRADING OFF — paused per user request after repeated
                  # losses this morning. Runs in PAPER mode: no real orders,
                  # no real funds moved, but every window still gets watched,
                  # simulated, and logged (including the new spot/strike tick
                  # data) so analysis work can continue while this is off.
                  # Flip back to True only when explicitly told to.
PEM_PATH = '/content/drive/MyDrive/intraday key.pem'
OUT_CSV    = '/content/drive/MyDrive/commod15min_v33_trades.csv'
TICK_CSV   = '/content/drive/MyDrive/commod15min_v33_ticks.csv'
SETTLE_CSV = '/content/drive/MyDrive/commod15min_v33_settlements.csv'

SERIES = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
    "KXCOPPER15M",
    "KXPLATINUM15M",
    "KXPALLADIUM15M",
]

TRIGGER_MIN        = 7.0  # V25: armed for the last 3 minutes of each
                           # 15-min market (i.e. from minute 12 on). Entry
                           # and stop both only happen inside this window.
ENTRY_C            = 51   # V32: the Favorite = the first side whose ask
                           # is between ENTRY_C and ENTRY_CAP_C.
ENTRY_CAP_C        = 55   # V32: upper bound of the entry band.
STOP_C             = 27   # V33: reversal trigger. When the tagged
                           # favorite's bid dips to 27c or less, buy 2x
                           # CONTRACTS of the favorite (~23-27c). Closes
                           # the held opposite position + opens favorite.
                           # Held to settlement. No second reversal.
CONTRACTS          = 10
REV_SKIP_BELOW_C   = 23   # V33: no-reversal floor. If the tagged
                           # favorite's bid is already below this when a
                           # reversal would fire, skip the reversal — hold
                           # the opposite position to settlement.
POLL_SEC           = 0.5
DAILY_LOSS_LIMIT_C = 1000
MAX_TRADES_DAY     = 40
WS_MAX_AGE_SEC      = 3.0   # if the feed hasn't confirmed a price this
                            # recently, fall back to the REST snapshot
                            # for that one ticker this cycle
STOP_DEADBAND_SEC  = 2.0   # never fire a stop inside this many seconds
                            # of a window's close (or after). Kalshi's
                            # WS ticker feed sends a degenerate final
                            # tick right at close (bid snaps to 0/ask to
                            # 100 as the book empties out) that is NOT a
                            # real price and must not be read as one —
                            # see the STOP_DEADBAND note above do_stop().
                            # A position still open this close just
                            # rides to the real REST settlement result
                            # instead, same as it always has.
STOP_ACTIVATE_SEC  = 420.0  # V31: reversal armed the whole 7-min window (was 120s). (V25: stop is live the whole time
                            # the Favorite is held (entry and stop share the
                            # same 3-min window). Was 90s in V19-V24:
                            # the stop-loss check doesn't arm until the
                            # window has this many seconds (or fewer) left
                            # to close — i.e. the stop is only "live"
                            # while STOP_DEADBAND_SEC < seconds-to-close
                            # <= STOP_ACTIVATE_SEC. Before that, a held
                            # position just rides regardless of price —
                            # no stop, no reversal. Kalshi settles these
                            # 15-min crypto markets on the average of the
                            # final 60 seconds of the underlying index,
                            # not the instantaneous price at close, so
                            # mid-window dips have time to fully
                            # mean-revert before they'd matter anyway;
                            # this concentrates the stop on the stretch
                            # that's actually close to decisive.
USE_PRICE_LIMITS     = False  # V24: master switch for the order price
                            # limits below. False = orders go out exactly
                            # like V22 (99c buy / 1c sell — always fills
                            # if there are contracts at any price), with
                            # every OTHER V23 speed fix still on. Use this
                            # to measure how much the speed fixes alone
                            # close the gap, then flip to True to add the
                            # limits on top.
ENTRY_CAP_GRACE_C    = 0   # V24: an ask up to this many cents ABOVE
                            # ENTRY_CAP_C still triggers the buy, so a
                            # market that ticks 1-2c past the cap between
                            # updates isn't a missed trade. 0 = hard cap.
MAX_ENTRY_SLIPPAGE_C = 2   # V23 (only when USE_PRICE_LIMITS): an entry
                            # order pays at most this many cents above the
                            # ask seen when the trigger fired. If the
                            # book can't fill all CONTRACTS inside that,
                            # the FOK is killed and the bot retries on the
                            # next tick. 0 = only ever fill at the exact
                            # price seen.
MAX_STOP_SLIPPAGE_C  = 2   # V23 (only when USE_PRICE_LIMITS): a
                            # stop/reversal order accepts at most
                            # this many cents worse than the bid seen when
                            # the stop fired. If price gaps past that
                            # before the order lands, the FOK is killed
                            # and the stop re-fires on the next tick,
                            # priced off the new bid — it never walks the
                            # book down to 1c the way the old orders could.
ORDER_RETRY_SEC      = 0.5 # V23: minimum gap between order attempts on
                            # the same market after a FOK kill, so a thin
                            # book doesn't turn into an order-spam loop.

# Twelve Data commodity spot sourcing REMOVED in V22 — free-tier credits
# ran out, and only gold ever actually worked free (silver/WTI/platinum/
# palladium were plan-restricted from the start, copper's symbol was
# never even valid). No free source covers all 6 commodities long term
# (checked metals.dev, commoditypriceapi.com — neither works either), so
# this was just dead weight. Removing it doesn't touch trading at all —
# gold/silver/WTI/copper/platinum/palladium still trade normally off
# Kalshi's own bid/ask, same as always; this only ever fed the optional
# spot_px/pct_from_strike tick-log columns for those 6, which now just
# stay blank (floor_strike still comes from Kalshi's own market data,
# unaffected). See CommodFeed's old header comment in earlier versions
# for the full Twelve Data/Pyth history if it's ever worth revisiting.
# ============================================================


# ---- crypto spot early reversal ----
SPOT_REV_ENABLED   = False   # reverse EARLY when spot confirms the favorite is losing
SPOT_REV_MAX_BID_C = 75      # ...only if the held bid is at or below this
SPOT_REV_FROM_SEC  = 120.0   # ...only while seconds-to-close is <= this
SPOT_REV_TO_SEC    = 60.0    # ...and > this (in the last minute Kalshi beats spot)
SETTLE_RETRY_SEC   = 10.0    # settlement file: re-check an unsettled market this often
SETTLE_GIVEUP_SEC  = 1800.0  # ...and stop trying after this long

import os, sys, csv, time, math, json, uuid, base64, threading, datetime as dt
import requests
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

try:
    import websocket  # websocket-client package
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "websocket-client"],
                    check=True)
    import websocket

BASE   = "https://api.elections.kalshi.com/trade-api/v2"
PREF   = "/trade-api/v2"
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
WS_PATH = "/trade-api/ws/v2"
KEY_ID = "e0d95d64-fa0e-4c9e-be91-35660b0af725"
COLS   = ["window","mode","side","entry_iso","entry_px",
          "exit_iso","exit_px","reason","net_c","run_net_c",
          "asset","entry_s2c","exit_s2c","trigger","seen_px","src",
          "entry_spot","exit_spot","strike"]
SETTLE_COLS = ["logged_iso","ticker","asset","close_time","result",
               "floor_strike","expiration_value","status"]
TICK_COLS = ["ts_iso","ticker","asset","phase","src",
             "yes_bid","yes_ask","yes_mid","sec_to_close",
             "spot_px","floor_strike","pct_from_strike","spot_age"]

def asset(t): return t.split("15M")[0].replace("KX","")

def stop_price(entry_px):
    """V25: fixed stop level, the same for every entry — the Favorite is
    reversed once its bid is at or below STOP_C (70c). (V19-V24 used a
    stop relative to the entry price.)"""
    return STOP_C

def load_key():
    p = os.path.expanduser(PEM_PATH)
    if not os.path.exists(p): sys.exit(f"PEM not found: {p}")
    return serialization.load_pem_private_key(open(p,"rb").read(), password=None)

def _sign(k, ts, method, path):
    return base64.b64encode(k.sign(
        f"{ts}{method}{path}".encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256())).decode()

def _hdrs(k, method, path):
    ts = str(int(time.time()*1000))
    return {"KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": _sign(k, ts, method, PREF+path),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Accept": "application/json",
            "Content-Type": "application/json"}

def api_get(sess, k, path, params=None):
    for attempt in range(3):
        try:
            r = sess.get(BASE+path, headers=_hdrs(k,"GET",path),
                         params=params, timeout=8)
            if r.status_code == 404: return None
            if r.status_code in (429,) or r.status_code >= 500:
                time.sleep(0.5*(attempt+1)); continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(0.5*(attempt+1))
    return None

def api_post(sess, k, path, body):
    try:
        r = sess.post(BASE+path, headers=_hdrs(k,"POST",path),
                      json=body, timeout=8)
        return r.status_code, r.json()
    except Exception as e:
        return 0, {"error": str(e)}

def _fetch_series_open(sess, k, ser):
    out = []
    cur = None
    while True:
        p = {"series_ticker": ser, "status": "open", "limit": 100}
        if cur: p["cursor"] = cur
        d = api_get(sess, k, "/markets", p) or {}
        out += d.get("markets", []) or []
        cur = d.get("cursor")
        if not cur: break
    return out

def fetch_open(sess, k):
    """SPEED: the 3 series (BTC/ETH/SOL) used to be fetched one at a time —
    3 sequential HTTP round trips every single poll tick, easily eating the
    whole 0.5s budget before any decision logic even ran. Now fired
    concurrently so wall-clock time is ~1 request, not ~3."""
    out = []
    with ThreadPoolExecutor(max_workers=max(1, len(SERIES))) as ex:
        for result in ex.map(lambda ser: _fetch_series_open(sess, k, ser), SERIES):
            out += result
    return out

def fetch_market(sess, k, ticker):
    d = api_get(sess, k, f"/markets/{ticker}")
    return (d or {}).get("market", {}) if d else {}

def get_prices(m):
    """Returns (yes_bid, yes_ask, yes_mid) in cents or None. REST fallback path."""
    def c(v):
        if v is None: return None
        try:
            f = float(v)
            return round(f*100) if f <= 1.5 else round(f)
        except (TypeError, ValueError): return None
    yb = c(m.get("yes_bid_dollars") or m.get("yes_bid"))
    ya = c(m.get("yes_ask_dollars") or m.get("yes_ask"))
    lp = c(m.get("last_price_dollars") or m.get("last_price"))
    if yb is not None and ya is not None and ya > yb:
        return yb, ya, (yb+ya)//2
    if lp is not None:
        return lp, lp, lp
    return None

def get_balance(sess, k):
    """Cross-shard aggregate balance — display only, NOT for pre-trade checks
    (collateral is per-shard; use balance_by_shard()/DEST_SHARD for that)."""
    d = api_get(sess, k, "/portfolio/balance") or {}
    b = d.get("balance")
    return int(b) if b is not None else None

def fee_est(px): return math.ceil(7*(px/100)*(1-px/100))

def now(): return dt.datetime.now(dt.timezone.utc)
def now_iso(): return now().isoformat()
def parse_iso(s):
    try: return dt.datetime.fromisoformat(str(s).replace("Z","+00:00"))
    except (ValueError, TypeError): return None

def cancel_all_resting(sess, k):
    """Cancel every resting order — frees reserved balance, prevents self-trade cancels."""
    d = api_get(sess, k, "/portfolio/orders", {"status": "resting", "limit": 200})
    orders = (d or {}).get("orders", []) if d else []
    n = 0
    for o in orders:
        oid = o.get("order_id")
        if oid:
            try:
                sess.delete(BASE+f"/portfolio/orders/{oid}",
                            headers=_hdrs(k,"DELETE",f"/portfolio/orders/{oid}"),
                            timeout=8)
                n += 1
            except Exception:
                pass
    if n: print(f"[cleanup] cancelled {n} resting order(s)")
    return n


DEST_SHARD = 2  # crypto/commodity 15-min markets live here (confirmed via balance_breakdown)

def balance_by_shard(sess, k):
    d = api_get(sess, k, "/portfolio/balance") or {}
    out = {}
    for b in d.get("balance_breakdown", []):
        try: out[int(b["exchange_index"])] = int(round(float(b["balance"])*100))
        except (TypeError, ValueError, KeyError): pass
    return out

def move_funds_to_shard(sess, k, dest=DEST_SHARD, quiet=False):
    """Moves all free balance from shard 0 to dest.
    FIX v2: the transfer endpoint takes 'amount' in CENTICENTS (1/100 of a
    cent), not cents. The prior version sent cents directly, so it silently
    moved 1% of the intended amount every time — confirmed by test: requested
    5000c, only 50c actually landed on shard 2. Now converts (x100) and
    re-reads the destination balance afterward (with brief retries for
    settlement lag) to confirm the real amount moved, instead of trusting
    a bare HTTP 200.
    quiet=True skips both prints below — used by the periodic hot-path
    topup (ShardCash.maybe_topup), which calls this every ~10s and would
    otherwise flood the log with "nothing to move" lines on any account
    sitting under the topup target. Startup/test-cell/ARMED-entry callers
    still print normally."""
    bs = balance_by_shard(sess, k)
    have_dest = bs.get(dest, 0)
    src0 = bs.get(0, 0)
    if src0 <= 100:  # $1 or less sitting on shard 0 — not worth moving
        if not quiet:
            print(f"[transfer] shard {dest} has {have_dest}c, shard 0 has {src0}c — nothing to move")
        return True

    body = {
        "source":                      "event_contract",
        "destination":                 "event_contract",
        "amount":                      src0 * 100,  # cents -> centicents
        "source_exchange_shard":       0,
        "destination_exchange_shard":  dest,
    }
    code, resp = api_post(sess, k, "/portfolio/intra_exchange_instance_transfer", body)
    ok = code in (200, 201)
    new_dest = have_dest
    if ok:
        for _ in range(3):
            time.sleep(0.5)
            new_dest = balance_by_shard(sess, k).get(dest, 0)
            if new_dest > have_dest: break
    moved = new_dest - have_dest
    success = ok and moved > 0
    if not quiet:
        print(f"[transfer] {'OK' if success else 'FAILED'} requested {src0}c shard 0 -> {dest}: "
              f"HTTP {code} actual_moved={moved}c (dest {have_dest}c -> {new_dest}c) "
              f"{json.dumps(resp)[:150]}")
    return success

def shard_balance(sess, k, dest=DEST_SHARD):
    """Balance actually available for collateral on the trading shard —
    use this before sizing/placing an order, never the cross-shard aggregate."""
    return balance_by_shard(sess, k).get(dest, 0)

def ensure_shard_funds(sess, k, need_c, dest=DEST_SHARD, quiet=False):
    """Check shard balance; if short, sweep shard 0 -> dest once and recheck.
    Returns the (possibly updated) shard balance."""
    bal = shard_balance(sess, k, dest)
    if bal < need_c:
        move_funds_to_shard(sess, k, dest, quiet=quiet)
        bal = shard_balance(sess, k, dest)
    return bal

def place_order(sess, k, ticker, action, yes_side, count, limit_c=None):
    """
    V2 order — /portfolio/events/orders, fill_or_kill.
    bid=buy YES, ask=sell YES(=buy NO).
    limit_c is the worst price accepted, in cents OF THE SIDE BEING
    TRADED: for a buy, the most we'll pay for that side; for a sell, the
    least we'll accept for it. (NO-side limits are converted to the YES
    book here: buying NO at <=L is selling YES at >=100-L, etc.)
    V23: limit_c=None (also what every call gets when USE_PRICE_LIMITS
    is False) used to be the only mode — a 99c buy / 1c sell,
    i.e. a market order that walked the book whenever the top level
    didn't have the full count. Every trading call site now passes a
    real limit; None is kept only for the 1-contract test cell.
    FOK = all-or-nothing: the full count fills immediately at or better
    than the limit, or the whole order is killed with no partial fill.
    Orders always go through REST — Kalshi's WebSocket API is market-data
    only, there is no order-placement channel.
    """
    if not USE_PRICE_LIMITS:
        limit_c = None
    if limit_c is None:
        limit_c = 99 if action == "buy" else 1
    limit_c = max(1, min(99, int(round(limit_c))))
    if action == "buy":
        book_side = "bid" if yes_side else "ask"
        yes_px = limit_c if yes_side else 100 - limit_c
    else:
        book_side = "ask" if yes_side else "bid"
        yes_px = limit_c if yes_side else 100 - limit_c
    price = f"{yes_px/100:.4f}"

    body = {
        "ticker":                     ticker,
        "client_order_id":            str(uuid.uuid4()),
        "side":                       book_side,
        "count":                      f"{int(count)}.00",
        "price":                      price,
        "time_in_force":              "fill_or_kill",
        "self_trade_prevention_type": "taker_at_cross",
        "exchange_index":              -1,
    }
    code, resp = api_post(sess, k, "/portfolio/events/orders", body)
    o = resp if isinstance(resp, dict) else {}
    fc = 0
    try: fc = float(o.get("fill_count") or 0)
    except (TypeError, ValueError): fc = 0
    avg = None
    try:
        raw = o.get("average_fill_price")
        if raw is not None: avg = round(float(raw)*100)
    except (TypeError, ValueError): avg = None
    fp = None
    try:
        fee = o.get("average_fee_paid")
        if fee: fp = round(float(fee)*100)
    except (TypeError, ValueError): fp = None
    filled = fc >= 1
    if not filled:
        print(f"[order-fail] {ticker[-7:]} {action} HTTP {code} "
              f"no fill {json.dumps(resp)[:150]}")
    return filled, avg, fp

# ============================================================
# WEBSOCKET PRICE FEED
# One persistent connection, run in a background thread. Keeps a
# {ticker: {yes_bid, yes_ask, yes_mid, ts}} cache updated in real time
# from Kalshi's public "ticker" channel — no REST polling involved.
# track(tickers) tells it which markets to subscribe to right now;
# call it every loop with whatever's currently open, it diffs against
# what's already subscribed and only sends the add/remove delta.
# Reconnects automatically with backoff and re-subscribes to whatever
# it was last tracking. Orders are never sent over this connection.
# ============================================================
class PriceFeed:
    def __init__(self, k):
        self.k = k
        self.prices = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.tracked = set()
        self.sid = None
        self.ws = None
        self.ready = threading.Event()
        self.stop_flag = threading.Event()
        self._next_id = 1
        self.connect_count = 0
        self.on_tick = None  # set by main(): called as on_tick(ticker, yes_bid, yes_ask)
                              # the instant a price update lands, for event-driven stops

    def _cmd_id(self):
        with self.lock:
            i = self._next_id; self._next_id += 1
        return i

    def _headers(self):
        ts = str(int(time.time()*1000))
        return [f"KALSHI-ACCESS-KEY: {KEY_ID}",
                f"KALSHI-ACCESS-SIGNATURE: {_sign(self.k, ts, 'GET', WS_PATH)}",
                f"KALSHI-ACCESS-TIMESTAMP: {ts}"]

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_flag.set()
        try:
            if self.ws: self.ws.close()
        except Exception: pass

    def _run(self):
        backoff = 1
        while not self.stop_flag.is_set():
            try:
                self.ready.clear()
                ws = websocket.create_connection(WS_URL, header=self._headers(),
                                                  timeout=15)
                self.ws = ws
                self.sid = None
                self.connect_count += 1
                backoff = 1
                with self.lock:
                    want = set(self.tracked)
                if want:
                    self._subscribe(want)
                print(f"[ws] connected (#{self.connect_count})"
                      f"{f', tracking {len(want)} ticker(s)' if want else ''}")
                self.ready.set()
                while not self.stop_flag.is_set():
                    raw = ws.recv()
                    if raw:
                        self._on_message(raw)
            except Exception as e:
                if self.stop_flag.is_set(): break
                self.ready.clear()
                try:
                    if self.ws: self.ws.close()
                except Exception: pass
                self.ws = None; self.sid = None
                print(f"[ws] disconnected ({e}) — reconnecting in {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _send(self, obj):
        with self.send_lock:
            if self.ws:
                self.ws.send(json.dumps(obj))

    def _subscribe(self, tickers):
        self._send({"id": self._cmd_id(), "cmd": "subscribe",
                    "params": {"channels": ["ticker"],
                               "market_tickers": sorted(tickers),
                               "send_initial_snapshot": True}})

    def _on_message(self, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        mtype = msg.get("type")
        if mtype == "subscribed":
            self.sid = (msg.get("msg") or {}).get("sid")
        elif mtype == "ticker":
            m = msg.get("msg") or {}
            t = m.get("market_ticker")
            if not t: return
            def cents(v):
                if v is None: return None
                try: return round(float(v)*100)
                except (TypeError, ValueError): return None
            yb = cents(m.get("yes_bid_dollars"))
            ya = cents(m.get("yes_ask_dollars"))
            if yb is None or ya is None: return
            with self.lock:
                self.prices[t] = {"yes_bid": yb, "yes_ask": ya,
                                   "yes_mid": (yb+ya)//2, "ts": time.time()}
            # SPEED: fire the event-driven stop check right here, off the
            # WS thread, the instant this price lands — don't wait for the
            # next poll cycle. The handler itself must be fast (a lock +
            # dict lookup) and hand any actual order off to a worker
            # thread, or it'll delay processing ticks for other markets.
            if self.on_tick is not None:
                try:
                    self.on_tick(t, yb, ya)
                except Exception as e:
                    print(f"[on-tick-error] {e}")
        elif mtype == "error":
            print(f"[ws-error] {msg.get('msg')}")
        # type == "ok" (update_subscription ack) — nothing to do

    def track(self, tickers):
        """Call every cycle with the full set of tickers you want live
        prices for. Only sends the delta (add_markets/delete_markets)."""
        tickers = set(tickers)
        with self.lock:
            add = tickers - self.tracked
            remove = self.tracked - tickers
            self.tracked = tickers
        if not add and not remove: return
        if self.sid is None:
            if tickers: self._subscribe(tickers)
            return
        if add:
            self._send({"id": self._cmd_id(), "cmd": "update_subscription",
                        "params": {"sid": self.sid, "market_tickers": sorted(add),
                                   "action": "add_markets"}})
        if remove:
            self._send({"id": self._cmd_id(), "cmd": "update_subscription",
                        "params": {"sid": self.sid, "market_tickers": sorted(remove),
                                   "action": "delete_markets"}})

    def get(self, ticker, max_age=WS_MAX_AGE_SEC):
        """Returns (yes_bid, yes_ask, yes_mid, age_sec) or None if the feed
        has no price for this ticker yet, or it hasn't been confirmed
        fresh enough (max_age) — caller should fall back to REST."""
        with self.lock:
            d = self.prices.get(ticker)
        if not d: return None
        age = time.time() - d["ts"]
        if age > max_age: return None
        return d["yes_bid"], d["yes_ask"], d["yes_mid"], age


# ============================================================
# SPOT PRICE FEED — public, no-auth Coinbase ticker WS for the
# underlying crypto assets (BTC-USD/ETH-USD/SOL-USD), separate from
# Kalshi's own market feed above. DATA COLLECTION ONLY right now —
# nothing reads this to make a trading decision yet. The point is to
# log, every tick, how far the real asset price sits from the
# window's floor_strike (Kalshi's settlement threshold), so a future
# tick log can be mined for what actually predicts a reversal
# settling as a win vs. a whipsaw. If this feed is ever down/slow,
# the tick log just gets blank spot columns — trading is unaffected.
# ============================================================
SPOT_WS_URL = "wss://ws-feed.exchange.coinbase.com"
SPOT_ASSET_MAP = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
                   "XRP": "XRP-USD", "DOGE": "DOGE-USD"}
# Commodities (gold/silver/oil/etc.) aren't on Coinbase and, as of V22,
# have no spot feed at all (the Twelve Data commodity feed was removed —
# see the note above the old param block for why). Their tick-log
# spot_px/pct_from_strike columns just stay blank; trading is unaffected
# either way since it never used spot price, only Kalshi's own bid/ask.

class SpotFeed:
    def __init__(self, product_ids):
        self.product_ids = list(product_ids)
        self.prices = {}  # product_id -> {"price": float, "ts": float}
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.ws = None
        self.connect_count = 0

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_flag.set()
        try:
            if self.ws: self.ws.close()
        except Exception: pass

    def _run(self):
        backoff = 1
        while not self.stop_flag.is_set():
            try:
                ws = websocket.create_connection(SPOT_WS_URL, timeout=15)
                self.ws = ws
                self.connect_count += 1
                backoff = 1
                ws.send(json.dumps({"type": "subscribe",
                                     "product_ids": self.product_ids,
                                     "channels": ["ticker"]}))
                print(f"[spot] connected (#{self.connect_count}) "
                      f"tracking {', '.join(self.product_ids)}")
                while not self.stop_flag.is_set():
                    raw = ws.recv()
                    if raw:
                        self._on_message(raw)
            except Exception as e:
                if self.stop_flag.is_set(): break
                try:
                    if self.ws: self.ws.close()
                except Exception: pass
                self.ws = None
                print(f"[spot] disconnected ({e}) — reconnecting in {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _on_message(self, raw):
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if msg.get("type") != "ticker": return
        pid = msg.get("product_id")
        try:
            px = float(msg.get("price"))
        except (TypeError, ValueError):
            return
        if not pid: return
        with self.lock:
            self.prices[pid] = {"price": px, "ts": time.time()}

    def get(self, asset_code, max_age=5.0):
        """asset_code is 'BTC'/'ETH'/'SOL'. Returns (price, age_sec) or
        None if no price yet or it's stale."""
        pid = SPOT_ASSET_MAP.get(asset_code)
        if not pid: return None
        with self.lock:
            d = self.prices.get(pid)
        if not d: return None
        age = time.time() - d["ts"]
        if age > max_age: return None
        return d["price"], age


# ============================================================
# SHARD CASH — local balance tracking for shard 2.
# ensure_shard_funds() (a real balance check, and possibly a live
# transfer with retry-sleeps up to ~1.5s) was being called on the hot
# path right before every stop/reversal order — exactly where that
# extra latency hurts most. This tracks the balance locally (updated
# by arithmetic after each fill) so the hot path can skip the API call
# entirely as long as the local number plus a safety buffer covers the
# order. It's topped up proactively every loop (well before it would
# ever run low) and re-synced from the real API whenever the hot path
# does have to fall back to a live check, so it can't drift for long.
# ============================================================
class ShardCash:
    def __init__(self, sess, k, dest=DEST_SHARD):
        self.sess = sess; self.k = k; self.dest = dest
        self.lock = threading.Lock()
        self.bal = shard_balance(sess, k, dest)
        self.last_sync = time.time()

    def ensure(self, need_c, buffer_c=3000):
        """Fast path: local balance already covers need+buffer -> no API
        call at all. Otherwise falls back to a real check/sweep."""
        with self.lock:
            if self.bal >= need_c + buffer_c:
                return self.bal
        with self.lock:
            self.bal = ensure_shard_funds(self.sess, self.k, need_c, self.dest)
            self.last_sync = time.time()
            return self.bal

    def debit(self, amount_c):
        with self.lock:
            self.bal -= amount_c

    def maybe_topup(self, target_c=6000, max_age_sec=10):
        """Call once per main-loop cycle. Tops up well ahead of need so a
        live transfer's retry-sleeps never land in the middle of a trade,
        and periodically re-syncs to the real balance so local tracking
        (which is only an arithmetic estimate) can't drift indefinitely.

        FIX: gated by time only, not by time-OR-low-balance. With
        low-balance also triggering it, a bankroll sitting under
        target_c (as it normally will on a small account) made this
        fire an API call — and a "[transfer] ... nothing to move" print —
        on every single 0.5s poll cycle forever, spamming the log and
        adding a synchronous REST round trip to the main loop every
        cycle (exactly the kind of latency V11 was meant to remove).
        Now it only checks/tops up once per max_age_sec, same as the
        periodic-resync behavior already describes."""
        with self.lock:
            if time.time() - self.last_sync <= max_age_sec:
                return
            low = self.bal < target_c
        if low:
            new_bal = ensure_shard_funds(self.sess, self.k, target_c, self.dest, quiet=True)
            with self.lock:
                self.bal = new_bal
        with self.lock:
            self.last_sync = time.time()


FEED = None    # started by the "persistent price feed" cell, or lazily by main()
SPOT = None    # started lazily by main() — see SpotFeed above

def start_spot_feed():
    """(Re)starts the Coinbase spot-price feed. Safe to re-run any time —
    stops a previous feed cleanly first. Same reconnect pattern as
    start_feed(), no auth needed."""
    global SPOT
    if SPOT is not None:
        print("[spot] stopping previous feed...")
        SPOT.stop()
    SPOT = SpotFeed(SPOT_ASSET_MAP.values())
    SPOT.start()
    return SPOT

def spot_lookup(asset_code):
    """Crypto spot price (Coinbase) if this asset has one. Returns
    (price, age_sec) or None — used for every tick's spot/strike columns.
    Commodities have no spot feed as of V22 (see note above the old
    Twelve Data param block) so this just returns None for them, same as
    it already did most of the time under the old plan-restricted feed."""
    if SPOT is not None:
        v = SPOT.get(asset_code)
        if v is not None: return v
    return None

def start_feed(k):
    """(Re)starts the WebSocket price feed. Safe to re-run this cell any
    time — if a feed is already running it's stopped cleanly first, so
    this doubles as the 'reconnect' cell if the feed ever looks stuck."""
    global FEED
    if FEED is not None:
        print("[ws] stopping previous feed...")
        FEED.stop()
    FEED = PriceFeed(k)
    FEED.start()
    if FEED.ready.wait(timeout=10):
        print("[ws] feed is up")
    else:
        print("[ws] still connecting in background — REST fallback covers "
              "prices until it's ready")
    return FEED

def main():
    global FEED, SPOT
    print("Commod15min V33 CONTRARIAN — starting")
    print(f"markets: {', '.join(asset(s) for s in SERIES)}")
    k = load_key(); sess = requests.Session()
    # POOL SIZE: fetch_open() fires one concurrent request per series
    # (now 11, up from the original 3), plus do_stop's worker pool (4)
    # can also be hitting the API at the same time — comfortably over
    # requests' default pool_maxsize=10, which was silently discarding
    # connections instead of reusing them (a real "connection pool is
    # full" warning, harmless but wasteful — a fresh TCP+TLS handshake
    # every time instead of reusing one). Size it with headroom instead.
    _adapter = requests.adapters.HTTPAdapter(pool_maxsize=max(20, len(SERIES) + 10))
    sess.mount("https://", _adapter)
    sess.mount("http://", _adapter)
    try: fetch_open(sess, k)
    except Exception as e: sys.exit(f"startup failed: {e}")

    if FEED is None:
        start_feed(k)
    if SPOT is None:
        start_spot_feed()

    if LIVE:
        cancel_all_resting(sess, k)
        move_funds_to_shard(sess, k)
    mode = "LIVE" if LIVE else "PAPER"
    bal  = get_balance(sess, k)
    shard_bal_start = shard_balance(sess, k) if LIVE else None
    print(f"mode={mode}  balance={'$%.2f'%(bal/100) if bal else '—'}"
          f"  shard{DEST_SHARD}={'$%.2f'%(shard_bal_start/100) if shard_bal_start is not None else '—'}")
    print(f"rules: CONTRARIAN — armed in the last {TRIGGER_MIN:.0f}m · "
          f"Favorite's ask {ENTRY_C}-{ENTRY_CAP_C}c → buy OPPOSITE · "
          f"{CONTRACTS} contracts FOK · "
          f"if tagged favorite's bid dips to {STOP_C}c: buy {2*CONTRACTS}x FAVORITE "
          f"(closes opposite + opens favorite) · "
          f"no reversal if fav bid < {REV_SKIP_BELOW_C}c · "
          f"reversal held to settlement · stop off within {STOP_DEADBAND_SEC:.0f}s "
          f"of close · reversal armed in the last {STOP_ACTIVATE_SEC:.0f}s · "
          f"entries+stops event-driven off WS ticks · "
          + (f"orders price-limited (entry <= ask+{MAX_ENTRY_SLIPPAGE_C}c, "
             f"stop >= bid-{MAX_STOP_SLIPPAGE_C}c)" if USE_PRICE_LIMITS else
             "order price limits OFF"))

    # One worker per market (was a flat 4) — if several markets trigger a
    # stop in the same moment (a broad move hits correlated assets
    # together), none of them should have to queue behind another
    # market's order round-trip. Queuing time was pure added slippage
    # with zero upside.
    order_executor = ThreadPoolExecutor(max_workers=max(4, len(SERIES)))
    state_lock = threading.RLock()
    shard_cash = ShardCash(sess, k) if LIVE else None

    new_file = not (os.path.exists(OUT_CSV) and os.path.getsize(OUT_CSV) > 0)
    fh = open(OUT_CSV, "a", newline=""); w = csv.writer(fh)
    if new_file: w.writerow(COLS); fh.flush()

    # DATA: every price tick for every market in the 3-min window, every
    # cycle — including markets already gated out ("done") — not just
    # ones the bot is actively watching/armed/holding/reversing on. This
    # gives a full price path to settlement for every asset regardless of
    # whether it ever traded, which is what's needed to check whether
    # BTC/ETH/SOL tend to settle the same direction each window. "src"
    # column shows whether that row came from the WS feed or REST fallback.
    new_tick_file = not (os.path.exists(TICK_CSV) and os.path.getsize(TICK_CSV) > 0)
    tfh = open(TICK_CSV, "a", newline=""); tw = csv.writer(tfh)
    if new_tick_file: tw.writerow(TICK_COLS); tfh.flush()
    tick_rows_since_flush = 0

    state       = {}
    close_at    = {}
    strike_at   = {}  # ticker -> floor_strike, cached once per window
    settle_due  = {}  # ticker -> [next_check_time, first_seen_closed]

    new_settle_file = not (os.path.exists(SETTLE_CSV) and os.path.getsize(SETTLE_CSV) > 0)
    sfh = open(SETTLE_CSV, 'a', newline=''); sw = csv.writer(sfh)
    if new_settle_file: sw.writerow(SETTLE_COLS); sfh.flush()

    def s2c_now(t):
        ct = close_at.get(t)
        return None if ct is None else round((ct - now()).total_seconds(), 1)

    def strike_of(t):
        try: return float(strike_at.get(t))
        except (TypeError, ValueError): return None

    def spot_now(t):
        v = spot_lookup(asset(t))
        return v[0] if v else None

    def spot_rev_ok(t, p, held_bid, s2c):
        """Crypto early reversal: spot on the losing side of the strike,
        held bid <= SPOT_REV_MAX_BID_C, between 120s and 60s left."""
        if not SPOT_REV_ENABLED or asset(t) not in SPOT_ASSET_MAP: return False
        if not (SPOT_REV_TO_SEC < s2c <= SPOT_REV_FROM_SEC): return False
        if held_bid > SPOT_REV_MAX_BID_C: return False
        sp, kx = spot_now(t), strike_of(t)
        if sp is None or kx is None: return False
        return (sp > kx) != p["yes"]
    open_assets = set()
    run_net     = 0.0
    n_trades    = 0
    day         = now().date()
    halt        = False

    def record(ticker, reason, entry_px, exit_px, yes_side, lots, extra=None):
        # Called from the main thread and from worker threads (do_stop) —
        # the whole read-modify-write of run_net/n_trades/state/the CSV
        # writer has to happen as one atomic step. No more post-trade
        # balance refresh here — it was never printed anywhere after
        # startup, just a wasted REST round-trip on every single trade.
        nonlocal run_net, n_trades
        with state_lock:
            entry_fee = fee_est(entry_px) * lots
            exit_fee  = fee_est(exit_px) * lots if reason in ("stop", "bad-fill") else 0
            net = (exit_px - entry_px) * lots - entry_fee - exit_fee
            run_net += net; n_trades += 1
            ex = extra or {}
            pst = state.get(ticker, {})
            w.writerow([ticker, mode, "YES" if yes_side else "NO",
                        pst.get("entry_iso",""),
                        round(entry_px,1), now_iso(), round(exit_px,1),
                        reason, round(net,1), round(run_net,1),
                        asset(ticker), pst.get("entry_s2c"), s2c_now(ticker),
                        ex.get("trigger", ""), ex.get("seen", ""), ex.get("src", ""),
                        pst.get("entry_spot"), spot_now(ticker), strike_of(ticker)])
            fh.flush()
            run_net_snapshot = run_net
        print(f"[{now():%H:%M:%S}] {reason.upper()} {lots}x "
              f"{'YES' if yes_side else 'NO'} "
              f"entry={entry_px:.0f} exit={exit_px:.0f} net={net:+.0f}c  "
              f"{asset(ticker)} {ticker[-7:]}  run={run_net_snapshot:+.0f}c")

    def do_stop(t, p, fav_bid0, level=None, why="price"):
        """V33 CONTRARIAN: reversal triggered by the tagged favorite's bid
        dipping into the stop range. Buys 2x of the favorite (opposite of
        what's held), closing the contrarian position + opening favorite."""
        fav_yes = p.get("fav_yes", not p["yes"])
        fav_bid = fav_bid0
        src, src_age = "ws", 0.0
        fresh = FEED.get(t) if FEED is not None else None
        if fresh is not None:
            fyb, fya, _, src_age = fresh
            fav_bid = fyb if fav_yes else (100 - fya)

        ct = close_at.get(t)
        if ct is None or (ct - now()).total_seconds() <= STOP_DEADBAND_SEC:
            with state_lock:
                if state.get(t, {}).get("phase") == "stopping":
                    state[t] = dict(p, phase="long")
            print(f"    (inside stop deadband at execution — skip, "
                  f"let it settle, {asset(t)} {t[-7:]})")
            return

        stop_px = level if level is not None else stop_price(p["entry_px"])
        if fav_bid > stop_px:
            with state_lock:
                if state.get(t, {}).get("phase") == "stopping":
                    state[t] = dict(p, phase="long")
            print(f"    (fav bid recovered to {fav_bid:.0f}c before execution "
                  f"— skip, {asset(t)} {t[-7:]})")
            return

        if fav_bid < REV_SKIP_BELOW_C:
            with state_lock:
                if state.get(t, {}).get("phase") == "stopping":
                    state[t] = dict(p, phase="long", no_rev=True, skip_bid=fav_bid)
            print(f"    (NO REVERSAL — fav bid already {fav_bid:.0f}c < {REV_SKIP_BELOW_C}c, "
                  f"holding opposite to settlement, {asset(t)} {t[-7:]})")
            return

        # V33 CONTRARIAN: the held position is the OPPOSITE of the favorite.
        # Its exit value ~ 100 - fav_bid. The reversal buys 2x of the
        # favorite (= opposite of what's held).
        held_bid = 100 - fav_bid  # approximate held side's current value
        exit_floor = max(1, held_bid - MAX_STOP_SLIPPAGE_C)
        t_trig = time.time()

        rev_yes = not p["yes"]  # = fav_yes (the favorite we're buying into)
        combo_ok = False
        if LIVE:
            rev_ask_est = fav_bid  # favorite's ask ≈ fav_bid at these spreads
            need = int(fav_bid * 2 * p["lots"])
            shard_bal = shard_cash.ensure(need)
            if shard_bal >= need:
                filledC, avgC, fpC = place_order(
                    sess, k, t, "buy", rev_yes, 2 * p["lots"],
                    limit_c=fav_bid + MAX_STOP_SLIPPAGE_C)
                if filledC:
                    combo_ok = True
                    rev_fill = (avgC if rev_yes else 100-avgC) \
                               if avgC is not None else rev_ask_est
                    shard_cash.debit(int(rev_fill * 2 * p["lots"]))
                    exit_px = 100 - rev_fill
        else:
            combo_ok = True
            rev_fill = fav_bid
            exit_px = 100 - fav_bid

        if not combo_ok:
            if LIVE:
                filled, avg, fp = place_order(
                    sess, k, t, "sell", p["yes"], p["lots"],
                    limit_c=exit_floor)
                if not filled:
                    with state_lock:
                        state[t] = dict(p, phase="long",
                                        retry_after=time.time() + ORDER_RETRY_SEC)
                    return
                exit_px = (avg if p["yes"] else 100-avg) \
                           if avg is not None else held_bid
            else:
                exit_px = held_bid

        record(t, "stop", p["entry_px"], exit_px, p["yes"], p["lots"],
               extra={"trigger": f"{why}{stop_px:.0f}", "seen": fav_bid, "src": src})
        print(f"    ({why} stop: fav bid={fav_bid:.0f}c, held exit={exit_px:.0f}c via {src} "
              f"age {src_age:.2f}s, "
              f"{(time.time() - t_trig)*1000:.0f}ms"
              f"{', combined order' if combo_ok else ''})")

        if not combo_ok:
            if LIVE:
                need = int(fav_bid * p["lots"])
                shard_bal = shard_cash.ensure(need)
                if shard_bal < need:
                    print(f"[skip-rev-bal] {asset(t)} {t[-7:]} "
                          f"need ~{need}c on shard {DEST_SHARD}, have {shard_bal}c")
                    with state_lock:
                        open_assets.discard(asset(t)); state[t] = {"phase": "done"}
                    return
                filled2, avg2, fp2 = place_order(
                    sess, k, t, "buy", rev_yes, p["lots"],
                    limit_c=fav_bid + MAX_STOP_SLIPPAGE_C)
                if not filled2:
                    print(f"[reverse-fail] {asset(t)} {t[-7:]}")
                    with state_lock:
                        open_assets.discard(asset(t)); state[t] = {"phase": "done"}
                    return
                rev_fill = (avg2 if rev_yes else 100-avg2) \
                            if avg2 is not None else fav_bid
                shard_cash.debit(int(rev_fill * p["lots"]))
            else:
                rev_fill = fav_bid

        with state_lock:
            state[t] = {"phase": "reversal", "yes": rev_yes,
                        "entry_px": rev_fill, "lots": p["lots"],
                        "entry_iso": now_iso(), "entry_s2c": s2c_now(t),
                        "entry_spot": spot_now(t)}
        print(f"[{now():%H:%M:%S}] REVERSE into favorite {p['lots']}x "
              f"{'YES' if rev_yes else 'NO'} @ {rev_fill:.0f}c  "
              f"{asset(t)} {t[-7:]}")

    def do_entry(t, buy_yes, fav_yes, opp_ask_seen, fav_ask_seen, limit, src, src_age, t_trig):
        """V33 CONTRARIAN: buy the opposite of the favorite. Store fav_yes
        so the stop monitor knows which side to watch for the dip."""
        side = "YES" if buy_yes else "NO"
        fav_side = "YES" if fav_yes else "NO"

        def release(reason):
            with state_lock:
                if state.get(t, {}).get("phase") == "entering":
                    state[t] = {"phase": "armed",
                                "retry_after": time.time() + ORDER_RETRY_SEC}
                open_assets.discard(asset(t))
            print(f"    (entry {side} {asset(t)} {t[-7:]} not filled"
                  f"{f' inside {limit:.0f}c limit' if USE_PRICE_LIMITS else ''}"
                  f" — {reason}; will retry)")

        if LIVE:
            need = int(min(limit, opp_ask_seen + MAX_ENTRY_SLIPPAGE_C) * CONTRACTS)
            shard_bal = shard_cash.ensure(need)
            if shard_bal < need:
                print(f"[skip-bal] {asset(t)} {t[-7:]} "
                      f"need ~{need}c on shard {DEST_SHARD}, have {shard_bal}c "
                      f"(after sweep attempt)")
                with state_lock:
                    state[t] = {"phase": "done"}
                    open_assets.discard(asset(t))
                return
            filled, avg, fp = place_order(sess, k, t, "buy", buy_yes,
                                          CONTRACTS, limit_c=limit)
            if not filled:
                release("book moved or too thin")
                return
            fill = (avg if buy_yes else 100 - avg) if avg is not None else opp_ask_seen
            shard_cash.debit(int(fill * CONTRACTS))
        else:
            fresh = FEED.get(t) if FEED is not None else None
            ask_now = opp_ask_seen
            if fresh is not None:
                fyb, fya, _, _ = fresh
                ask_now = fya if buy_yes else 100 - fyb
            if ask_now > limit:
                release(f"ask now {ask_now:.0f}c")
                return
            fill = ask_now

        with state_lock:
            state[t] = {"phase": "long", "yes": buy_yes,
                        "fav_yes": fav_yes,
                        "entry_px": fill, "lots": CONTRACTS,
                        "entry_iso": now_iso(), "entry_s2c": s2c_now(t),
                        "entry_spot": spot_now(t), "entry_src": src}
        print(f"[{now():%H:%M:%S}] BUY {CONTRACTS}x {side} @ {fill:.0f}c  "
              f"{asset(t)} {t[-7:]}  run={run_net:+.0f}c  "
              f"(CONTRARIAN: fav {fav_side} was {fav_ask_seen:.0f}c, "
              f"bought opposite {side} @ {fill:.0f}c via {src} "
              f"age {src_age:.2f}s, {(time.time() - t_trig)*1000:.0f}ms trigger->fill)")

    def try_entry(t, p, yb, ya, src, src_age):
        """V33 CONTRARIAN: detect the favorite (51-55c), but BUY the
        opposite side. Tag which side was the favorite for the reversal
        trigger. Called with state_lock HELD."""
        if halt: return None
        if time.time() < p.get("retry_after", 0): return None
        ct = close_at.get(t)
        if ct is None: return None
        s2c = (ct - now()).total_seconds()
        if s2c <= 0 or s2c > TRIGGER_MIN * 60: return None
        if asset(t) in open_assets: return None
        # favorite = side with the higher mid; the band is checked on its
        # ASK — the price a buy actually pays — not on mid
        fav_yes = (yb + ya) >= 100
        fav_ask = ya if fav_yes else 100 - yb
        if fav_ask < ENTRY_C or fav_ask > ENTRY_CAP_C + ENTRY_CAP_GRACE_C: return None
        # V33: buy the OPPOSITE of the favorite
        buy_yes = not fav_yes
        opp_ask = (100 - yb) if fav_yes else ya
        limit = opp_ask + MAX_ENTRY_SLIPPAGE_C if USE_PRICE_LIMITS else 99
        state[t] = {"phase": "entering"}
        open_assets.add(asset(t))
        return (t, buy_yes, fav_yes, opp_ask, fav_ask, limit, src, src_age, time.time())

    def handle_tick(t, yb, ya, src="ws", src_age=0.0):
        """Fast path: called directly from the WS thread the instant a
        price update lands (and also once per poll cycle for the REST-
        fallback case) — must stay cheap. Just checks the trigger and,
        if it fires, claims the position (phase='entering'/'stopping', so
        nothing else can double-fire on it) and hands the actual order
        off to a worker thread via do_entry/do_stop. V23: entries are
        handled here too now, not just stops."""
        with state_lock:
            p = state.get(t)
            if not p: return
            if p.get("phase") in ("watch", "armed"):
                args = try_entry(t, p, yb, ya, src, src_age)
                if args is None: return
            else:
                args = None
        if args is not None:
            if LIVE: order_executor.submit(do_entry, *args)
            else:    do_entry(*args)
            return
        with state_lock:
            p = state.get(t)
            if not p or p.get("phase") != "long":
                return
            if p.get("no_rev"):
                return
            if time.time() < p.get("retry_after", 0):
                return
            ct = close_at.get(t)
            if ct is None:
                return
            s2c = (ct - now()).total_seconds()
            if s2c <= STOP_DEADBAND_SEC or s2c > STOP_ACTIVATE_SEC:
                return
            # V33 CONTRARIAN: monitor the TAGGED FAVORITE's bid, not the
            # held position's bid. When the favorite collapses to 23-27c,
            # that's our signal to reverse into it.
            fav_yes = p.get("fav_yes", not p["yes"])
            fav_bid = yb if fav_yes else (100 - ya)
            level, why = stop_price(p["entry_px"]), "price"
            if fav_bid > level:
                if not spot_rev_ok(t, p, fav_bid, s2c):
                    return
                level, why = SPOT_REV_MAX_BID_C, "spot"
            if fav_bid < REV_SKIP_BELOW_C:
                state[t] = dict(p, no_rev=True, skip_bid=fav_bid)
                print(f"[{now():%H:%M:%S}] NO REVERSAL — fav bid already {fav_bid:.0f}c "
                      f"(< {REV_SKIP_BELOW_C}c), holding opposite to settlement  "
                      f"{asset(t)} {t[-7:]}  {s2c:.0f}s left")
                return
            snap = dict(p)
            state[t] = dict(p, phase="stopping")
        if LIVE:
            # do_stop does real blocking network calls in LIVE mode
            # (place_order etc.) — hand it to a worker thread so a slow
            # order round trip for one market never delays reacting to
            # ticks for the others.
            order_executor.submit(do_stop, t, snap, fav_bid, level, why)
        else:
            # PAPER mode: do_stop is pure local state/logging, no network
            # I/O at all — handing it to the worker pool just adds
            # queuing/scheduling delay before its "fresh" price re-read,
            # which is pure slippage with no upside. Run it synchronously
            # instead so that re-read happens essentially instantly after
            # the trigger tick.
            do_stop(t, snap, fav_bid, level, why)

    FEED.on_tick = handle_tick

    while True:
        try:
            t0 = time.time()

            if now().date() != day:
                day = now().date(); n_trades = 0; halt = False
                # run_net only resets at midnight in LIVE mode, where it's
                # tied to DAILY_LOSS_LIMIT_C — a real daily loss cap needs
                # a fresh daily total. In PAPER mode there's no real money
                # and no daily limit in play, so run_net stays continuous
                # across the UTC day boundary instead of silently
                # dropping to 0 mid-print.
                if LIVE:
                    run_net = 0.0

            # DAILY_LOSS_LIMIT_C / MAX_TRADES_DAY only apply in LIVE mode
            # — they exist to protect real money, and there's no real
            # money at risk in PAPER mode, so capping trades there just
            # throttles data collection for no reason. This re-engages
            # automatically the moment LIVE=True again, no separate flag
            # to remember to flip back.
            if LIVE and not halt and (run_net <= -DAILY_LOSS_LIMIT_C or
                             n_trades >= MAX_TRADES_DAY):
                halt = True
                print(f"[{now():%H:%M:%S}] HALT — "
                      f"net={run_net:+.0f}c trades={n_trades}")

            live = {m["ticker"]: m
                    for m in fetch_open(sess, k) if m.get("ticker")}
            fetch_ts = time.time()  # age of the REST snapshot — only matters
                                     # now as the fallback path's timestamp

            # keep the WS subscription in sync with whatever's currently
            # open for our series — cheap no-op most cycles, only sends
            # anything when a market opens or rolls off
            if FEED is not None:
                FEED.track(live.keys())

            for t, m in live.items():
                close_at.setdefault(t, parse_iso(m.get("close_time")))
                strike_at.setdefault(t, m.get("floor_strike"))
                state.setdefault(t, {"phase": "watch"})
                settle_due.setdefault(t, [0.0, None])

            # DATA: official result for EVERY market (traded or not);
            # at most 4 lookups per loop so a window rollover stays cheap
            n_lookups = 0
            for t in list(settle_due):
                if t in live or n_lookups >= 4: continue
                due = settle_due[t]
                if due[1] is None: due[1] = time.time()
                if time.time() < due[0]: continue
                if time.time() - due[1] > SETTLE_GIVEUP_SEC:
                    del settle_due[t]; continue
                mk = fetch_market(sess, k, t); n_lookups += 1
                if mk.get("status") in ("finalized", "settled") and mk.get("result"):
                    sw.writerow([now_iso(), t, asset(t), mk.get("close_time"), mk.get("result"),
                                 mk.get("floor_strike"), mk.get("expiration_value"),
                                 mk.get("status")])
                    sfh.flush()
                    del settle_due[t]
                else:
                    due[0] = time.time() + SETTLE_RETRY_SEC

            # settle closed positions
            for t, p in list(state.items()):
                if p["phase"] not in ("long","reversal"): continue
                if t in live: continue
                m = fetch_market(sess, k, t)
                if m.get("status") in ("finalized","settled") and m.get("result"):
                    won = (m["result"] == "yes") == p["yes"]
                    # V25: label which of the 3 outcomes this cycle was.
                    #   settle_win      — outcome 1: Favorite held, won
                    #   rev_settle_win  — outcome 2: reversed, reversal won
                    #   rev_settle_loss — outcome 3: reversed, but the
                    #                     Favorite won (reversal was wrong)
                    #   settle_loss     — Favorite held and lost without
                    #                     ever triggering the 70c stop
                    #                     (e.g. fell inside the last 2s)
                    is_rev = p["phase"] == "reversal"
                    reason = (("rev_settle_win" if won else "rev_settle_loss")
                              if is_rev else
                              ("settle_win" if won else "settle_loss"))
                    record(t, reason,
                           p["entry_px"], 100 if won else 0,
                           p["yes"], p["lots"],
                           extra=({"trigger": f"skip<{REV_SKIP_BELOW_C}",
                                   "seen": p.get("skip_bid")}
                                  if p.get("no_rev") else None))
                    print("    outcome: " + {
                        "settle_win": "1 — Favorite won",
                        "rev_settle_win": "2 — reversal won",
                        "rev_settle_loss": "3 — Favorite won after being reversed out",
                        "settle_loss": "Favorite lost (stop never triggered)",
                    }[reason] + (" (reversal skipped: bid was below the floor)"
                                   if p.get("no_rev") else "")
                                + f"  {asset(t)} {t[-7:]}")
                    open_assets.discard(asset(t))
                    state[t] = {"phase": "done"}

            for t, m in live.items():
                p  = state[t]
                ct = close_at.get(t)
                if ct is None: continue
                s2c = (ct - now()).total_seconds()
                if s2c <= 0: continue

                # SPEED: prefer the WS feed's price — pushed the instant it
                # changes — over the REST batch snapshot, which can only be
                # as fresh as the last poll and can't see a move that
                # happens between polls at all. Falls back to REST per
                # ticker if the feed has nothing fresh yet.
                wsq = FEED.get(t) if FEED is not None else None
                if wsq is not None:
                    yb, ya, ymid, src_age = wsq
                    src = "ws"
                else:
                    q = get_prices(m)
                    if q is None: continue
                    yb, ya, ymid = q
                    src = "rest"; src_age = time.time() - fetch_ts
                nmid = 100 - ymid
                lmid = max(ymid, nmid)

                # DATA: log this tick for EVERY market in the window, every
                # cycle — including ones already "done" (gated out or a
                # bad-fill exit) — so every asset has a full price path to
                # settlement, not just the ones actually traded. This is
                # what lets you check cross-asset settlement correlation.
                # spot_px/floor_strike/pct_from_strike: the underlying
                # asset's real price vs. Kalshi's settlement threshold for
                # this window (crypto via SpotFeed — see spot_lookup()
                # above; commodities have no spot feed as of V22, so
                # spot_px/pct_from_strike are always blank for those 6,
                # floor_strike still comes straight from Kalshi either
                # way). Not used for any trading decision.
                spot = spot_lookup(asset(t))
                spot_px, spot_age = spot if spot else (None, None)
                strike = strike_at.get(t)
                pct_from_strike = None
                if spot_px is not None and strike:
                    pct_from_strike = round((spot_px - strike) / strike * 100, 4)
                tw.writerow([now_iso(), t, asset(t), p["phase"], src,
                             yb, ya, ymid, round(s2c, 1),
                             spot_px, strike, pct_from_strike,
                             round(spot_age, 2) if spot_age is not None else None])
                tick_rows_since_flush += 1
                if tick_rows_since_flush >= 20:
                    tfh.flush(); tick_rows_since_flush = 0

                # log the whole market (above); trade only inside the armed window
                if s2c > TRIGGER_MIN * 60: continue
                if p["phase"] == "done": continue  # logged above; nothing more to act on

                # ── WATCH -> ARMED: status line only. V23: no `continue`
                # here any more — a market already sitting at the target
                # when its watch window opens gets bought THIS cycle, not
                # one full cycle later ──
                with state_lock:
                    if state[t].get("phase") == "watch":
                        state[t] = {"phase": "armed"}
                        print(f"[armed] {asset(t)} {t[-7:]} "
                              f"fav={lmid:.0f} {s2c:.0f}s to close")

                # ── ARMED (entry) / LONG (stop) ──
                # V23: both triggers are event-driven now — handle_tick
                # runs the instant a WS tick lands. This call is the
                # backstop for the REST-fallback case (WS stale) and a
                # cheap no-op otherwise: whichever path gets there first
                # claims the market under state_lock ("entering" /
                # "stopping"), so nothing double-fires. Every order is
                # price-limited, so a stale snapshot here can't produce a
                # bad fill — at worst a killed FOK.
                handle_tick(t, yb, ya, src, src_age)
                # ── "stopping": in-flight, being handled by a worker
                # thread right now — nothing to do here.
                # ── "reversal": hold to settlement, no stop
                # (still ticked and settle-checked above) ──

            if LIVE:
                shard_cash.maybe_topup()

            elapsed = time.time() - t0
            if elapsed < POLL_SEC: time.sleep(POLL_SEC - elapsed)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[loop-error] {e}"); time.sleep(1)

    FEED.on_tick = None  # stop routing ticks into this run's closures
    print("[stopped] waiting for any in-flight stop/reversal orders...")
    order_executor.shutdown(wait=True)
    fh.flush(); fh.close()
    tfh.flush(); tfh.close()
    sfh.flush(); sfh.close()
    print(f"[stopped] trades={n_trades} net={run_net:+.0f}c")

