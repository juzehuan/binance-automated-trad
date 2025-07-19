from config import TradingConfig
import logging
import time
from binance.exceptions import BinanceAPIException, BinanceOrderException

logger = logging.getLogger('trading_system')

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
        """下空单（支持模拟模式）"""
        if self.config.SIMULATION_MODE:

            # 模拟做空订单
            close_price = self.get_latest_price(symbol)
            if close_price is None:
                logger.error(f"[{symbol}] 模拟下单失败: 无法获取最新价格")
                return None

            # 模拟订单信息
            simulated_order = {
                'symbol': symbol,
                'side': 'SELL',
                'type': 'MARKET',
                'quantity': quantity,
                'fills': [{'price': close_price, 'qty': quantity}]
            }


            state.last_short_price = close_price
            # 设置止盈价格（做空时止盈价格低于开仓价格）
            # 做空盈利目标价格 = 开仓价 × (1 - 目标盈利百分比)，与用户提供的计算公式一致
            state.take_profit_price = close_price * (1 - self.config.TAKE_PROFIT_PERCENT / 100)
            profit_percent = self.config.TAKE_PROFIT_PERCENT

            logger.info(f"[{symbol}] [模拟] 做空订单已执行: 数量={quantity}, 开仓价格={close_price}, 止盈价格={state.take_profit_price}, 目标获利={profit_percent}%")
            logger.info(f"[{symbol}] [模拟] 订单详情: {simulated_order}")
            return simulated_order

        # 真实交易逻辑
        try:

            order = self.client.futures_create_order(
                symbol=symbol,
                side=self.client.SIDE_SELL,
                type=self.client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
            logger.info(f"[{symbol}] 做空订单已执行: 数量={quantity}, 开仓价格={state.last_short_price}, 止盈价格={state.take_profit_price}, 目标获利={self.config.TAKE_PROFIT_PERCENT}%")
            logger.info(f"[{symbol}] 订单详情: {order}")
            with state.lock:
                state.in_position = True
                state.last_short_price = float(order['fills'][0]['price'])
                # 设置止盈价格（做空时止盈价格低于开仓价格）
                # 做空盈利目标价格 = 开仓价 × (1 - 目标盈利百分比)，与用户提供的计算公式一致
                state.take_profit_price = state.last_short_price * (1 - self.config.TAKE_PROFIT_PERCENT / 100)
            logger.info(f"[{symbol}] 设置止盈价格: {state.take_profit_price}")
            return order
        except Exception as e:
            logger.error(f"[{symbol}] 做空订单执行失败: {e}")
            return None


    def close_short_order(self, symbol, quantity, state):
        """平空单（支持模拟平仓）"""
        if self.config.SIMULATION_MODE:
            # 模拟平空订单（买入）
            with state.lock:
                state.is_closing_position = True
            close_price = self.get_latest_price(symbol)
            if close_price is None:
                with state.lock:
                    state.is_closing_position = False
                logger.error(f"[{symbol}] 模拟平仓失败: 无法获取最新价格")
                return None

            # 计算利润（做空时利润 = (开仓价 - 平仓价) * 数量）
            profit = (state.last_short_price - close_price) * quantity
            profit_percent = ((state.last_short_price - close_price) / state.last_short_price) * 100

            # 模拟订单信息
            simulated_order = {
                'symbol': symbol,
                'side': 'BUY',
                'type': 'MARKET',
                'quantity': quantity,
                'fills': [{'price': close_price, 'qty': quantity}]
            }

            with state.lock:
                    state.in_position = False
                    state.is_closing_position = False
            logger.info(f"[{symbol}] 持仓状态更新为: {state.in_position}")
            state.last_short_price = 0
            state.take_profit_price = 0
            logger.info(f"[{symbol}] [模拟] 平仓订单已执行: 数量={quantity}, 平仓价格={close_price}, 开仓价格={state.last_short_price}, 获利金额={profit:.2f} USDT, 获利百分比={profit_percent:.2f}%")
            logger.info(f"[{symbol}] [模拟] 订单详情: {simulated_order}")
            return simulated_order
        with state.lock:
                if state.in_position:
                    # 真实交易平空单（买入）
                    try:
                        with state.lock:
                            state.is_closing_position = True

                        order = self.client.futures_create_order(
                            symbol=symbol,
                            side=self.client.SIDE_BUY,
                            type=self.client.ORDER_TYPE_MARKET,
                            quantity=quantity
                        )

                        with state.lock:
                            state.in_position = False
                            state.last_short_price = 0
                            state.take_profit_price = 0
                            state.is_closing_position = False

                        logger.info(f"[{symbol}] 平空订单已执行: 数量={quantity}, 平仓价格={float(order['fills'][0]['price'])}, 开仓价格={state.last_short_price}")
                        logger.info(f"[{symbol}] 订单详情: {order}")
                        return order
                    except Exception as e:
                        with state.lock:
                            state.is_closing_position = False
                        logger.error(f"[{symbol}] 平空订单执行失败: {e}")
                        return None


    def get_available_balance(self, asset):
        """获取合约账户可用余额（支持模拟模式）"""
        if self.config.SIMULATION_MODE and asset == 'USDT':
            logger.info(f"[模拟] 获取{asset}可用余额: {self.config.SIMULATED_BALANCE:.4f}")
            return self.config.SIMULATED_BALANCE
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
        # 获取最新价格
        close_price = self.get_latest_price(symbol)
        if close_price is None:
            return
        logger.info(f"[{symbol}] 最新价格: {close_price}, RSI: {rsi_value}")
        # 统一交易条件判断（模拟与真实交易共用同一套逻辑）
        # 先获取余额，减少锁持有时间
        usdt_balance = self.get_available_balance("USDT")

        with state.lock:
            logger.debug(f"[{symbol}] 锁获取成功，当前持仓状态: {state.in_position}")
            if not state.in_position and rsi_value >= self.config.OVERBOUGHT and not state.is_closing_position:
                logger.info(f"[{symbol}] RSI大于等于超买阈值({self.config.OVERBOUGHT}), 执行做空操作")
                state.in_position = True  # 立即锁定仓位
                logger.info(f"[{symbol}] 持仓状态更新为: {state.in_position}")

                if close_price <= 0:
                    logger.error(f"[{symbol}] 无效价格: {close_price}")
                    state.in_position = False  # 重置状态
                    logger.debug(f"[{symbol}] 释放锁，持仓状态重置为: {state.in_position}")
                    return

                sell_quantity = (usdt_balance / close_price) * 0.25  # 四分之一USDT仓位
                if sell_quantity > 0:
                    order_result = self.place_short_order(symbol, sell_quantity, state)
                    if order_result is not None:
                        state.position_size = sell_quantity  # 记录仓位大小

                    else:
                        state.in_position = False  # 订单失败，重置状态
                        logger.error(f"[{symbol}] 下单失败，重置持仓状态")
                else:
                    state.in_position = False  # 重置状态
            else:
                # RSI小于等于超卖阈值或达到止盈价格时平仓
                if rsi_value <= self.config.OVERSOLD or close_price <= state.take_profit_price:
                    if rsi_value <= self.config.OVERSOLD:
                        logger.info(f"[{symbol}] RSI小于等于超卖阈值({self.config.OVERSOLD}), 执行平仓操作")
                    else:
                        logger.info(f"[{symbol}] 价格达到止盈点({state.take_profit_price}), 准备平仓...")
                    if hasattr(state, 'position_size') and state.position_size > 0:
                          with state.lock:
                              state.is_closing_position = True
                          self.close_short_order(symbol, state.position_size, state)
                          with state.lock:
                              state.position_size = 0
                              state.is_closing_position = False

            logger.debug(f"[{symbol}] 释放锁，当前持仓状态: {state.in_position}")