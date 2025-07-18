import pandas as pd
import numpy as np
from config import Config
import logging

logger = logging.getLogger('data_processor')

class DataProcessor:
    @staticmethod
    def calculate_rsi(data, period=14):
        """使用Wilder's Smoothing方法计算RSI，返回包含RSI列的DataFrame"""
        close_prices = data['close']
        deltas = close_prices.diff()

        # 分离涨跌幅
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)

        # 计算平均收益和损失
        avg_gain = gains.rolling(window=period, min_periods=period).mean()
        avg_loss = losses.rolling(window=period, min_periods=period).mean()

        # 处理前n个数据点后的平均收益和损失
        for i in range(period, len(avg_gain)):
            avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gains.iloc[i]) / period
            avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + losses.iloc[i]) / period

        # 避免除以零
        avg_loss = avg_loss.replace(0, 0.0001)

        # 计算RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # 添加RSI列到原始DataFrame
        data['rsi'] = rsi
        return data

    @staticmethod
    def process_kline_data(kline_data, state):
        """处理K线数据并更新交易状态"""
        try:
            # 提取K线数据
            symbol = kline_data['k']['s']
            close_price = float(kline_data['k']['c'])
            timestamp = pd.to_datetime(kline_data['k']['t'], unit='ms')

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