from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any
from core import logger




class LimitlessMarketFinder(ABC):
    """Base class for finding markets on Limitless via HTTP GET requests"""
        
    @abstractmethod
    def get_slug(self) -> str:
        """
        Return the market slug identifier.
        
        Returns:
            str: The slug for the specific market
        """
        pass


class ManualLimitlessMarketFinder(LimitlessMarketFinder):
    """Market finder for manually specified slug"""
    
    def __init__(self, slug: str):
        super().__init__()
        self.slug = slug
    
    def get_slug(self) -> str:
        return self.slug
    

## some helper functions

all_limitless_markets = {
    "manual": ManualLimitlessMarketFinder
}

def _build_limitless_market_finder(market: str, **kwargs) -> LimitlessMarketFinder:
    """
        Factory function to create LimitlessMarketFinder instances.
        Args:
            market (str): The market type identifier.
            **kwargs: Additional arguments for specific LimitlessMarketFinder constructors.
        Returns:
            LimitlessMarketFinder: An instance of a LimitlessMarketFinder subclass.
        Raises:
            ValueError: If the market type is not supported.
            TypeError: If the provided arguments do not match the constructor.
    """
    if market in all_limitless_markets:
        return all_limitless_markets[market](**kwargs)
    else:
        raise ValueError(f"LimitlessMarket {market} not supported")
    
