from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Tuple, List, Optional

from core import logger
from core.utils import OrderBook


class BaseMonitor(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def get_yes_orderbook(self) -> OrderBook | None:
        raise NotImplementedError

    @abstractmethod
    def place_limit_order_fak(self, price: float, size: float, side: str, yes_or_no: bool) -> Tuple[float, float, float] | None:
        raise NotImplementedError
    
    @abstractmethod
    def cancel_all_open_orders(self):
        raise NotImplementedError


def build_kalshi_monitor(market_type: str, **kwargs) -> Optional[BaseMonitor]:
    """构建 Kalshi Monitor 实例"""
    try:
        from .kalshi.kalshi_monitor import KalshiMonitor
        return KalshiMonitor(market_type=market_type, **kwargs)
    except Exception as e:
        logger.error(f"Error building Kalshi monitor for {market_type}: {e}")
        return None


def build_limitless_monitor(market_type: str, **kwargs) -> Optional[BaseMonitor]:
    """构建 Limitless Monitor 实例"""
    try:
        from .limitless.limitless_monitor import LimitlessMonitor
        return LimitlessMonitor(market_type=market_type, **kwargs)
    except Exception as e:
        logger.error(f"Error building Limitless monitor for {market_type}: {e}")
        return None


def build_polymarket_monitor(market_type: str, **kwargs) -> Optional[BaseMonitor]:
    """构建 Polymarket Monitor 实例"""
    try:
        from .polymarket.polymarket_monitor import PolymarketMonitor
        return PolymarketMonitor(market_type=market_type, **kwargs)
    except Exception as e:
        logger.error(f"Error building Polymarket monitor for {market_type}: {e}")
        return None


# Monitor 类型到 builder 函数的映射
MONITOR_BUILDERS = {
    'kalshi': build_kalshi_monitor,
    'limitless': build_limitless_monitor,
    'polymarket': build_polymarket_monitor,
}


def build_monitor(monitor_type: str, market_type: str, **kwargs) -> Optional[BaseMonitor]:
    """根据类型构建 Monitor 实例"""
    builder = MONITOR_BUILDERS.get(monitor_type)
    if builder:
        return builder(market_type=market_type, **kwargs)
    logger.error(f"Unknown monitor type: {monitor_type}")
    return None

