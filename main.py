from binance.client import Client
import logging
from logging.handlers import RotatingFileHandler
import signal
import time
import pandas as pd
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import sys

# 导入自定义模块
from config import Config
from data_processor import DataProcessor
from trading_executor import TradingExecutor
from websocket_client import BinanceWebSocketClient

# 配置日志系统
logger = logging.getLogger('trading_system')
logger.setLevel(getattr(logging, Config.LOG_LEVEL))

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 自定义过滤器：只允许包含买入或卖出关键词的日志
class TradingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        return '买入' in message or '卖出' in message or '做空' in message or 'RSI' in message

# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(getattr(logging, Config.LOG_LEVEL))
console_handler.setFormatter(formatter)
console_handler.addFilter(TradingFilter())

# 文件处理器 (支持轮转)
file_handler = RotatingFileHandler(
    Config.LOG_FILE,
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
client = None

def on_kline_data(kline_data):
    """WebSocket K线数据回调函数"""
    symbol = kline_data['s']
    if symbol in state_map:
        state = state_map[symbol]
        df, rsi_value = DataProcessor.process_kline_data(kline_data, state)
        if df is not None and rsi_value is not None:
            close_price = df['close'].iloc[-1]
            # 检查交易条件
            trading_executor = TradingExecutor(client)
            trading_executor.check_trading_conditions(symbol, close_price, rsi_value, state)
# 定义信号处理函数，用于优雅退出
def signal_handler(sig, frame):
    logger.info('程序正在退出...')
    if 'executor' in globals() and executor is not None:
        executor.shutdown(wait=False)
    exit(0)

def main():
    global client

    # 初始化Binance客户端
    client = Client(Config.API_KEY, Config.API_SECRET, {'proxies': Config.PROXIES}, testnet=Config.TESTNET)
    client.ping()  # 测试连接并自动同步时间

    # 为每个交易对设置合约杠杆
    trading_executor = TradingExecutor(client)
    for symbol in Config.SYMBOLS:
        trading_executor.set_leverage(symbol)

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 根据配置选择数据源
    if Config.DATA_SOURCE == 'websocket':
        logger.info('使用WebSocket数据源')
        ws_client = BinanceWebSocketClient(
            symbols=Config.SYMBOLS,
            interval=Config.INTERVAL,
            testnet=Config.TESTNET,
            proxies=Config.PROXIES
        )
        ws_client.start(on_kline_data)
    else:
        logger.info('使用REST API数据源')
        # 创建线程池，最大线程数为交易对数量
        max_workers = min(len(Config.SYMBOLS), 10)  # 限制最大线程数为10
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            logger.info('程序正在运行，按Ctrl+C退出...')
            while True:
                # 提交所有交易对的处理任务
                futures = {executor.submit(process_symbol, symbol): symbol for symbol in Config.SYMBOLS}

                # 等待刷新间隔
                time.sleep(Config.REFRESH_INTERVAL - 0.001)

if __name__ == '__main__':
    main()
def process_symbol(symbol):
    logger.info(f"开始处理交易对: {symbol}")
    try:
        # 初始化交易状态
        state = TradingState()
        state_map[symbol] = state

        # 创建交易执行器
        executor = TradingExecutor(client)
        
        # 设置杠杆
        executor.set_leverage(symbol, Config.LEVERAGE)

        # 获取K线数据
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval=Config.KLINE_INTERVAL,
                limit=Config.RSI_PERIOD + 100
            )
            
            # 处理K线数据
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close'] = df['close'].astype(float)
            
            # 初始化K线列表
            state.klines = df[['timestamp', 'close']].to_dict('records')
            logger.info(f"成功加载{len(state.klines)}条{symbol}的K线数据")

            # 计算初始RSI
            if len(state.klines) >= Config.RSI_PERIOD:
                rsi_value = DataProcessor.calculate_rsi(pd.DataFrame(state.klines), Config.RSI_PERIOD)
                logger.info(f"{symbol}当前RSI: {rsi_value:.2f}")

            # 模拟实时更新
            for i in range(5):
                # 模拟新价格数据
                last_close = state.klines[-1]['close']
                new_close = last_close * (1 + (random.uniform(-0.01, 0.01)))
                new_timestamp = state.klines[-1]['timestamp'] + pd.Timedelta(minutes=1)

                # 添加新数据
                state.klines.append({
                    'timestamp': new_timestamp,
                    'close': new_close
                })

                # 保持K线列表长度
                if len(state.klines) > Config.RSI_PERIOD + 100:
                    state.klines.pop(0)

                # 计算RSI并检查交易条件
                rsi_value = None
                if len(state.klines) >= Config.RSI_PERIOD:
                    rsi_value = DataProcessor.calculate_rsi(pd.DataFrame(state.klines), Config.RSI_PERIOD)
                    logger.info(f"{symbol}模拟RSI更新: {rsi_value:.2f}, 价格: {new_close:.4f}")
                    
                    # 检查交易条件
                    executor.check_trading_conditions(symbol, new_close, rsi_value, state)

                # 等待1秒
                time.sleep(1)

        except Exception as e:
            logger.error(f"获取{symbol}的K线数据失败: {e}")
            return

    except Exception as e:
        logger.error(f"处理{symbol}时发生错误: {e}", exc_info=True)



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

            # 等待刷新间隔
            time.sleep(refresh_interval - 0.001)  # 减去动画暂停时间以保持总间隔一致

if __name__ == '__main__':
    main()
