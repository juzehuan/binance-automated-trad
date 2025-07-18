import pandas as pd
import numpy as np
from config import Config
import logging

logger = logging.getLogger('data_processor')

class DataProcessor:
    @staticmethod
    def calculate_rsi(data, period=14, return_all=False):
        """计算RSI指标"""
        close_prices = data['close']
        deltas = close_prices.diff()

        # 分离涨跌幅
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)

        # 计算平均收益和损失（使用指数移动平均）
        avg_gain = gains.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = losses.ewm(alpha=1/period, min_periods=period).mean()

        # 避免除以零
        if avg_loss.sum() == 0:
            return 100 if return_all else 100

        # 计算RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        if return_all:
            return rsi
        else:
            return rsi.iloc[-1] if not rsi.empty else 50

    @staticmethod
    def process_kline_data(kline_data, state):
        """处理K线数据并更新交易状态"""
        try:
            # 提取K线数据
            symbol = kline_data['symbol']
            close_price = float(kline_data['close'])
            timestamp = pd.to_datetime(kline_data['event_time'], unit='ms')

            # 添加到K线列表
            # 如果是新K线，添加新记录；否则更新最后一条记录
            if not state.klines or state.klines[-1]['timestamp'] != timestamp:
                state.klines.append({
                    'timestamp': timestamp,
                    'close': close_price
                })
            else:
                state.klines[-1]['close'] = close_price

            # 保持K线列表长度
            max_klines = Config.RSI_PERIOD + 10
            if len(state.klines) > max_klines:
                state.klines.pop(0)

            # 当有足够数据时计算RSI
            if len(state.klines) >= Config.RSI_PERIOD:
                df = pd.DataFrame(state.klines)
                rsi_value = DataProcessor.calculate_rsi(df, Config.RSI_PERIOD)
                logger.info(f"[{symbol}] 当前RSI: {rsi_value:.2f}, 价格: {close_price}")
                return df, rsi_value
            return None, None
        except Exception as e:
            logger.error(f"处理K线数据错误: {e}")
            return None, None