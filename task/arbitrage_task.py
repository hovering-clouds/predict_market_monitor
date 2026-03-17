import threading
import time
from typing import Dict, Any, Optional, Tuple
from queue import Queue, Empty
import json
import math

from core import logger
from monitor import build_monitor, BaseMonitor
from core.utils import OrderBook

_RESULT_PATH = "./logs/results.csv"

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
        self.min_order_quantity = self._parse_non_negative_float(cfg.get('min_order_quantity', 5.0))
        self.min_order_amount = self._parse_non_negative_float(cfg.get('min_order_amount', 1.0))
        self.market1_budget = self._parse_budget(cfg.get('market1_budget'))
        self.market2_budget = self._parse_budget(cfg.get('market2_budget'))
        self.market1_remaining_budget = self.market1_budget
        self.market2_remaining_budget = self.market2_budget
        self.market1_consumed_budget = 0.0
        self.market2_consumed_budget = 0.0
        self.arb_cnt = 0 # 已执行的套利次数（统计用途，不作为停止条件）
        self.status = 'running'
        self.cumulative_profit = 0.0
        self.cumulative_risk_exposure = 0.0
        self.cumulative_fee = 0.0

    def _parse_budget(self, value: Any) -> float:
        """Parse per-market allocated budget; non-positive or invalid means unlimited."""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return float('inf')
        return parsed if parsed > 0 else float('inf')

    def _parse_non_negative_float(self, value: Any) -> float:
        """Parse non-negative numeric config values; invalid values fallback to 0."""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return parsed if parsed >= 0 else 0.0

    def _serialize_number(self, value: float, digits: int = 6):
        """Serialize numbers for JSON payloads; unlimited values are represented as null."""
        if not math.isfinite(value):
            return None
        return round(value, digits)

    def _serialize_for_csv(self, value: float, digits: int = 6) -> str:
        if not math.isfinite(value):
            return 'inf'
        return str(round(value, digits))

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
                        f"{self.arb_cnt},"
                        f"{self.max_arb_ratio},{self.max_arb_quantity},{self.min_order_quantity},{self.min_order_amount},"
                        f"{self._serialize_for_csv(self.market1_budget)},{self._serialize_for_csv(self.market1_remaining_budget)},"
                        f"{self._serialize_for_csv(self.market2_budget)},{self._serialize_for_csv(self.market2_remaining_budget)},"
                        f"{round(self.cumulative_profit, 6)},{round(self.cumulative_risk_exposure, 6)},"
                        f"{round(self.cumulative_fee, 6)},{self.status}\n")
        except Exception as e:
            logger.error(f"Error saving results for task {self.id}: {e}")

    def _build_monitor(self, mtype: str, market: str):
        """Build a monitor instance using builder functions."""
        return build_monitor(monitor_type=mtype, market_type="manual", slug=market)

    def _execute_parallel_order_legs(
        self,
        leg1: Tuple[BaseMonitor, float, float, str, bool],
        leg2: Tuple[BaseMonitor, float, float, str, bool],
    ) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """Run both market legs concurrently to reduce sequential blocking time."""
        results: list[Optional[Tuple[float, float, float]]] = [None, None]

        def _runner(index: int, leg: Tuple[BaseMonitor, float, float, str, bool]):
            monitor, price, size, side, yes_or_no = leg
            order_id = monitor.place_limit_order_fak(price=price, size=size, side=side, yes_or_no=yes_or_no)
            if order_id is None:
                return
            order = monitor.get_order(order_id)
            leg_result = monitor.parse_order_result(order)
            results[index] = leg_result

        thread1 = threading.Thread(target=_runner, args=(0, leg1), daemon=True)
        thread2 = threading.Thread(target=_runner, args=(1, leg2), daemon=True)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        if results[0] is None or results[1] is None:
            raise RuntimeError("Order placement failed in at least one market leg")

        return results[0], results[1]

    def _execute_parallel_get_orderbook(self, monitor1: BaseMonitor, monitor2: BaseMonitor) -> Tuple[Optional[OrderBook], Optional[OrderBook]]:
        """Fetch orderbooks from both monitors in parallel to minimize latency."""
        orderbooks: list[Optional[OrderBook]] = [None, None]

        def _fetch_ob(index: int, monitor: BaseMonitor):
            ob = monitor.get_yes_orderbook()
            orderbooks[index] = ob

        thread1 = threading.Thread(target=_fetch_ob, args=(0, monitor1), daemon=True)
        thread2 = threading.Thread(target=_fetch_ob, args=(1, monitor2), daemon=True)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        return orderbooks[0], orderbooks[1]

    def _update_trade_stats(self, qty1: float, vlm1: float, fee1: float, qty2: float, vlm2: float, fee2: float):
        """Accumulate fee/profit/exposure based on realized two-leg execution."""
        qty1 = float(qty1 or 0.0)
        qty2 = float(qty2 or 0.0)
        vlm1 = float(vlm1 or 0.0)
        vlm2 = float(vlm2 or 0.0)
        fee1 = float(fee1 or 0.0)
        fee2 = float(fee2 or 0.0)

        self.cumulative_fee += fee1 + fee2

        # Track per-market budget consumption using realized traded volume plus fee.
        spent1 = max(vlm1 + fee1, 0.0)
        spent2 = max(vlm2 + fee2, 0.0)
        self.market1_consumed_budget += spent1
        self.market2_consumed_budget += spent2
        if math.isfinite(self.market1_budget):
            self.market1_remaining_budget = max(self.market1_budget - self.market1_consumed_budget, 0.0)
        if math.isfinite(self.market2_budget):
            self.market2_remaining_budget = max(self.market2_budget - self.market2_consumed_budget, 0.0)

        if qty1 > 0 and qty2 > 0 and abs(qty1 - qty2) <= 1e-9:
            # Fully hedged pair: payoff is qty * $1 at settlement.
            self.cumulative_profit += qty1 * 1.0 - vlm1 - vlm2
        else:
            # Any imbalance leaves one-sided position exposure.
            if qty1 > qty2:
                self.cumulative_risk_exposure += (qty1 - qty2) * vlm1/qty1
            elif qty2 > qty1:
                self.cumulative_risk_exposure += (qty2 - qty1) * vlm2/qty2
        
        logger.info(f"successfully executed arbitrage legs with qty1={qty1}, qty2={qty2}.")

    def _is_budget_exhausted(self) -> bool:
        epsilon = 1e-9
        return self.market1_remaining_budget <= epsilon or self.market2_remaining_budget <= epsilon

    def _budget_limited_quantity(self, price1: float, price2: float) -> float:
        """Compute max executable quantity under current remaining budgets for two legs."""
        price1 = float(price1 or 0.0)
        price2 = float(price2 or 0.0)
        if price1 <= 0 or price2 <= 0:
            return 0.0

        cap1 = float('inf') if not math.isfinite(self.market1_remaining_budget) else self.market1_remaining_budget / price1
        cap2 = float('inf') if not math.isfinite(self.market2_remaining_budget) else self.market2_remaining_budget / price2
        return max(min(cap1, cap2), 0.0)

    def _minimum_required_quantity(self, leg1_price: float, leg2_price: float) -> float:
        """Compute minimum executable quantity from API minimum quantity and amount constraints."""
        min_qty = self.min_order_quantity
        if self.min_order_amount <= 0:
            return min_qty

        leg1_price = float(leg1_price or 0.0)
        leg2_price = float(leg2_price or 0.0)
        if leg1_price <= 0 or leg2_price <= 0:
            return float('inf')

        amount_based_min_qty = max(self.min_order_amount / leg1_price, self.min_order_amount / leg2_price)
        return max(min_qty, amount_based_min_qty)

    def _limited_order_quantity(self, opportunity_quantity: float, leg1_price: float, leg2_price: float) -> float:
        """Apply all quantity controls and return executable order size, 0 when constraints cannot be met."""
        opportunity_quantity = max(float(opportunity_quantity or 0.0), 0.0)
        max_allowed_quantity = min(
            opportunity_quantity * self.max_arb_ratio,
            self.max_arb_quantity,
            self._budget_limited_quantity(leg1_price, leg2_price),
        )

        if max_allowed_quantity <= 0:
            return 0.0

        min_required_quantity = self._minimum_required_quantity(leg1_price, leg2_price)
        if max_allowed_quantity + 1e-9 < min_required_quantity:
            return 0.0

        return max_allowed_quantity

    def _build_result_payload(
        self,
        market1_bid,
        market1_ask,
        market2_bid,
        market2_ask,
        arbitrage_spread,
        arbitrage_quantity,
    ) -> Dict[str, Any]:
        return {
            'market1_bid': {'value': market1_bid.value, 'quantity': market1_bid.quantity} if market1_bid else '-',
            'market1_ask': {'value': market1_ask.value, 'quantity': market1_ask.quantity} if market1_ask else '-',
            'market2_bid': {'value': market2_bid.value, 'quantity': market2_bid.quantity} if market2_bid else '-',
            'market2_ask': {'value': market2_ask.value, 'quantity': market2_ask.quantity} if market2_ask else '-',
            'arbitrage_spread': arbitrage_spread,
            'arbitrage_quantity': arbitrage_quantity,
            'arb_cnt': self.arb_cnt,
            'status': self.status,
            'max_arb_ratio': self.max_arb_ratio,
            'max_arb_quantity': self._serialize_number(self.max_arb_quantity),
            'min_order_quantity': self._serialize_number(self.min_order_quantity),
            'min_order_amount': self._serialize_number(self.min_order_amount),
            'market1_budget': self._serialize_number(self.market1_budget),
            'market2_budget': self._serialize_number(self.market2_budget),
            'market1_remaining_budget': self._serialize_number(self.market1_remaining_budget),
            'market2_remaining_budget': self._serialize_number(self.market2_remaining_budget),
            'market1_consumed_budget': self._serialize_number(self.market1_consumed_budget),
            'market2_consumed_budget': self._serialize_number(self.market2_consumed_budget),
            'cumulative_profit': round(self.cumulative_profit, 6),
            'cumulative_risk_exposure': round(self.cumulative_risk_exposure, 6),
            'cumulative_fee': round(self.cumulative_fee, 6),
        }

    def run(self):
        monitor1 = self._build_monitor(self.cfg.get('type1'), self.cfg.get('market1'))
        monitor2 = self._build_monitor(self.cfg.get('type2'), self.cfg.get('market2'))
        freq = max(float(self.cfg.get('freq', 5)), 1.0)
        min_spread = float(self.cfg.get('min_spread', 0.01))

        while not self._stop.is_set():
            try:
                if self._is_budget_exhausted():
                    self.status = 'finished'
                    final_result = self._build_result_payload(
                        market1_bid=None,
                        market1_ask=None,
                        market2_bid=None,
                        market2_ask=None,
                        arbitrage_spread='-',
                        arbitrage_quantity='-',
                    )
                    try:
                        self.queue.put_nowait(json.dumps(final_result))
                        self._save_results()
                    except Exception:
                        pass
                    logger.info(
                        f"Budget exhausted for task {self.id}, stopping. "
                        f"remaining market1={self._serialize_for_csv(self.market1_remaining_budget)}, "
                        f"market2={self._serialize_for_csv(self.market2_remaining_budget)}"
                    )
                    break
                
                if monitor1 is None or monitor2 is None:
                    logger.error(f"One or both monitors failed to initialize for task {self.id}, aborting.")
                    self.status = 'aborted'
                    self._save_results()
                    break

                # Get orderbooks from both markets
                ob1, ob2 = self._execute_parallel_get_orderbook(monitor1, monitor2)
                
                if ob1 is None or ob2 is None:
                    logger.warning(f"Failed to fetch orderbooks for task {self.id}, aborting.")
                    self.status = 'aborted'
                    self._save_results()
                    break

                # Extract best bid/ask
                market1_bid = ob1.bids[0] if ob1.bids else None
                market1_ask = ob1.asks[0] if ob1.asks else None
                market2_bid = ob2.bids[0] if ob2.bids else None
                market2_ask = ob2.asks[0] if ob2.asks else None

                result = None
                arb_spread = None
                quantity = None
                quantity_display = '-'

                # Calculate arbitrage opportunity
                if ob1 and ob2:
                    # 检查是否能从market2买入，在market1卖出获利
                    if market1_bid and market2_ask and not self._is_budget_exhausted():
                        arb_spread = market1_bid.value - market2_ask.value
                        buy_price, sell_price, quantity = ob2.find_arbitrage_opportunity(ob1, min_spread)
                        buy_price = float(buy_price or 0.0)
                        sell_price = float(sell_price or 0.0)
                        quantity = max(float(quantity or 0.0), 0.0)

                        leg1_price = 1 - sell_price
                        leg2_price = buy_price
                        # 应用最大/最小数量、最小金额和预算限制
                        limited_quantity = self._limited_order_quantity(quantity, leg1_price, leg2_price)
                        quantity_display = round(limited_quantity, 6) if limited_quantity > 0 else '-'
                        if limited_quantity > 0:
                            order_result1, order_result2 = self._execute_parallel_order_legs(
                                (monitor1, leg1_price, limited_quantity, 'BUY', False),
                                (monitor2, leg2_price, limited_quantity, 'BUY', True),
                            )
                            qty1, vlm1, fee1 = order_result1
                            qty2, vlm2, fee2 = order_result2
                            self._update_trade_stats(qty1, vlm1, fee1, qty2, vlm2, fee2)
                            if qty1 > 0 or qty2 > 0:
                                self.arb_cnt += 1
                            if self._is_budget_exhausted():
                                self.status = 'finished'
                                break
                    
                    # 检查是否能从market1买入，在market2卖出获利
                    if market2_bid and market1_ask and not self._is_budget_exhausted():
                        arb_spread = max(
                            market2_bid.value - market1_ask.value,
                            arb_spread if arb_spread is not None else -float('inf')
                        )
                        buy_price, sell_price, quantity = ob1.find_arbitrage_opportunity(ob2, min_spread)
                        buy_price = float(buy_price or 0.0)
                        sell_price = float(sell_price or 0.0)
                        quantity = max(float(quantity or 0.0), 0.0)

                        leg1_price = buy_price
                        leg2_price = 1 - sell_price
                        # 应用最大/最小数量、最小金额和预算限制
                        limited_quantity = self._limited_order_quantity(quantity, leg1_price, leg2_price)
                        quantity_display = round(limited_quantity, 6) if limited_quantity > 0 else quantity_display
                        if limited_quantity > 0:
                            order_result1, order_result2 = self._execute_parallel_order_legs(
                                (monitor1, leg1_price, limited_quantity, 'BUY', True),
                                (monitor2, leg2_price, limited_quantity, 'BUY', False),
                            )
                            qty1, vlm1, fee1 = order_result1
                            qty2, vlm2, fee2 = order_result2
                            self._update_trade_stats(qty1, vlm1, fee1, qty2, vlm2, fee2)
                            if qty1 > 0 or qty2 > 0:
                                self.arb_cnt += 1
                            if self._is_budget_exhausted():
                                self.status = 'finished'
                                break

                    if quantity_display == '-' and quantity is not None:
                        try:
                            quantity_display = round(float(quantity), 6)
                        except (TypeError, ValueError):
                            quantity_display = '-'
                    
                    result = self._build_result_payload(
                        market1_bid=market1_bid,
                        market1_ask=market1_ask,
                        market2_bid=market2_bid,
                        market2_ask=market2_ask,
                        arbitrage_spread=round(arb_spread, 6) if arb_spread is not None else '-',
                        arbitrage_quantity=quantity_display,
                    )

                if result is None:
                    result = self._build_result_payload(
                        market1_bid=market1_bid,
                        market1_ask=market1_ask,
                        market2_bid=market2_bid,
                        market2_ask=market2_ask,
                        arbitrage_spread='-',
                        arbitrage_quantity='-',
                    )

                # Push to queue
                try:
                    self.queue.put_nowait(json.dumps(result))
                except Exception:
                    pass

            except Exception as e:
                self.status = 'aborted'
                self._save_results()
                logger.error(f"Error in arbitrage task: {e}")
                break

            time.sleep(freq)
