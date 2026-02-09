from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any
from core import logger




class KalshiMarketFinder(ABC):
    """Base class for finding markets on Kalshi via HTTP GET requests"""
        
    @abstractmethod
    def get_slug(self) -> str:
        """
        Return the market slug identifier.
        
        Returns:
            str: The slug for the specific market
        """
        pass


class ManualKalshiMarketFinder(KalshiMarketFinder):
    """Market finder for manually specified slug"""
    
    def __init__(self, slug: str):
        super().__init__()
        self.slug = slug
    
    def get_slug(self) -> str:
        return self.slug
    

## some helper functions

all_kalshi_markets = {
    "manual": ManualKalshiMarketFinder
}

def _build_kalshi_market_finder(market_type: str, **kwargs) -> KalshiMarketFinder:
    """
        Factory function to create KalshiMarketFinder instances.
        Args:
            market_type (str): The market type identifier.
            **kwargs: Additional arguments for specific KalshiMarketFinder constructors.
        Returns:
            KalshiMarketFinder: An instance of a KalshiMarketFinder subclass.
        Raises:
            ValueError: If the market type is not supported.
            TypeError: If the provided arguments do not match the constructor.
    """
    if market_type in all_kalshi_markets:
        return all_kalshi_markets[market_type](**kwargs)
    else:
        raise ValueError(f"KalshiMarket {market_type} not supported")
    
