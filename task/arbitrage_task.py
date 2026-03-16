import threading
import time
from typing import Dict, Any, Optional, Tuple
from queue import Queue, Empty
import json

from core import logger
from monitor import build_monitor, BaseMonitor

_RESULT_PATH = "../logs/results.csv"

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
        self.status = 'running'
        self.cumulative_profit = 0.0
        self.cumulative_risk_exposure = 0.0
        self.cumulative_fee = 0.0

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.status = 'stopped'
        if self.thread:
            self.thread.join(timeout=1)
        self._save_results()

    def _save_results(self):
        """Save results to a CSV file for later analysis."""
        try:
            with open(_RESULT_PATH, 'a') as f:
                f.write(f"{self.id},{self.cfg.get('type1')}-{self.cfg.get('market1')},{self.cfg.get('type2')}-{self.cfg.get('market2')},"
                        f"{self.arb_cnt},{self.max_arb_cnt},"
                        f"{self.max_arb_ratio},{self.max_arb_quantity},"
                        f"{round(self.cumulative_profit, 6)},{round(self.cumulative_risk_exposure, 6)},"
                        f"{round(self.cumulative_fee, 6)},{self.status}\n")
        except Exception as e:
            logger.error(f"Error saving results for task {self.id}: {e}")

    def _build_monitor(self, mtype: str, market: str):
        """Build a monitor instance using builder functions."""
        return build_monitor(monitor_type=mtype, market_type="manual", slug=market)

    def _execute_order_leg(
        self,
        monitor: BaseMonitor,
        price: float,
        size: float,
        side: str,
        yes_or_no: bool,
    ) -> Tuple[float, float, float]:
        """Execute one market leg and always attempt to cancel leftovers."""
        default_result = (0.0, 0.0, 0.0)
        if not monitor:
            return default_result

        try:
            order_result = monitor.place_limit_order_fak(price, size, side, yes_or_no)
            if not order_result:
                return default_result
            qty, volume, fee = order_result
            return float(qty or 0.0), float(volume or 0.0), float(fee or 0.0)
        except Exception as e:
            logger.error(f"Error placing order leg for task {self.id}: {e}")
            return default_result
        finally:
            try:
                monitor.cancel_all_open_orders()
            except Exception as e:
                logger.error(f"Error canceling open orders for task {self.id}: {e}")

    def _execute_parallel_order_legs(
        self,
        leg1: Tuple[BaseMonitor, float, float, str, bool],
        leg2: Tuple[BaseMonitor, float, float, str, bool],
    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """Run both market legs concurrently to reduce sequential blocking time."""
        results = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]

        def _runner(index: int, leg: Tuple[BaseMonitor, float, float, str, bool]):
            monitor, price, size, side, yes_or_no = leg
            results[index] = self._execute_order_leg(monitor, price, size, side, yes_or_no)

        thread1 = threading.Thread(target=_runner, args=(0, leg1), daemon=True)
        thread2 = threading.Thread(target=_runner, args=(1, leg2), daemon=True)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        return results[0], results[1]

    def _update_trade_stats(self, qty1: float, vlm1: float, fee1: float, qty2: float, vlm2: float, fee2: float):
        """Accumulate fee/profit/exposure based on realized two-leg execution."""
        qty1 = float(qty1 or 0.0)
        qty2 = float(qty2 or 0.0)
        vlm1 = float(vlm1 or 0.0)
        vlm2 = float(vlm2 or 0.0)
        fee1 = float(fee1 or 0.0)
        fee2 = float(fee2 or 0.0)

        self.cumulative_fee += fee1 + fee2

        if qty1 > 0 and qty2 > 0 and abs(qty1 - qty2) <= 1e-9:
            # Fully hedged pair: payoff is qty * $1 at settlement.
            self.cumulative_profit += qty1 * 1.0 - vlm1 - vlm2
        else:
            # Any imbalance leaves one-sided position exposure.
            if qty1 > qty2:
                self.cumulative_risk_exposure += (qty1 - qty2) * vlm1/qty1
            elif qty2 > qty1:
                self.cumulative_risk_exposure += (qty2 - qty1) * vlm2/qty2

    def _is_arbitrage_limit_reached(self) -> bool:
        return self.max_arb_cnt > 0 and self.arb_cnt >= self.max_arb_cnt

    def run(self):
        monitor1 = self._build_monitor(self.cfg.get('type1'), self.cfg.get('market1'))
        monitor2 = self._build_monitor(self.cfg.get('type2'), self.cfg.get('market2'))
        freq = max(float(self.cfg.get('freq', 5)), 1.0)
        min_spread = float(self.cfg.get('min_spread', 0.01))

        while not self._stop.is_set():
            try:
                if self._is_arbitrage_limit_reached():
                    self.status = 'finished'
                    final_result = {
                        'market1_bid': '-',
                        'market1_ask': '-',
                        'market2_bid': '-',
                        'market2_ask': '-',
                        'arbitrage_spread': '-',
                        'arbitrage_quantity': '-',
                        'arb_cnt': self.arb_cnt,
                        'max_arb_cnt': self.max_arb_cnt,
                        'status': self.status,
                        'cumulative_profit': round(self.cumulative_profit, 6),
                        'cumulative_risk_exposure': round(self.cumulative_risk_exposure, 6),
                        'cumulative_fee': round(self.cumulative_fee, 6),
                    }
                    try:
                        self.queue.put_nowait(json.dumps(final_result))
                        self._save_results()
                    except Exception:
                        pass
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
                            order_result1, order_result2 = self._execute_parallel_order_legs(
                                (monitor1, 1 - sell_price, limited_quantity, 'BUY', False),
                                (monitor2, buy_price, limited_quantity, 'BUY', True),
                            )
                            qty1, vlm1, fee1 = order_result1
                            qty2, vlm2, fee2 = order_result2
                            self._update_trade_stats(qty1, vlm1, fee1, qty2, vlm2, fee2)
                    
                    # 检查是否能从market1买入，在market2卖出获利
                    if market2_bid and market1_ask:
                        arb_spread = max(market2_bid.value - market1_ask.value, arb_spread or -float('inf'))
                        buy_price, sell_price, quantity = ob1.find_arbitrage_opportunity(ob2, min_spread)
                        # 应用最大套利比例和数量限制
                        limited_quantity = min(quantity * self.max_arb_ratio, self.max_arb_quantity)
                        if limited_quantity > 0:
                            self.arb_cnt += 1
                            order_result1, order_result2 = self._execute_parallel_order_legs(
                                (monitor1, buy_price, limited_quantity, 'BUY', True),
                                (monitor2, 1 - sell_price, limited_quantity, 'BUY', False),
                            )
                            qty1, vlm1, fee1 = order_result1
                            qty2, vlm2, fee2 = order_result2
                            self._update_trade_stats(qty1, vlm1, fee1, qty2, vlm2, fee2)
                    
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': round(arb_spread, 6) if arb_spread is not None else '-',
                        'arbitrage_quantity': round(quantity, 6) if quantity is not None else '-',
                        'arb_cnt': self.arb_cnt,
                        'max_arb_cnt': self.max_arb_cnt,
                        'status': self.status,
                        'cumulative_profit': round(self.cumulative_profit, 6),
                        'cumulative_risk_exposure': round(self.cumulative_risk_exposure, 6),
                        'cumulative_fee': round(self.cumulative_fee, 6),
                    }
                if result is None:
                    result = {
                        'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
                        'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
                        'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
                        'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
                        'arbitrage_spread': '-',
                        'arbitrage_quantity': '-',
                        'arb_cnt': self.arb_cnt,
                        'max_arb_cnt': self.max_arb_cnt,
                        'status': self.status,
                        'cumulative_profit': round(self.cumulative_profit, 6),
                        'cumulative_risk_exposure': round(self.cumulative_risk_exposure, 6),
                        'cumulative_fee': round(self.cumulative_fee, 6),
                    }

                # Push to queue
                try:
                    self.queue.put_nowait(json.dumps(result))
                except Exception:
                    pass

            except Exception as e:
                self.status = 'aborted'
                self._save_results()
                logger.error(f"Error in arbitrage task: {e}")

            time.sleep(freq)
