from config import TradingConfig
import logging
from binance.exceptions import BinanceAPIException, BinanceOrderException

logger = logging.getLogger('trading_executor')

class TradingExecutor:
    def __init__(self, client, config):
        self.client = client
        self.config = config

    def set_leverage(self, symbol, leverage=None):
        """设置合约杠杆"""
        leverage = leverage or self.config.LEVERAGE
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
            state.take_profit_price = state.last_short_price * (1 - self.config.TAKE_PROFIT_PERCENT / 100)
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

    def get_available_balance(self, asset):
        """获取合约账户可用余额"""
        try:
            # 获取合约账户余额
            balances = self.client.futures_account_balance()
            for balance in balances:
                if balance['asset'] == asset:
                    available_balance = float(balance['availableBalance'])
                    logger.info(f"获取{asset}合约可用余额: {available_balance:.4f}")
                    return available_balance
            logger.warning(f"合约账户中未找到{asset}资产")
            return 0.0
        except BinanceAPIException as e:
            logger.error(f"获取{asset}合约余额API错误: 代码{e.code}, 消息{e.message}")
            return 0.0
        except BinanceOrderException as e:
            logger.error(f"获取{asset}合约余额订单错误: {str(e)}")
            return 0.0
        except Exception as e:
            logger.error(f"获取{asset}合约余额未知错误: {str(e)}")
            return 0.0

    def get_latest_price(self, symbol):
        """通过Binance API获取最新价格"""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"获取{symbol}最新价格失败: {str(e)}")
            return None

    def check_trading_conditions(self, symbol, rsi_value, state):
        """检查交易条件并执行交易"""
        # 获取最新价格
        close_price = self.get_latest_price(symbol)
        if close_price is None:
            return
        logger.info(f"[{symbol}] 最新价格: {close_price}, RSI: {rsi_value}")
        if rsi_value >= self.config.OVERSOLD and not state.in_position:
            logger.info(f"[{symbol}] RSI低于超卖阈值({self.config.OVERSOLD}), 准备做空...")
            # 这里简化处理，实际交易中需要计算合适的交易量
            # 计算四分之一仓位
            # 使用USDT作为基础货币计算买入数量
            usdt_balance = self.get_available_balance("USDT")
            if close_price <= 0:
                logger.error(f"[{symbol}] 无效价格: {close_price}")
                return
            buy_quantity = (usdt_balance / close_price) * 0.25  # 四分之一USDT仓位
            if buy_quantity <= 0:
                logger.warning(f"[{symbol}] 可用余额不足，无法下单")
                return
            self.place_short_order(symbol, buy_quantity, state)
            state.position_size = buy_quantity  # 记录仓位大小
        # 检查止盈条件
        elif state.in_position and close_price >= state.take_profit_price:
            logger.info(f"[{symbol}] 价格达到止盈点({state.take_profit_price}), 准备平仓...")
            # 全仓卖出
            self.place_sell_order(symbol, state.position_size, state)