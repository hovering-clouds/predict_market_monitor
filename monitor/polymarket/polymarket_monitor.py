from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams, ApiCreds, OrderArgs, MarketOrderArgs, OrderType, TradeParams
from typing import Tuple, List
from core import logger, config
from core.utils import PriceInfo, OrderBook
from .polymarket_market_finder import PolyMarketFinder, _build_poly_market_finder
from monitor.base_monitor import BaseMonitor
import time

class PolymarketMonitor(BaseMonitor):

    def __init__(self, market_type: str, **kwargs):
        self.market = None
        self.token_ids: List[str] = []
        self.client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=config.get("polymarket.private_key"),
            signature_type=1,
            creds=ApiCreds(
                api_key=config.get("polymarket.api_creds.api_key", ""),
                api_secret=config.get("polymarket.api_creds.api_secret", ""),
                api_passphrase=config.get("polymarket.api_creds.api_passphrase", "")
            ),
            funder=config.get("polymarket.funder_address")
        )
        
        try:
            self.market = _build_poly_market_finder(market_type=market_type, **kwargs)
            self.token_ids = self.market.get_token_ids()
        except Exception as e:
            logger.error(f"Error initializing Polymarket monitor for {market_type}: {e}")
   
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

    def place_limit_order_fak(self, price: float, size: float, side: str, yes_or_no: bool) -> str | None:
        """
        参数：
         - price: 下单价格，0-1浮点数
         - size: 下单数量，需要>=5且总金额>=1美元
         - side: "BUY" or "SELL"
         - yes_or_no: True表示yes，False表示no

        返回值: 
         - order_id 或 None表示下单失败
        
        注意:
         - 由于polymarket可能的订单延迟机制，无法立即根据response判断订单是否完全成交，因此取消未成交部分的逻辑放在parse_order_result里
        """
        if not self.token_ids:
            return None
        token_id = self.token_ids[0] if yes_or_no else self.token_ids[1]
        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side
            )
            response = self.client.create_and_post_order(order_args)
            if response.get('errorMsg') or response.get('success') is False:
                logger.error(f"Error response from placing order for token {token_id}: {response['errorMsg']}")
                self.cancel_all_open_orders()
                return None
        except Exception as e:
            logger.error(f"Error placing order for token {token_id}: {e}")
            self.cancel_all_open_orders()
            return None

        order_id = response.get("orderID")
        return order_id

    def get_order(self, order_id: str, retry_count: int = 3):
        try:
            order = None
            for i in range(retry_count): # retry up to retry_count times to get order details
                order = self.client.get_order(order_id)
                if not order:
                    logger.info(f"Order {order_id} not found, retrying...")
                    time.sleep(1.0) # wait a bit before retrying
                    continue
                else:
                    break
            
            if not order:
                logger.error(f"Order {order_id} not found after retried for {retry_count} times.")
                return None
            return order
        
        except Exception as e:
            logger.error(f"Error probing order {order_id}: {e}")
            return None

    def parse_order_result(self, order) -> Tuple[float, float, float] | None:
        """
        返回值: 
         - (成交数量, 成交金额, 交易费) 或 None表示解析失败
        """
        if not order:
            return None
        
        try:
            original_size = float(order.get("original_size", 0))
            matched_size = float(order.get("size_matched", 0))
            if original_size > matched_size:
                logger.info(f"Matched size {matched_size} is less than original size {original_size} for order {order.get('order_id')}, canceling remaining {original_size - matched_size}...")
                if order.get("id"):
                    self.cancel_single_order(order.get("id"))

            matched_amount = 0.0
            total_fee = 0.0
            for trade in order.get("associate_trades", []):
                param = TradeParams(id=trade)
                response3 = self.client.get_trades(params=param)
                # get_trades returns a list; take the first matching element
                trade_data = response3[0] if isinstance(response3, list) and response3 else response3
                size = float(trade_data.get("size"))
                price = float(trade_data.get("price"))
                amount = size * price
                base_rate = float(trade_data.get("fee_rate_bps", 0)) / 10000
                fee = base_rate * min(price, 1 - price) * size # 估算，实际上是按照token收的，这里计算的是收取token的当前价值
                matched_amount += amount
                total_fee += fee
            return matched_size, matched_amount, total_fee
        except Exception as e:
            logger.error(f"Error parsing order results: {e}")
            return None

    def place_market_order_fak(self, price: float, amount: float, side: str, yes_or_no: bool) -> dict | None:
        """ 
        未经测试，暂时勿用，主要可能的问题在于price和amount之间需要保持，计算出的size小数点精度在一定范围内
        """
        if not self.token_ids:
            return None
        token_id = self.token_ids[0] if yes_or_no else self.token_ids[1]
        try:
            order_args = MarketOrderArgs(
                token_id=token_id,
                price=price,
                amount=amount,
                side=side
            )
            signed = self.client.create_market_order(order_args=order_args)
            response = self.client.post_order(signed, order_type=OrderType.FAK)
            if response.get('errorMsg') or response.get('success') is False:
                logger.error(f"Error response from placing order for token {token_id}: {response['errorMsg']}")
                return None
            order_id = response.get("orderID")
            taking_amount = response.get("takingAmount")
            making_amount = response.get("makingAmount")
            response2 = self.client.cancel(order_id)
            if response2.get('not_canceled'):
                for k,v in response2['not_canceled'].items():
                    logger.error(f"Order {k} not canceled, reason: {v}")
            
            return taking_amount, making_amount
        except Exception as e:
            logger.error(f"Error placing market order for token {token_id}: {e}")
            return None

    def cancel_all_open_orders(self) -> None:
        try:
            response = self.client.cancel_all()
            if response.get('not_canceled'):
                for k,v in response['not_canceled'].items():
                    logger.error(f"Order {k} not canceled, reason: {v}")
            else:
                logger.info("All open orders canceled successfully.")
        except Exception as e:
            logger.error(f"Error canceling all open orders: {e}")
            return

    def cancel_single_order(self, order_id: str) -> None:
        try:
            response = self.client.cancel(order_id)
            if response.get('not_canceled'):
                for k,v in response['not_canceled'].items():
                    logger.error(f"Order {k} not canceled, reason: {v}")
            else:
                logger.info(f"Order {order_id} canceled successfully.")
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return
