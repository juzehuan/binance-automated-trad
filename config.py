import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    # 数据源配置
    DATA_SOURCE = 'websocket'  # 可选: 'rest_api' 或 'websocket'
    REFRESH_INTERVAL = 2  # REST API刷新间隔(秒)

    # 交易对配置
    SYMBOLS = ["CRVUSDT", "ACHUSDT", "ONDOUSDT"]
    INTERVAL = '15m'  # K线周期

    # RSI指标配置
    RSI_PERIOD = 6
    OVERBOUGHT = 90
    OVERSOLD = 5

    # 交易配置
    TESTNET = True
    LEVERAGE = 10
    TAKE_PROFIT_PERCENT = 5

    # API配置
    API_KEY = os.getenv('TEST_API_KEY' if TESTNET else 'API_KEY')
    API_SECRET = os.getenv('TEST_API_SECRET' if TESTNET else 'API_SECRET')

    # 代理配置
    PROXIES = {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890'
    }

    # 日志配置
    LOG_FILE = 'trading.log'
    LOG_LEVEL = 'INFO'