from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams
from typing import Tuple, List
from core import logger
from core.utils import PriceInfo, OrderBook
from .polymarket_market_finder import PolyMarketFinder, _build_poly_market_finder

class PolymarketMonitor:

    def __init__(self, market: str, **kwargs):
        self.market = None
        self.token_ids: List[str] = []
        self.client = ClobClient("https://clob.polymarket.com")
        
        try:
            self.market = _build_poly_market_finder(market=market, **kwargs)
            self.token_ids = self.market.get_token_ids()
        except Exception as e:
            logger.error(f"Error initializing market finder and tokens for {market}: {e}")
   
    def get_all_orderbooks(self) -> List[OrderBook]:
        if not self.token_ids:
            return []
        
        try:
            params = [BookParams(token_id=token_id) for token_id in self.token_ids]
            books = self.client.get_order_books(params)
            result = []
            for book in books:
                asks = []
                bids = []
                for obs in reversed(book.asks):
                    asks.append(PriceInfo(value=float(obs.price), quantity=float(obs.size)))
                for obs in reversed(book.bids):
                    bids.append(PriceInfo(value=float(obs.price), quantity=float(obs.size)))
                orderbook = OrderBook(bids=bids, asks=asks)
                result.append(orderbook)
        except Exception as e:
            logger.error(f"Error fetching orderbooks for tokens {self.token_ids}: {e}")
            return []
        
        return result
    
    def get_yes_orderbook(self) -> OrderBook | None:
        if not self.token_ids:
            return None
        
        try:
            book = self.client.get_order_book(self.token_ids[0])
            asks = []
            bids = []
            for obs in reversed(book.asks):
                asks.append(PriceInfo(value=float(obs.price), quantity=float(obs.size)))
            for obs in reversed(book.bids):
                bids.append(PriceInfo(value=float(obs.price), quantity=float(obs.size)))
        except Exception as e:
            logger.error(f"Error processing orderbook data for token {self.token_ids[0]}: {e}")
            return None
        
        return OrderBook(bids=bids, asks=asks)
