"""Configuration management for the Polymarket trading bot."""
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class ClobConfig:
    host: str = "https://clob.polymarket.com"
    chain_id: int = 137
    signature_type: int = 2


@dataclass
class RelayerConfig:
    host: str = "https://relayer-v2.polymarket.com"
    tx_type: str = "SAFE"


@dataclass
class BuilderConfig:
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""


@dataclass
class Config:
    safe_address: str = ""
    rpc_url: str = "https://polygon-rpc.com"
    clob: ClobConfig = field(default_factory=ClobConfig)
    relayer: RelayerConfig = field(default_factory=RelayerConfig)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    default_token_id: str = ""
    default_size: float = 1.0
    default_price: float = 0.5
    data_dir: str = "credentials"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        config = cls()
        config.safe_address = os.getenv("POLY_SAFE_ADDRESS", "")
        config.rpc_url = os.getenv("POLY_RPC_URL", config.rpc_url)
        config.data_dir = os.getenv("POLY_DATA_DIR", config.data_dir)
        config.log_level = os.getenv("POLY_LOG_LEVEL", config.log_level)

        chain_id_str = os.getenv("POLY_CHAIN_ID", "")
        config.clob = ClobConfig(
            host=os.getenv("POLY_CLOB_HOST", ClobConfig.host),
            chain_id=int(chain_id_str) if chain_id_str else 137,
            signature_type=2,
        )

        config.relayer = RelayerConfig()

        config.builder = BuilderConfig(
            api_key=os.getenv("POLY_BUILDER_API_KEY", ""),
            api_secret=os.getenv("POLY_BUILDER_API_SECRET", ""),
            api_passphrase=os.getenv("POLY_BUILDER_API_PASSPHRASE", ""),
        )

        size_str = os.getenv("POLY_DEFAULT_SIZE", "")
        if size_str:
            config.default_size = float(size_str)

        price_str = os.getenv("POLY_DEFAULT_PRICE", "")
        if price_str:
            config.default_price = float(price_str)

        return config

    @classmethod
    def load(cls, path: str) -> "Config":
        """Load configuration from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return cls._from_dict(data)

    @classmethod
    def load_with_env(cls, path: str) -> "Config":
        """Load YAML config then override with environment variables."""
        config = cls.load(path)
        env_config = cls.from_env()

        # Override with any env vars that are explicitly set
        if os.getenv("POLY_SAFE_ADDRESS"):
            config.safe_address = env_config.safe_address
        if os.getenv("POLY_RPC_URL"):
            config.rpc_url = env_config.rpc_url
        if os.getenv("POLY_DATA_DIR"):
            config.data_dir = env_config.data_dir
        if os.getenv("POLY_LOG_LEVEL"):
            config.log_level = env_config.log_level
        if os.getenv("POLY_CLOB_HOST"):
            config.clob.host = env_config.clob.host
        if os.getenv("POLY_CHAIN_ID"):
            config.clob.chain_id = env_config.clob.chain_id
        if os.getenv("POLY_BUILDER_API_KEY"):
            config.builder.api_key = env_config.builder.api_key
        if os.getenv("POLY_BUILDER_API_SECRET"):
            config.builder.api_secret = env_config.builder.api_secret
        if os.getenv("POLY_BUILDER_API_PASSPHRASE"):
            config.builder.api_passphrase = env_config.builder.api_passphrase
        if os.getenv("POLY_DEFAULT_SIZE"):
            config.default_size = env_config.default_size
        if os.getenv("POLY_DEFAULT_PRICE"):
            config.default_price = env_config.default_price

        return config

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Build a Config from a dictionary (e.g. parsed YAML).

        YAML values starting with 0x are parsed as integers by default unless
        quoted, so we convert integers to their hex strings where appropriate.
        """
        config = cls()

        def _str(val) -> str:
            if val is None:
                return ""
            if isinstance(val, int):
                return hex(val)
            return str(val)

        config.safe_address = _str(data.get("safe_address", ""))
        config.rpc_url = data.get("rpc_url", config.rpc_url)
        config.default_token_id = _str(data.get("default_token_id", ""))
        config.data_dir = data.get("data_dir", config.data_dir)
        config.log_level = data.get("log_level", config.log_level)

        size_val = data.get("default_size")
        if size_val is not None:
            config.default_size = float(size_val)

        price_val = data.get("default_price")
        if price_val is not None:
            config.default_price = float(price_val)

        clob_data = data.get("clob", {}) or {}
        config.clob = ClobConfig(
            host=clob_data.get("host", ClobConfig.host),
            chain_id=int(clob_data.get("chain_id", 137)),
            signature_type=int(clob_data.get("signature_type", 2)),
        )

        relayer_data = data.get("relayer", {}) or {}
        config.relayer = RelayerConfig(
            host=relayer_data.get("host", RelayerConfig.host),
            tx_type=relayer_data.get("tx_type", RelayerConfig.tx_type),
        )

        builder_data = data.get("builder", {}) or {}
        config.builder = BuilderConfig(
            api_key=builder_data.get("api_key", ""),
            api_secret=builder_data.get("api_secret", ""),
            api_passphrase=builder_data.get("api_passphrase", ""),
        )

        return config
