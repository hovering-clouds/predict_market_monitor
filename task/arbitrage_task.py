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
        self.max_arb_cnt = int(cfg.get('max_arb_cnt', 0))  # 默认为不限制套利次数
        self.arb_cnt = 0 # 已执行的套利次数

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
                if self.max_arb_cnt > 0 and self.arb_cnt >= self.max_arb_cnt:
                    logger.info(f"Reached max arbitrage count {self.max_arb_cnt}, stopping task {self.id}")
                    break
                # Get orderbooks from both markets
                ob1 = monitor1.get_yes_orderbook() if monitor1 else None
                ob2 = monitor2.get_yes_orderbook() if monitor2 else None
                
                # Extract best bid/ask
                market1_bid = ob1.bids[0] if ob1 and ob1.bids else None
                market1_ask = ob1.asks[0] if ob1 and ob1.asks else None
                market2_bid = ob2.bids[0] if ob2 and ob2.bids else None
                market2_ask = ob2.asks[0] if ob2 and ob2.asks else None

                result = None
                arb_spread = None
                quantity = None
                # Calculate arbitrage opportunity
                if ob1 and ob2:
                    # 检查是否能从market2买入，在market1卖出获利
                    if market1_bid and market2_ask:
                        arb_spread = market1_bid.value - market2_ask.value
                        buy_price, sell_price, quantity = ob2.find_arbitrage_opportunity(ob1, min_spread)
                        # 应用最大套利比例和数量限制
                        limited_quantity = min(quantity * self.max_arb_ratio, self.max_arb_quantity)
                        if limited_quantity > 0:
                            self.arb_cnt += 1
                            order_result1 = monitor1.place_limit_order_fak(1-sell_price, limited_quantity, 'BUY', False) # 在market1卖出yes（即买入no）
                            order_result2 = monitor2.place_limit_order_fak(buy_price, limited_quantity, 'BUY', True)    # 在market2买入yes
                            monitor1.cancel_all_open_orders()
                            monitor2.cancel_all_open_orders()
                            qty1, vlm1, fee1 = order_result1 if order_result1 else (0.0, 0.0, 0.0)
                            qty2, vlm2, fee2 = order_result2 if order_result2 else (0.0, 0.0, 0.0)
                    
                    # 检查是否能从market1买入，在market2卖出获利
                    if market2_bid and market1_ask:
                        arb_spread = market2_bid.value - market1_ask.value
                        buy_price, sell_price, quantity = ob1.find_arbitrage_opportunity(ob2, min_spread)
                        # 应用最大套利比例和数量限制
                        limited_quantity = min(quantity * self.max_arb_ratio, self.max_arb_quantity)
                        if limited_quantity > 0:
                            self.arb_cnt += 1
                            order_result1 = monitor1.place_limit_order_fak(1-buy_price, limited_quantity, True)  # 在market1买入yes
                            order_result2 = monitor2.place_limit_order_fak(sell_price, limited_quantity, 'BUY', False) # 在market2卖出yes（即买入no）
                            monitor1.cancel_all_open_orders()
                            monitor2.cancel_all_open_orders()
                            qty1, vlm1, fee1 = order_result1 if order_result1 else (0.0, 0.0, 0.0)
                            qty2, vlm2, fee2 = order_result2 if order_result2 else (0.0, 0.0, 0.0)
                    
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': round(arb_spread, 6) if arb_spread is not None else '-',
                        'arbitrage_quantity': round(quantity, 6) if quantity is not None else '-',
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
