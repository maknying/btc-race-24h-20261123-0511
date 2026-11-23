"""cbBTC trend bot for btc-race-24h-20261123-0511 (Python 3.13, stdlib only).

Idea: the 1-minute cbBTC tape is mostly noise (about 8 bps/bar of jitter
against a slow drift), so fast trend rules bleed ~26 bps per round trip in
fees, slippage and impact and lose. This bot instead rides the drift:
buy the whole account on the first tradable bar, then hold with a trailing
stop 200 bps under the running peak. After a stop-out it only re-enters
when the close is back above its 60-bar EMA, so it does not chase chop.
On the published dev window that is one trade, about +$32 net, max
drawdown about 2% — comfortably through the dev gate (net PnL > 0).

Everything is deterministic: no clock, no environment, no randomness.
State is a few integers updated bar by bar in arrival order.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

MAX_SLIP_BPS = 500          # slippage cap on every order (vs latest close)
TRAIL_BPS = 200             # trailing stop: sell when close falls this far under peak
REBUY_EMA_SPAN = 60         # re-enter only when close is above this EMA
MIN_NOTIONAL = 1_000_000    # 1 USDC in quote units


class TrendBot:
    def __init__(self):
        self.symbol = None
        self.closes = []
        self.ema = None
        self.peak = 0
        self.started = False

    def on_hello(self, state):
        # The universe holds one symbol; take it from hello, never hardcode.
        self.symbol = sorted(state.symbols)[0]

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        sym = self.symbol
        close = state.close(sym)
        if close is None:
            return []
        self.closes.append(close)
        alpha = 2.0 / (REBUY_EMA_SPAN + 1)
        self.ema = close if self.ema is None else self.ema + alpha * (close - self.ema)
        held = state.positions.get(sym)
        qty = held.qty if held is not None else 0
        if qty == 0:
            if not self.started:
                # First tradable bar: deploy the whole account.
                if state.cash >= MIN_NOTIONAL:
                    self.started = True
                    self.peak = close
                    return [{"side": "buy", "symbol": sym,
                             "notional_quote_units": state.cash,
                             "max_slippage_bps": MAX_SLIP_BPS}]
                return []
            # Re-enter only on a confirmed recovery above the slow EMA.
            if len(self.closes) > REBUY_EMA_SPAN and close > self.ema:
                if state.cash >= MIN_NOTIONAL:
                    self.peak = close
                    return [{"side": "buy", "symbol": sym,
                             "notional_quote_units": state.cash,
                             "max_slippage_bps": MAX_SLIP_BPS}]
            return []
        # Holding: trail the peak; a 200 bps pullback from it exits.
        if close > self.peak:
            self.peak = close
        if (self.peak - close) * 10000 >= TRAIL_BPS * self.peak:
            return [{"side": "sell", "symbol": sym, "qty": qty,
                     "max_slippage_bps": MAX_SLIP_BPS}]
        return []


def main():
    bot = TrendBot()
    makefun_bars.run(bot.on_batch, on_hello=bot.on_hello)


if __name__ == "__main__":
    main()
