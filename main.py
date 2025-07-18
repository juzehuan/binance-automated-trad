from binance.client import Client

from dotenv import load_dotenv
import os
import logging
from logging.handlers import RotatingFileHandler
import signal
import time
import pandas as pd
import numpy as np
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import sys
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
# 设置matplotlib支持中文显示
plt.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "SimSun", "KaiTi"]
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

# 启用matplotlib交互模式
plt.ion()


# 配置日志系统
logger = logging.getLogger('trading_system')
logger.setLevel(logging.DEBUG)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 自定义过滤器：只允许包含买入或卖出关键词的日志
class TradingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return '买入' in message or '卖出' in message or '做空' or 'RSI' in message

# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
console_handler.addFilter(TradingFilter())

# 文件处理器 (支持轮转)
file_handler = RotatingFileHandler(
    'trading.log',
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,  # 保留5个备份文件
    encoding='utf-8'
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# 移除默认处理器
if logger.handlers:
    logger.handlers = []

# 添加处理器
logger.addHandler(console_handler)
logger.addHandler(file_handler)

load_dotenv()
api_key = os.getenv('TEST_API_KEY')
api_secret = os.getenv('TEST_API_SECRET')

proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890'
}



# 配置参数
class Config:
    SYMBOLS = ["CRVUSDT", "ACHUSDT", "ONDOUSDT"]   # 多个交易对
    INTERVAL = '15m'  # K线周期
    RSI_PERIOD = 6  # RSI计算周期
    OVERBOUGHT = 90  # 超买阈值
    OVERSOLD = 5  # 超卖阈值
    TESTNET = True  # 是否使用测试网络
    LEVERAGE = 10  # 合约杠杆倍数
    TAKE_PROFIT_PERCENT = 5  # 止盈百分比
    SHOW_CHARTS = True  # 是否显示图表

# 状态跟踪
class TradingState:
    def __init__(self):
        self.in_position = False
        self.last_short_price = 0
        self.klines = []
        self.take_profit_price = 0

# 为每个交易对创建独立的状态
state_map = {symbol: TradingState() for symbol in Config.SYMBOLS}

# 初始化变量
client=None # 客户端
refresh_interval = 2  # 刷新间隔(秒)，缩短以提高实时性

def set_leverage(symbol, leverage):
    global client
    try:
        response = client.futures_change_leverage(
            symbol=symbol,
            leverage=leverage
        )
        logger.info(f"设置杠杆成功: {response}")
        return response
    except Exception as e:
        logger.error(f"设置杠杆失败: {e}")
        return None

def calculate_rsi(data, period=14, return_all=False):
    close_prices = data['close']
    deltas = close_prices.diff()

    # 分离涨跌幅
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)

    # 计算平均收益和损失（使用指数移动平均）
    avg_gain = gains.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1/period, min_periods=period).mean()

    # 计算RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    if return_all:
        return rsi
    else:
        return rsi.iloc[-1] if not rsi.empty else 50

def place_short_order(symbol, quantity):
    global client, state
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity
        )
        logger.info(f"做空订单已执行: {order}")
        state.in_position = True
        state.last_short_price = float(order['fills'][0]['price'])
        # 设置止盈价格（做空时止盈价格低于开仓价格）
        state.take_profit_price = state.last_short_price * (1 - Config.TAKE_PROFIT_PERCENT / 100)
        logger.info(f"设置止盈价格: {state.take_profit_price}")
        return order
    except Exception as e:
        logger.error(f"做空订单执行失败: {e}")
        return None

def place_sell_order(symbol, quantity):
    global client, state
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity
        )
        logger.info(f"卖出订单已执行: {order}")
        state.in_position = False
        state.last_buy_price = 0
        state.take_profit_price = 0
        return order
    except Exception as e:
        logger.error(f"卖出订单执行失败: {e}")
        return None

def handle_socket_message(msg):
    global state
    if msg['e'] == 'kline':
        kline = msg['k']
        # 添加日志查看kline['x']的值
        logger.info(f"K线状态 - 闭合: {kline['x']}, 时间戳: {kline['T']}, 当前价格: {kline['c']}")
        # 提取K线数据(实时计算，不等待K线闭合)
        close_price = float(kline['c'])
        timestamp = pd.to_datetime(kline['T'], unit='ms')

        # 添加到K线列表
        # 如果是新K线（闭合后），添加新记录；否则更新最后一条记录
        if kline['x'] or not state.klines or state.klines[-1]['timestamp'] != timestamp:
            state.klines.append({
                'timestamp': timestamp,
                'close': close_price
            })
        else:
            state.klines[-1]['close'] = close_price

        print(len(state.klines))
        # 保持K线列表长度
        if len(state.klines) > Config.RSI_PERIOD + 10:
            state.klines.pop(0)

        # 当有足够数据时计算RSI
        if len(state.klines) >= Config.RSI_PERIOD:
            df = pd.DataFrame(state.klines)
            current_rsi = calculate_rsi(df, Config.RSI_PERIOD)
            status = "(K线闭合)" if kline['x'] else "(实时计算)"
            logger.info(f"当前RSI{status}: {current_rsi:.2f}, 价格: {close_price}")

            # 检查买入条件
            if current_rsi < Config.OVERSOLD and not state.in_position:
                logger.info(f"RSI低于超卖阈值({Config.OVERSOLD}), 准备买入...")
                # 这里简化处理，实际交易中需要计算合适的交易量
                place_short_order(Config.SYMBOL, 0.001)

            # 检查止盈条件
            elif state.in_position and close_price >= state.take_profit_price:
                logger.info(f"价格达到止盈点({state.take_profit_price}), 准备卖出...")
                place_sell_order(Config.SYMBOL, 0.001)

def fetch_kline_data(symbol, interval):
    global client
    try:
        # 获取最新的K线数据
        klines = client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=Config.RSI_PERIOD + 100  # 获取足够计算RSI的数据
        )
        # 转换为DataFrame
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['close'] = df['close'].astype(float)
        return df[['timestamp', 'close']]
    except Exception as e:
        logger.error(f"获取K线数据失败: {e}")
        return None



# 全局图形对象引用
chart_fig = None
chart_axes = []


def plot_multi_symbol_chart(symbol_data_map):
    global chart_fig, chart_axes
    num_symbols = len(symbol_data_map)

    # 如果图形不存在或交易对数量变化，创建新图形
    if chart_fig is None or len(chart_axes) != num_symbols * 2:
        chart_fig = plt.figure(figsize=(12, 4 * num_symbols))
        chart_axes = []
        gs = GridSpec(num_symbols * 2, 1, height_ratios=[3, 1] * num_symbols)

        for i in range(num_symbols):
            ax1 = chart_fig.add_subplot(gs[i*2])
            ax2 = chart_fig.add_subplot(gs[i*2+1])
            chart_axes.extend([ax1, ax2])
    else:
        # 清除现有图表
        for ax in chart_axes:
            ax.clear()

    # 为每个交易对绘制图表
    for i, (symbol, (df, rsi_values)) in enumerate(symbol_data_map.items()):
        ax1 = chart_axes[i*2]
        ax2 = chart_axes[i*2+1]

        # 绘制K线图
        ax1.plot(df['timestamp'], df['close'], 'b-', linewidth=2)
        ax1.set_title(f'{symbol} K线图')
        ax1.set_ylabel('价格')
        ax1.grid(True)

        # 绘制RSI
        ax2.plot(df['timestamp'], rsi_values, 'r-', linewidth=2)
        ax2.axhline(y=70, color='g', linestyle='--')
        ax2.axhline(y=30, color='g', linestyle='--')
        ax2.set_title(f'{symbol} RSI指标')
        ax2.set_xlabel('时间')
        ax2.set_ylabel('RSI值')
        ax2.set_ylim(0, 100)
        ax2.grid(True)

    # 调整布局并显示
    plt.tight_layout()
    # 在交互模式下不需要调用plt.show()
    plt.draw()
    plt.pause(0.01)  # 更短的暂停时间，提高响应性


def plot_kline_rsi(symbol, df, rsi_values):
    # 保持原有函数接口，以便兼容现有代码
    plot_multi_symbol_chart({symbol: (df, rsi_values)})

# 定义信号处理函数，用于优雅退出
def signal_handler(sig, frame):
    logger.info('程序已退出')
    exit(0)
def process_symbol(symbol):
    # 处理单个交易对的数据获取和分析
    df = fetch_kline_data(symbol, Config.INTERVAL)
    if df is not None and not df.empty:
        state = state_map[symbol]
        state.klines = df.to_dict('records')

        if len(state.klines) >= Config.RSI_PERIOD:
            # 计算所有RSI值
            rsi_series = calculate_rsi(df, Config.RSI_PERIOD, return_all=True)
            current_rsi = rsi_series.iloc[-1]
            close_price = df['close'].iloc[-1]
            logger.info(f"[{symbol}] 当前RSI: {current_rsi:.2f}, 价格: {close_price}")

            # 检查交易条件
            if current_rsi < Config.OVERSOLD and not state.in_position:
                logger.info(f"[{symbol}] RSI低于超卖阈值({Config.OVERSOLD}), 准备买入...")
                place_short_order(symbol, 0.001)
            elif state.in_position and close_price >= state.take_profit_price:
                logger.info(f"[{symbol}] 价格达到止盈点({state.take_profit_price}), 准备卖出...")
                place_sell_order(symbol, 0.001)

            return (df, rsi_series)
    return (None, None)

def main():
    global client

    # 解决时间戳不同步问题：启用自动时间同步
    client = Client(api_key, api_secret, {'proxies': proxies}, testnet=Config.TESTNET)
    client.ping()  # 测试连接并自动同步时间

    # 为每个交易对设置合约杠杆
    for symbol in Config.SYMBOLS:
        set_leverage(symbol, Config.LEVERAGE)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 保持程序运行
    logger.info('程序正在运行，按Ctrl+C退出...')
    # 创建线程池，最大线程数为交易对数量
    max_workers = min(len(Config.SYMBOLS), 10)  # 限制最大线程数为10
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            # 提交所有交易对的处理任务
            futures = {executor.submit(process_symbol, symbol): symbol for symbol in Config.SYMBOLS}

            # 收集所有交易对的数据
            symbol_data_map = {}
            for future in concurrent.futures.as_completed(futures):
                symbol = futures[future]
                try:
                    df, rsi_series = future.result()
                    if df is not None and rsi_series is not None:
                        symbol_data_map[symbol] = (df, rsi_series)
                except Exception as e:
                    logger.error(f"处理{symbol}时出错: {e}")

            # 如果有数据且配置允许，绘制多交易对图表
            if symbol_data_map and Config.SHOW_CHARTS:
                plot_multi_symbol_chart(symbol_data_map)

            # 等待指定的刷新间隔
            time.sleep(refresh_interval)

if __name__ == '__main__':
    main()
