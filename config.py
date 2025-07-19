from dataclasses import dataclass, field
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

@dataclass
class TradingConfig:
    """交易系统配置参数"""
    # 基础配置
    REFRESH_INTERVAL: int = 2  # REST API刷新间隔(秒)

    # 交易对配置
    SYMBOLS: list[str] = field(default_factory=lambda: ['ACHUSDT'])
    SIMULATION_MODE: bool = field(default_factory=lambda: True)
    SIMULATED_BALANCE: float = field(default_factory=lambda: 10000.0)  # 模拟USDT余额
    TAKE_PROFIT_PERCENT: float = field(default_factory=lambda: 2.0)  # 止盈百分比(%)
    INTERVAL: str = '15m'  # K线周期

    # RSI指标配置
    RSI_PERIOD: int = 6
    OVERBOUGHT: int = 25 # 超买
    OVERSOLD: int = 22 # 超卖

    # 交易配置
    TESTNET: bool = False
    LEVERAGE: int = 10
    
    TAKE_PROFIT_PERCENT: float = 10.0  # 做空目标盈利百分比，对应价格下跌幅度

    # API配置
    API_KEY: str = os.getenv('ROOT_API_KEY', '')
    API_SECRET: str = os.getenv('ROOT_API_SECRET', '')
    TEST_API_KEY: str = os.getenv('TEST_API_KEY', '')
    TEST_API_SECRET: str = os.getenv('TEST_API_SECRET', '')

    # 代理配置
    PROXIES: dict[str, str] = field(default_factory=lambda: {
        'http': 'http://127.0.0.1:7890',
        'https': 'http://127.0.0.1:7890'
    })

    # 日志配置
    LOG_FILE: str = 'trading.log'
    SIMULATION_LOG_FILE: str = 'simulation_trading.log'
    REAL_LOG_FILE: str = 'real_trading.log'
    LOG_LEVEL: str = 'INFO'

    @property
    def active_api_key(self) -> str:
        """根据当前环境返回活跃的API Key"""
        return self.TEST_API_KEY if self.TESTNET else self.API_KEY

    @property
    def active_api_secret(self) -> str:
        """根据当前环境返回活跃的API Secret"""
        return self.TEST_API_SECRET if self.TESTNET else self.API_SECRET