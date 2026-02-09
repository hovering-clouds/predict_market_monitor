from typing import Tuple, List
from core import logger
from core.utils import PriceInfo, OrderBook
from .limitless_market_finder import LimitlessMarketFinder, _build_limitless_market_finder
from monitor.base_monitor import BaseMonitor
import requests


class LimitlessMonitor(BaseMonitor):

    BASE_URL = "https://api.limitless.exchange"

    def __init__(self, market_type: str, **kwargs):
        self.market = None
        self.session = requests.Session()
        
        try:
            self.market = _build_limitless_market_finder(market_type=market_type, **kwargs)
        except Exception as e:
            logger.error(f"Error initializing Limitless monitor for {market_type}: {e}")

        
    def get_yes_orderbook(self) -> OrderBook | None:
        if not self.market:
            return None
        
        slug = self.market.get_slug()
        url = f"{self.BASE_URL}/markets/{slug}/orderbook"
        response = self.session.get(url)
        if response.status_code != 200:
            logger.error(f"Failed to fetch orderbook for slug {slug}: {response.status_code}")
            return None

        try:
            book = response.json()
        except requests.exceptions.JSONDecodeError as e:
            logger.error(f"Error decoding JSON response for slug {slug}: {e}")
            return None
        
        asks = []
        bids = []
        if "asks" not in book or "bids" not in book:
            logger.error(f"Malformed orderbook data for slug {slug}: {book}")
            return None
        
        try:
            for obs in book["asks"]:
                asks.append(PriceInfo(value=obs["price"], quantity=obs["size"]/1e6))
            for obs in book["bids"]:
                bids.append(PriceInfo(value=obs["price"], quantity=obs["size"]/1e6))
        except Exception as e:
            logger.error(f"Error processing orderbook data {book} for slug {slug}: {e}")
            return None
        
        return OrderBook(bids=bids, asks=asks)
    
