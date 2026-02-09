from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Tuple, List

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