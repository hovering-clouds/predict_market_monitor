from typing import List, Tuple, Any
from dataclasses import dataclass, asdict


@dataclass
class PriceInfo:
    """
    value (float): value is the price between 0 and 1 (in $) \n
    quantity (float): in contract units, one unit stands for $value
    """
    value: float 
    quantity: float 

    def to_dict(self) -> dict:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'PriceInfo':
        return cls(**data)

class OrderBook:
    def __init__(self, bids: List[PriceInfo], asks: List[PriceInfo]):
        """Make sure bids and asks are sorted so that best price is first"""
        self.bids = bids  
        self.asks = asks

    def find_arbitrage_opportunity(self, other: 'OrderBook', min_spread: float) -> Tuple[float, float, float]:
        """
            Only consider BUY on itself and SELL on the other.\n
            Returns (buy price on itself, sell price on the other, arbitrage_quantity)
        """
        result = _match_arbitrage_orders(self.asks, other.bids, min_spread)
        if result:
            validi, validj, quantity = result
            buy_price = self.asks[validi].value
            sell_price = other.bids[validj].value
            return buy_price, sell_price, quantity
        return 0.0, 0.0, 0.0



def _match_arbitrage_orders(ob1_ask: List[PriceInfo], ob2_bid: List[PriceInfo], min_spread: float) -> Tuple[int, int, float] | None:
    """assume the best price is first in ask/bid list"""
    i = 0
    validi = None
    n = len(ob1_ask)
    j = 0
    validj = None
    m = len(ob2_bid)
    total_quant = 0.0
    while i < n and j < m:
        o1 = ob1_ask[i]
        o2 = ob2_bid[j]
        if o2.value - o1.value >= min_spread:
            validi = i
            validj = j
            if o1.quantity >= o2.quantity:
                total_quant+=o2.quantity
                o1.quantity-=o2.quantity
                j+=1
            else:
                total_quant+=o1.quantity
                o2.quantity-=o1.quantity
                i+=1
        else:
            break
    if validi is None or validj is None:
        return None
    else:
        return validi, validj, total_quant

