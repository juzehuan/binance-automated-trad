from config import Config
import logging

logger = logging.getLogger('trading_executor')

class TradingExecutor:
    def __init__(self, client):
        self.client = client

    def set_leverage(self, symbol, leverage=None):
        """设置合约杠杆"""
        leverage = leverage or Config.LEVERAGE
        try:
            response = self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logger.info(f"[{symbol}] 设置杠杆成功: {response}")
            return response
        except Exception as e:
            logger.error(f"[{symbol}] 设置杠杆失败: {e}")
            return None

    def place_short_order(self, symbol, quantity, state):
        """下空单"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=self.client.SIDE_SELL,
                type=self.client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
            logger.info(f"[{symbol}] 做空订单已执行: {order}")
            state.in_position = True
            state.last_short_price = float(order['fills'][0]['price'])
            # 设置止盈价格（做空时止盈价格低于开仓价格）
            state.take_profit_price = state.last_short_price * (1 - Config.TAKE_PROFIT_PERCENT / 100)
            logger.info(f"[{symbol}] 设置止盈价格: {state.take_profit_price}")
            return order
        except Exception as e:
            logger.error(f"[{symbol}] 做空订单执行失败: {e}")
            return None

    def place_sell_order(self, symbol, quantity, state):
        """平空单"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=self.client.SIDE_SELL,
                type=self.client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
            logger.info(f"[{symbol}] 卖出订单已执行: {order}")
            state.in_position = False
            state.last_short_price = 0
            state.take_profit_price = 0
            return order
        except Exception as e:
            logger.error(f"[{symbol}] 卖出订单执行失败: {e}")
            return None

    def check_trading_conditions(self, symbol, close_price, rsi_value, state):
        """检查交易条件并执行交易"""
        # 检查做空条件
        if rsi_value < Config.OVERSOLD and not state.in_position:
            logger.info(f"[{symbol}] RSI低于超卖阈值({Config.OVERSOLD}), 准备做空...")
            # 这里简化处理，实际交易中需要计算合适的交易量
            self.place_short_order(symbol, 0.001, state)
        # 检查止盈条件
        elif state.in_position and close_price >= state.take_profit_price:
            logger.info(f"[{symbol}] 价格达到止盈点({state.take_profit_price}), 准备平仓...")
            self.place_sell_order(symbol, 0.001, state)