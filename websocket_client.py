import json
import logging
from binance import ThreadedWebsocketManager
from dotenv import load_dotenv
import os
import time

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger('websocket_client')
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class BinanceWebSocketClient:
    def __init__(self, symbols, interval, testnet=True, proxies=None):
        self.symbols = symbols
        self.interval = interval
        self.testnet = testnet
        self.proxies = proxies
        self.twm = None
        self.running = False
        self.data_callback = None
        self.api_key = os.getenv('TEST_API_KEY' if testnet else 'API_KEY')
        self.api_secret = os.getenv('TEST_API_SECRET' if testnet else 'API_SECRET')

    def on_message(self, message):
        """接收到WebSocket消息时调用"""
        try:
            data = json.loads(message)
            if 'data' in data:
                # 处理K线数据
                kline_data = data['data']
                if self.data_callback:
                    self.data_callback(kline_data)
        except Exception as e:
            logger.error(f'处理消息错误: {e}')

    def on_error(self, error):
        """WebSocket错误时调用"""
        logger.error(f'WebSocket错误: {error}')

    def on_close(self):
        """WebSocket关闭时调用"""
        logger.info('WebSocket连接已关闭')
        self.running = False
        # 尝试重连
        logger.info('尝试重新连接...')
        time.sleep(5)
        self.start(self.data_callback)

    def start(self, data_callback=None):
        """启动WebSocket客户端"""
        self.data_callback = data_callback
        self.running = True

        # 创建ThreadedWebsocketManager实例
        self.twm = ThreadedWebsocketManager(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            proxies=self.proxies
        )

        # 启动WebSocket管理器
        self.twm.start()

        # 为每个交易对订阅K线流
        for symbol in self.symbols:
            stream_name = f'{symbol.lower()}@kline_{self.interval}'
            logger.info(f'订阅流: {stream_name}')
            self.twm.start_stream(
                stream_name=stream_name,
                callback=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )

        logger.info('WebSocket客户端已启动')

    def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        if self.twm:
            self.twm.stop()
            logger.info('WebSocket客户端已停止')

# 通用工具函数
def setup_logger(name, log_file=None, level=logging.INFO):
    """设置日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 移除已存在的处理器
    if logger.handlers:
        logger.handlers = []

    # 创建格式化器
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 添加文件处理器（如果提供了文件路径）
    if log_file:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# 示例用法
if __name__ == '__main__':
    # 测试WebSocket连接
    def handle_kline_data(data):
        symbol = data['s']
        close_price = float(data['k']['c'])
        logger.info(f'收到{symbol}的K线数据: 收盘价={close_price}')

    # 配置参数
    symbols = ['CRVUSDT', 'ACHUSDT', 'ONDOUSDT']
    interval = '15m'
    testnet = True
    proxies = {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890'
    }

    # 创建并启动WebSocket客户端
    ws_client = BinanceWebSocketClient(symbols, interval, testnet, proxies)
    ws_client.start(handle_kline_data)