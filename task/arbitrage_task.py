import threading
import time
from typing import Dict, Any, Optional
from queue import Queue, Empty
import json

from core import logger
from monitor import build_monitor


class MonitorTask:
    def __init__(self, id: str, cfg: dict, queue: Queue):
        self.id = id
        self.cfg = cfg
        self.queue = queue
        self._stop = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def run(self):
        # Try to build a real monitor instance using builder function
        monitor = None
        mtype = self.cfg.get('type')
        market = self.cfg.get('market')
        freq = max(float(self.cfg.get('freq', 5)), 1.0)

        # Use the centralized builder function
        monitor = build_monitor(monitor_type=mtype, market_type="manual", slug=market)

        while not self._stop.is_set():
            result = None
            if monitor:
                ob = monitor.get_yes_orderbook()
                if ob:
                    bid = ob.bids[0] if ob.bids else None
                    ask = ob.asks[0] if ob.asks else None
                    result = {
                        'bid': {'value': bid.value, 'quantity': bid.quantity} if bid else None,
                        'ask': {'value': ask.value, 'quantity': ask.quantity} if ask else None,
                    }

            if result is None:
                result = {
                    'bid': {'value': '-', 'quantity': '-'},
                    'ask': {'value': '-', 'quantity': '-'}
                }

            # push to queue for any active SSE listeners
            try:
                self.queue.put_nowait(json.dumps(result))
            except Exception:
                pass

            time.sleep(freq)


class ArbitrageTask:
    """Monitor two markets and compute arbitrage opportunities."""
    def __init__(self, id: str, cfg: dict, queue: Queue):
        self.id = id
        self.cfg = cfg
        self.queue = queue
        self._stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.max_arb_ratio = float(cfg.get('max_arb_ratio', 1.0))  # 默认为100%
        self.max_arb_quantity = float(cfg.get('max_arb_quantity', float('inf')))  # 默认为无限制

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=1)

    def _build_monitor(self, mtype: str, market: str):
        """Build a monitor instance using builder functions."""
        return build_monitor(monitor_type=mtype, market_type="manual", slug=market)

    def run(self):
        monitor1 = self._build_monitor(self.cfg.get('type1'), self.cfg.get('market1'))
        monitor2 = self._build_monitor(self.cfg.get('type2'), self.cfg.get('market2'))
        freq = max(float(self.cfg.get('freq', 5)), 1.0)
        min_spread = float(self.cfg.get('min_spread', 0.01))

        while not self._stop.is_set():
            try:
                # Get orderbooks from both markets
                ob1 = monitor1.get_yes_orderbook() if monitor1 else None
                ob2 = monitor2.get_yes_orderbook() if monitor2 else None
                
                # Extract best bid/ask
                market1_bid = ob1.bids[0] if ob1 and ob1.bids else None
                market1_ask = ob1.asks[0] if ob1 and ob1.asks else None
                market2_bid = ob2.bids[0] if ob2 and ob2.bids else None
                market2_ask = ob2.asks[0] if ob2 and ob2.asks else None

                result = None
                # Calculate arbitrage opportunity
                if ob1 and ob2:
                    arb_spread, quantity = ob1.find_arbitrage_opportunity(ob2, min_spread)
                    # 应用最大套利比例和数量限制
                    limited_quantity = min(quantity * self.max_arb_ratio, self.max_arb_quantity)
                        
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': round(arb_spread, 6),
                        'arbitrage_quantity': round(quantity, 6),
                    }
                if result is None:
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': '-',
                        'arbitrage_quantity': '-',
                    }

                # Push to queue
                try:
                    self.queue.put_nowait(json.dumps(result))
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"Error in arbitrage task: {e}")

            time.sleep(freq)
