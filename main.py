from binance.client import Client
from binance import ThreadedWebsocketManager
from dotenv import load_dotenv
import os
import logging
import signal
import time
import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)

load_dotenv()
api_key = os.getenv('TEST_API_KEY')
api_secret = os.getenv('TEST_API_SECRET')

proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890'
}



# 配置参数
class Config:
    SYMBOL = 'ACHUSDT'  # 交易对
    INTERVAL = '15m'  # K线周期
    RSI_PERIOD = 6  # RSI计算周期
    OVERBOUGHT = 90  # 超买阈值
    OVERSOLD = 5  # 超卖阈值
    TESTNET = True  # 是否使用测试网络
    LEVERAGE = 10  # 合约杠杆倍数
    TAKE_PROFIT_PERCENT = 5  # 止盈百分比

# 状态跟踪
class TradingState:
    def __init__(self):
        self.in_position = False
        self.last_buy_price = 0
        self.klines = []
        self.take_profit_price = 0

state = TradingState()

# 初始化变量
twm=None # websocket
client=None # 客户端

def set_leverage(symbol, leverage):
    global client
    try:
        response = client.futures_change_leverage(
            symbol=symbol,
            leverage=leverage
        )
        logging.info(f"设置杠杆成功: {response}")
        return response
    except Exception as e:
        logging.error(f"设置杠杆失败: {e}")
        return None

def calculate_rsi(data, period=14):
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

    # 计算RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi.iloc[-1] if not rsi.empty else 50

def place_buy_order(symbol, quantity):
    global client, state
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity
        )
        logging.info(f"买入订单已执行: {order}")
        state.in_position = True
        state.last_buy_price = float(order['fills'][0]['price'])
        # 设置止盈价格
        state.take_profit_price = state.last_buy_price * (1 + Config.TAKE_PROFIT_PERCENT / 100)
        logging.info(f"设置止盈价格: {state.take_profit_price}")
        return order
    except Exception as e:
        logging.error(f"买入订单执行失败: {e}")
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
        logging.info(f"卖出订单已执行: {order}")
        state.in_position = False
        state.last_buy_price = 0
        state.take_profit_price = 0
        return order
    except Exception as e:
        logging.error(f"卖出订单执行失败: {e}")
        return None

def handle_socket_message(msg):
    global state
    if msg['e'] == 'kline':
        kline = msg['k']
        # 添加日志查看kline['x']的值
        logging.info(f"K线状态 - 闭合: {kline['x']}, 时间戳: {kline['T']}, 当前价格: {kline['c']}")
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
            logging.info(f"当前RSI{status}: {current_rsi:.2f}, 价格: {close_price}")

            # 检查买入条件
            if current_rsi < Config.OVERSOLD and not state.in_position:
                logging.info(f"RSI低于超卖阈值({Config.OVERSOLD}), 准备买入...")
                # 这里简化处理，实际交易中需要计算合适的交易量
                place_buy_order(Config.SYMBOL, 0.001)

            # 检查止盈条件
            elif state.in_position and close_price >= state.take_profit_price:
                logging.info(f"价格达到止盈点({state.take_profit_price}), 准备卖出...")
                place_sell_order(Config.SYMBOL, 0.001)

def createWebSocket():
    global twm
    symbol = Config.SYMBOL
    twm = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret,  testnet=Config.TESTNET, https_proxy=proxies['https'])
    # start is required to initialise its internal loop
    twm.start()



    twm.start_kline_socket(callback=handle_socket_message, symbol=symbol, interval=Config.INTERVAL)

    return twm

def closeWebSocket():
    global twm
    if twm is not None:
        twm.stop()
        logging.info("WebSocket连接已关闭")
        twm = None
    else:
        logging.warning("没有活动的WebSocket连接")

# 定义信号处理函数，用于优雅退出
def signal_handler(sig, frame):
    logging.info('收到退出信号，正在关闭WebSocket...')
    closeWebSocket()
    logging.info('程序已退出')
    exit(0)
def main():
    global client

    # 解决时间戳不同步问题：启用自动时间同步
    client = Client(api_key, api_secret, {'proxies': proxies}, testnet=Config.TESTNET)
    client.ping()  # 测试连接并自动同步时间

    # 设置合约杠杆
    set_leverage(Config.SYMBOL, Config.LEVERAGE)

    # 启动WebSocket
    createWebSocket()



    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 保持程序运行
    logging.info('程序正在运行，按Ctrl+C退出...')
    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()
