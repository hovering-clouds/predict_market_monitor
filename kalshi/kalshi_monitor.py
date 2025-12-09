from kalshi_python_sync import Configuration, KalshiClient, GetMarketOrderbookResponse
from typing import Tuple, List, Any, Dict, Optional
from core import logger, config
from core.utils import PriceInfo, OrderBook
from pydantic import validate_call, StrictStr
from .kalshi_market_finder import KalshiMarketFinder, _build_kalshi_market_finder
import json
import types

class KalshiMonitor:

    def __init__(self, market_type: str, **kwargs):
        # Configure the client
        self.config = Configuration(
            host="https://api.elections.kalshi.com/trade-api/v2",
        )
        if config.get('kalshi.api_key_id') and config.get('kalshi.private_key'):
            self.config.api_key_id = config.get('kalshi.api_key_id')
            self.config.private_key_pem = config.get('kalshi.private_key')
        try:
            self.client = KalshiClient(self.config)
            self.patch_client_method()
            self.market = _build_kalshi_market_finder(market_type=market_type, **kwargs)
        except Exception as e:
            logger.error(f"Error initializing market finder and tokens for {market_type}: {e}")
   
    def patch_client_method(self):
        """修复self.client中get_market_orderbook方法中错误的数据类型问题"""
        
        @validate_call
        def patch_get_market_orderbook(
            self,
            ticker: StrictStr,
            depth: Any = None,
        ) -> GetMarketOrderbookResponse:

            _param = self._get_market_orderbook_serialize(
                ticker=ticker,
                depth=depth,
                _request_auth=None,
                _content_type=None,
                _headers=None,
                _host_index=0
            )

            _response_types_map: Dict[str, Optional[str]] = {
                '200': "GetMarketOrderbookResponse",
                '401': "ErrorResponse",
                '404': "ErrorResponse",
                '500': "ErrorResponse",
            }
            response_data = self.api_client.call_api(
                *_param,
                _request_timeout=None,
            )
            # 修复数据类型
            byte_data = response_data.response.data
            json_data = json.loads(byte_data.decode('utf-8'))
            if json_data.get('orderbook', {}).get('yes_dollars') is not None:
                json_data['orderbook']['yes_dollars'] = [[lst[0], str(lst[1])] for lst in json_data['orderbook']['yes_dollars']]
            if json_data.get('orderbook', {}).get('no_dollars') is not None:
                json_data['orderbook']['no_dollars'] = [[lst[0], str(lst[1])] for lst in json_data['orderbook']['no_dollars']]
            response_data.data = json.dumps(json_data).encode('utf-8')
            return self.api_client.response_deserialize(
                response_data=response_data,
                response_types_map=_response_types_map,
            ).data
         
        # 替换客户端的方法
        self.client._market_api.get_market_orderbook = types.MethodType(patch_get_market_orderbook, self.client._market_api)
    
    def get_yes_orderbook(self) -> OrderBook | None:
        if not self.market:
            return None
        
        try:
            response: GetMarketOrderbookResponse = self.client.get_market_orderbook(self.market.get_slug())
            asks = []
            bids = []
            # yes bids, price from lower to higher
            for lst in reversed(response.orderbook.yes_dollars):
                bids.append(PriceInfo(value=float(lst[0]), quantity=float(lst[1])))
            # no bids, price from lower to higher
            for lst in reversed(response.orderbook.no_dollars):
                asks.append(PriceInfo(value=1-float(lst[0]), quantity=float(lst[1])))
        except Exception as e:
            logger.error(f"Error processing orderbook data for token {self.market.get_slug()}: {e}")
            return None
        
        return OrderBook(bids=bids, asks=asks)
