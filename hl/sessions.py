"""
Is an xyz market priced by the real exchange right now, or by its own book?

WHY THIS MATTERS TO A COST CHECK
--------------------------------
While the underlying market is open, trade.xyz sets its oracle from external
prices. Once it closes, the oracle is driven by trade.xyz's own order book
(an EWMA moving at most ~9.5% of the gap per update), and the mark price is
held inside a discovery band around the last external price. An order filled
then is priced against whoever is trading on the weekend, not against the
stock. What it will be worth when the real market reopens is not something a
book walk can measure. Under the rule this project runs on, a cost that cannot
be measured is not an acceptable cost, so the oracle refuses by default and
the caller has to opt in explicitly.

SCHEDULES (all times US Eastern; source: trade.xyz Specification Index and
Holiday Closures pages, read 2026-10-03)
---------
us_equity_24_5   external Sun 20:00 -> Fri 20:00 via pre, regular, post and
                 overnight (Blue Ocean ATS) sessions. Equity holidays close
                 04:00-20:00; listed overnight closures close the session that
                 starts at 20:00 that evening. Ported from Stock-Hours Guard.
futures          external Sun 18:00 -> Fri 17:00, with a 17:00-18:00 break
                 Mon-Thu. On any listed futures, energy or base-metal holiday
                 the whole day is treated as internal: conservative, since the
                 exact partial hours differ by contract group.
fx               external Sun 17:00 -> Fri 17:00.
unknown          anything else. Treated as internal.

Python on Windows ships without a timezone database, so New York time is
computed from the US DST rule directly (second Sunday of March 02:00 to first
Sunday of November 02:00) instead of adding a dependency.
"""

from datetime import date, datetime, timedelta, timezone

# 2026 dates from trade.xyz Holiday Closures. Extend yearly.
EQUITY_CLOSED = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
                 "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"}
EQUITY_EARLY_CLOSE = {"2026-11-27", "2026-12-24"}  # day sessions end 13:00
OVERNIGHT_CLOSED = {"2026-01-18", "2026-02-15", "2026-04-02", "2026-05-24", "2026-06-18",
                    "2026-07-02", "2026-09-06", "2026-11-25", "2026-12-24"}
# Union of the futures, energy and base-metal lists. Any listed day -> internal.
FUTURES_HOLIDAYS = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-02", "2026-04-03",
                    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26",
                    "2026-11-27", "2026-12-24", "2026-12-25", "2026-12-31"}

EXTERNAL, INTERNAL = "external", "internal"


def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def to_eastern(t):
    """UTC datetime -> naive New York wall-clock datetime."""
    t = t.astimezone(timezone.utc).replace(tzinfo=None)
    y = t.year
    dst_start = datetime.combine(_nth_sunday(y, 3, 2), datetime.min.time()) + timedelta(hours=7)
    dst_end = datetime.combine(_nth_sunday(y, 11, 1), datetime.min.time()) + timedelta(hours=6)
    return t - timedelta(hours=4 if dst_start <= t < dst_end else 5)


def _us_equity(et):
    d, wd, m = et.date(), et.weekday(), et.hour * 60 + et.minute  # Mon=0 .. Sun=6
    if wd == 5 or (wd == 6 and m < 20 * 60) or (wd == 4 and m >= 20 * 60):
        return INTERNAL, "weekend"
    if m >= 20 * 60:
        return (INTERNAL, "overnight holiday closure") if d.isoformat() in OVERNIGHT_CLOSED \
            else (EXTERNAL, "overnight")
    if m < 4 * 60:
        prev = (d - timedelta(days=1)).isoformat()
        return (INTERNAL, "overnight holiday closure") if prev in OVERNIGHT_CLOSED \
            else (EXTERNAL, "overnight")
    if d.isoformat() in EQUITY_CLOSED:
        return INTERNAL, "equity holiday"
    if d.isoformat() in EQUITY_EARLY_CLOSE and m >= 13 * 60:
        return INTERNAL, "early close"
    if m < 9 * 60 + 30:
        return EXTERNAL, "pre-market"
    return (EXTERNAL, "regular") if m < 16 * 60 else (EXTERNAL, "post-market")


def _weekly(et, open_sun, close_fri, daily_break=False):
    wd, m = et.weekday(), et.hour * 60 + et.minute
    if wd == 5 or (wd == 6 and m < open_sun) or (wd == 4 and m >= close_fri):
        return INTERNAL, "weekend"
    if daily_break and wd <= 3 and 17 * 60 <= m < 18 * 60:
        return INTERNAL, "daily maintenance break"
    return EXTERNAL, "open"


def session(schedule, t=None):
    """(external|internal, why, eastern time as text) for a schedule at UTC time t."""
    t = t or datetime.now(timezone.utc)
    et = to_eastern(t)
    if schedule == "us_equity_24_5":
        state, why = _us_equity(et)
    elif schedule == "futures":
        if et.date().isoformat() in FUTURES_HOLIDAYS:
            state, why = INTERNAL, "futures holiday (whole day, conservative)"
        else:
            state, why = _weekly(et, 18 * 60, 17 * 60, daily_break=True)
    elif schedule == "fx":
        state, why = _weekly(et, 17 * 60, 17 * 60)
    else:
        state, why = INTERNAL, "schedule unknown"
    return state, why, et.strftime("%a %Y-%m-%d %H:%M ET")
