from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any
from core import logger

import requests
import pytz



class PolyMarketFinder(ABC):
    """Base class for finding markets on Polymarket via HTTP GET requests"""
    
    BASE_URL = "https://clob.polymarket.com"
    
    def __init__(self):
        self.session = requests.Session()
    
    @abstractmethod
    def get_slug(self) -> str:
        """
        Return the market slug identifier.
        
        Returns:
            str: The slug for the specific market
        """
        pass
    
    def get_token_ids(self) -> List[str]:
        """
        Return the token IDs for this market.
        
        Returns:
            List[str]: List of token IDs
        """
        slug = self.get_slug()
        url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
        response = self.session.get(url)
        if response.status_code != 200:
            logger.error(f"Failed to fetch market info for slug {slug}: {response.status_code}")
            return []
        
        tokens = response.json().get("clobTokenIds")
        if not tokens:
            logger.error(f"No token IDs found for slug {slug}")
            return []
        
        # 解析token IDs
        tokens = tokens[1:-1]  # 去掉前后的方括号
        lst = tokens.split(', ')
        return [idstr[1:-1] for idstr in lst]


class BtcUpOrDown1hPolyMarketFinder(PolyMarketFinder):
    """Market finder for BTC up or down 1-hour markets"""
    
    def get_slug(self) -> str:
        eastern_time = datetime.now(pytz.timezone('US/Eastern'))
        # 月份映射（确保小写）
        months = {
            1: 'january', 2: 'february', 3: 'march', 4: 'april',
            5: 'may', 6: 'june', 7: 'july', 8: 'august',
            9: 'september', 10: 'october', 11: 'november', 12: 'december'
        }
        month = months[eastern_time.month]
        day = eastern_time.day
        # 处理12小时制时间
        hour_12 = eastern_time.hour % 12
        if hour_12 == 0:
            hour_12 = 12
        # 确定上午/下午
        period = 'am' if eastern_time.hour < 12 else 'pm'
        
        return f"bitcoin-up-or-down-{month}-{day}-{hour_12}{period}-et"
    

class ManualPolyMarketFinder(PolyMarketFinder):
    """Market finder for manually specified slug"""
    
    def __init__(self, slug: str):
        super().__init__()
        self.slug = slug
    
    def get_slug(self) -> str:
        return self.slug
    

## some helper functions

all_poly_markets = {
    "btc_up_down_1h": BtcUpOrDown1hPolyMarketFinder,
    "manual": ManualPolyMarketFinder
}

def _build_poly_market_finder(market: str, **kwargs) -> PolyMarketFinder:
    """
        Factory function to create PolyMarketFinder instances.
        Args:
            market (str): The market type identifier.
            **kwargs: Additional arguments for specific PolyMarketFinder constructors.
        Returns:
            PolyMarketFinder: An instance of a PolyMarketFinder subclass.
        Raises:
            ValueError: If the market type is not supported.
            TypeError: If the provided arguments do not match the constructor.
    """
    if market in all_poly_markets:
        return all_poly_markets[market](**kwargs)
    else:
        raise ValueError(f"PolyMarket {market} not supported")
    
