"""Tests for Config class from src/config.py."""
import pytest
from src.config import Config, BuilderConfig, ClobConfig


class TestConfig:
    def test_default_values(self):
        config = Config()
        assert config.rpc_url == "https://polygon-rpc.com"
        assert config.clob.host == "https://clob.polymarket.com"
        assert config.clob.chain_id == 137
        assert config.default_size == 1.0
        assert config.log_level == "INFO"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("POLY_SAFE_ADDRESS", "0x" + "b" * 40)
        monkeypatch.setenv("POLY_BUILDER_API_KEY", "test_key")
        monkeypatch.setenv("POLY_BUILDER_API_SECRET", "test_secret")
        monkeypatch.setenv("POLY_CHAIN_ID", "137")

        config = Config.from_env()
        assert config.safe_address == "0x" + "b" * 40
        assert config.builder.api_key == "test_key"
        assert config.builder.api_secret == "test_secret"
        assert config.clob.chain_id == 137

    def test_load_yaml(self, tmp_path):
        yaml_content = '''
safe_address: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
rpc_url: "https://example.com"
clob:
  host: "https://clob.example.com"
  chain_id: 137
builder:
  api_key: "yaml_key"
'''
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = Config.load(str(config_file))
        assert "bbbb" in config.safe_address
        assert config.builder.api_key == "yaml_key"

    def test_load_with_env_overrides(self, tmp_path, monkeypatch):
        yaml_content = '''
safe_address: "0x1111111111111111111111111111111111111111"
builder:
  api_key: "yaml_key"
'''
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        monkeypatch.setenv("POLY_BUILDER_API_KEY", "env_key")
        monkeypatch.setenv("POLY_SAFE_ADDRESS", "0x" + "b" * 40)

        config = Config.load_with_env(str(config_file))
        assert config.builder.api_key == "env_key"
        assert "bbbb" in config.safe_address

    def test_default_safe_address_empty(self):
        config = Config()
        assert config.safe_address == ""

    def test_default_builder_empty(self):
        config = Config()
        assert config.builder.api_key == ""
        assert config.builder.api_secret == ""
        assert config.builder.api_passphrase == ""

    def test_from_env_defaults_when_not_set(self, monkeypatch):
        monkeypatch.delenv("POLY_SAFE_ADDRESS", raising=False)
        monkeypatch.delenv("POLY_BUILDER_API_KEY", raising=False)
        config = Config.from_env()
        assert config.safe_address == ""
        assert config.builder.api_key == ""

    def test_load_yaml_0x_address_quoted(self, tmp_path):
        yaml_content = 'safe_address: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)
        config = Config.load(str(config_file))
        assert config.safe_address == "0x" + "a" * 40
