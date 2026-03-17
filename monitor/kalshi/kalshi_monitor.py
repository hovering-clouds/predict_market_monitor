from kalshi_python_sync import Configuration, KalshiClient, GetMarketOrderbookResponse, Order
from typing import Tuple, List, Any, Dict, Optional
from core import logger, config
from core.utils import PriceInfo, OrderBook
from pydantic import validate_call, StrictStr
from .kalshi_market_finder import KalshiMarketFinder, _build_kalshi_market_finder
from monitor.base_monitor import BaseMonitor
import json
import types

class KalshiMonitor(BaseMonitor):

    def __init__(self, market_type: str, **kwargs):
        # Configure the client
        self.config = Configuration(
            host="https://api.elections.kalshi.com/trade-api/v2",
        )
        if config.get('kalshi.api_key_id') and config.get('kalshi.private_key'):
            self.config.api_key_id = config.get('kalshi.api_key_id')
            self.config.private_key_pem = config.get('kalshi.private_key')
        self.client = None
        try:
            self.client = KalshiClient(self.config)
            #self.patch_client_method()
            self.market = _build_kalshi_market_finder(market_type=market_type, **kwargs)
        except Exception as e:
            logger.error(f"Error initializing Kalshi monitor for {market_type}: {e}")
   
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
            for lst in reversed(response.orderbook_fp.yes_dollars):
                bids.append(PriceInfo(value=float(lst[0]), quantity=float(lst[1])))
            # no bids, price from lower to higher
            for lst in reversed(response.orderbook_fp.no_dollars):
                asks.append(PriceInfo(value=1-float(lst[0]), quantity=float(lst[1])))
        except Exception as e:
            logger.error(f"Error processing orderbook data for token {self.market.get_slug()}: {e}")
            return None
        
        return OrderBook(bids=bids, asks=asks)
    
    def place_limit_order_fak(self, price: float, size: float, side: str, yes_or_no: bool) -> Tuple[str, str] | None:
        """
        参数：
         - price: 下单价格，0-1浮点数
         - size: 下单数量，需要>=1且为整数
         - side: "BUY" or "SELL"
         - yes_or_no: True表示yes，False表示no

        返回值: 
         - order_id 或 None表示下单失败
        """
        if not self.market:
            return None

        try:
            response = self.client._orders_api.create_order(
                ticker=self.market.get_slug(),
                side="yes" if yes_or_no else "no",
                action=side.lower(),
                count=int(size),
                type="limit",
                yes_price_dollars=f"{price:.4f}" if yes_or_no else None,
                no_price_dollars=f"{price:.4f}" if not yes_or_no else None,
            )
        except Exception as e:
            logger.error(f"Error placing order for market {self.market.get_slug()}: {e}")
            self.cancel_all_open_orders()
            return None
        
        order_id = response.order.order_id
        remaining_count = float(response.order.remaining_count_fp)
        if remaining_count > 0:
            logger.info(f"Order {order_id} not fully filled, canceling remaining {remaining_count}...")
            self.cancel_single_order(order_id)
            return order_id, "cancelled"
        
        return order_id, "filled"
        
    def get_order(self, order_id: str, retry_count: int = 3):
        try:
            resp = self.client._orders_api.get_order(order_id)
            return resp.order
        except Exception as e:
            logger.error(f"Error fetching order {order_id}: {e}")
            return None

    def parse_order_result(self, order) -> Tuple[float, float, float] | None:
        if order is None:
            return None
        
        try:
            fill_count = float(order.fill_count_fp)
            taker_amount = float(order.taker_fill_cost_dollars)
            maker_amount = float(order.maker_fill_cost_dollars)
            taker_fee = float(order.taker_fees_dollars)
            maker_fee = float(order.maker_fees_dollars)
            return fill_count, taker_amount + maker_amount, taker_fee + maker_fee
        except Exception as e:
            logger.error(f"Error parsing order results: {e}")
            return None

    def cancel_all_open_orders(self):
        """取消所有未完成订单"""
        try:
            response = self.client._orders_api.get_orders(status="open")
            for order in response.orders:
                try:
                    self.client._orders_api.cancel_order(order.order_id)
                    logger.info(f"Canceled order {order.order_id} successfully.")
                except Exception as e:
                    logger.error(f"Error canceling order {order.order_id}: {e}")
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")

    def cancel_single_order(self, order_id: str):
        """取消单个订单"""
        try:
            self.client._orders_api.cancel_order(order_id)
            logger.info(f"Canceled order {order_id} successfully.")
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
