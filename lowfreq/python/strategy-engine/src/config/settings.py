"""Configuration Management"""
import os
import platform
from pathlib import Path
from typing import List
from dotenv import load_dotenv
import yaml

load_dotenv()


class Settings:
    """Application Configuration"""

    # Kafka configuration
    KAFKA_BROKERS: List[str] = os.getenv("KAFKA_BROKERS", "localhost:9092").split(",")
    KAFKA_TOPIC: str = os.getenv("KAFKA_TOPIC", "market.data")
    KAFKA_GROUP_ID: str = os.getenv("KAFKA_GROUP_ID", "strategy_engine_group")

    # Data storage configuration
    DATA_BASE_PATH: Path = Path(os.getenv("DATA_BASE_PATH", "D:/TradingPlatform/data"))
    PARQUET_PATH: Path = Path(os.getenv("PARQUET_PATH", "D:/TradingPlatform/data/minute/1min"))

    # ExecutionService configuration
    EXECUTION_SERVICE_ADDRESS: str = os.getenv("EXECUTION_SERVICE_ADDRESS", "localhost:50051")

    # Strategy configuration
    INITIAL_CAPITAL: float = float(os.getenv("INITIAL_CAPITAL", "1000000"))
    COMMISSION_RATE: float = float(os.getenv("COMMISSION_RATE", "0.0003"))

    # Logging configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Set log path based on OS and environment variables
    if os.getenv("LOG_PATH"):
        # If environment variable is set, use it
        LOG_PATH: Path = Path(os.getenv("LOG_PATH"))
    else:
        # Otherwise auto-select based on OS
        if platform.system() == "Windows":
            # Windows: use D:/TradingPlatform/logs/strategy-engine
            LOG_PATH: Path = Path("D:/TradingPlatform/logs/strategy-engine")
        else:
            # Linux/Docker: use /var/log/services/strategy-engine
            LOG_PATH: Path = Path("/var/log/services/strategy-engine")


def load_config(config_path: str) -> dict:
    """Load YAML configuration file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


settings = Settings()
