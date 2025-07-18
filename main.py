from binance.client import Client
import logging
from logging.handlers import RotatingFileHandler
import signal
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import sys

# 导入自定义模块
from config import TradingConfig
from data_processor import DataProcessor
from binance.client import Client
from trading_executor import TradingExecutor

config = TradingConfig()
client = Client(config.active_api_key, config.active_api_secret, testnet=config.TESTNET)
trading_executor = TradingExecutor(client, config)

# 配置日志系统
logger = logging.getLogger('trading_system')
logger.setLevel(getattr(logging, config.LOG_LEVEL))

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 自定义过滤器：只允许包含买入或卖出关键词的日志
class TradingFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        # return '买入' in message or '卖出' in message or '做空' in message or 'RSI' in message
        return message

# 控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(getattr(logging, config.LOG_LEVEL))
console_handler.setFormatter(formatter)
console_handler.addFilter(TradingFilter())

# 模拟交易日志处理器
simulation_file_handler = RotatingFileHandler(
    config.SIMULATION_LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,
    encoding='utf-8'
)
simulation_file_handler.setLevel(logging.DEBUG)
simulation_file_handler.setFormatter(formatter)

# 真实交易日志处理器
real_file_handler = RotatingFileHandler(
    config.REAL_LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=5,
    encoding='utf-8'
)
real_file_handler.setLevel(logging.DEBUG)
real_file_handler.setFormatter(formatter)

# 模拟交易日志过滤器
class SimulationLogFilter(logging.Filter):
    def filter(self, record):
        return '[模拟]' in record.getMessage()

# 真实交易日志过滤器
class RealLogFilter(logging.Filter):
    def filter(self, record):
        return '[模拟]' not in record.getMessage() and ('买入' in record.getMessage() or '卖出' in record.getMessage() or '做空' in record.getMessage())

simulation_file_handler.addFilter(SimulationLogFilter())
real_file_handler.addFilter(RealLogFilter())

# 移除默认处理器
if logger.handlers:
    logger.handlers = []

# 添加处理器
logger.addHandler(console_handler)
logger.addHandler(simulation_file_handler)
logger.addHandler(real_file_handler)

# 状态跟踪
class TradingState:
    def __init__(self):
        self.in_position = False
        self.last_short_price = 0
        self.klines = []
        self.take_profit_price = 0

# 为每个交易对创建独立的状态
state_map = {symbol: TradingState() for symbol in config.SYMBOLS}

# 初始化变量
client = None


# 定义信号处理函数，用于优雅退出
def signal_handler(sig, frame):
    logger.info('程序正在退出...')
    if 'executor' in globals() and executor is not None:
        executor.shutdown(wait=False)
    exit(0)


def process_symbol(symbol):
    logger.info(f"开始处理交易对: {symbol}")
    try:
        # 初始化交易状态
        state = TradingState()
        state_map[symbol] = state

        # 获取K线数据
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval=config.INTERVAL,
                limit=config.RSI_PERIOD + 100
            )

            # 处理K线数据
            df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['close'] = df['close'].astype(float)

            # 初始化K线列表
            state.klines = df[['timestamp', 'close']].to_dict('records')
            logger.info(f"成功加载{len(state.klines)}条{symbol}的K线数据")

            # 计算初始RSI
            if len(state.klines) >= config.RSI_PERIOD:
                # 计算RSI并提取最新值
                  kline_df = pd.DataFrame(state.klines)
                  DataProcessor.calculate_rsi(kline_df, config.RSI_PERIOD)
                  rsi_value = kline_df['rsi'].iloc[-1] if not kline_df.empty else 50
                  trading_executor.check_trading_conditions(symbol, rsi_value, state)
                  logger.info(f"{symbol}当前RSI: {rsi_value:.2f}")



        except Exception as e:
            logger.error(f"获取{symbol}的K线数据失败: {e}")
            return

    except Exception as e:
        logger.error(f"处理{symbol}时发生错误: {e}", exc_info=True)


def main():
    global client

    # 初始化Binance客户端
    client = Client(config.active_api_key, config.active_api_secret, {'proxies': config.PROXIES}, testnet=config.TESTNET)
    client.ping()  # 测试连接并自动同步时间



    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info('使用REST API数据源')
    # 创建线程池，最大线程数为交易对数量
    max_workers = min(len(config.SYMBOLS), 10)  # 限制最大线程数为10
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        logger.info('程序正在运行，按Ctrl+C退出...')
        while True:
            # 提交所有交易对的处理任务
            futures = {executor.submit(process_symbol, symbol): symbol for symbol in config.SYMBOLS}
            # 等待刷新间隔
            time.sleep(config.REFRESH_INTERVAL - 0.001)


if __name__ == '__main__':
    main()