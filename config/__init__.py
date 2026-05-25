"""
Configuration loader for AntiBlack system.
Loads settings from config.yaml with environment variable support.
"""
import os
import yaml
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


def _load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file if it exists."""
    if not os.path.exists(env_path):
        # Try relative to this file's directory
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value


@dataclass
class AppConfig:
    name: str = "AntiBlack"
    version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    token_budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MongoDBConfig:
    host: str = "localhost"
    port: int = 27017
    database: str = "antiblack"
    username: str = ""
    password: str = ""
    auth_source: str = "admin"

    @property
    def uri(self) -> str:
        if self.username and self.password:
            return f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
        return f"mongodb://{self.host}:{self.port}/{self.database}"


@dataclass
class KafkaConfig:
    bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "antiblack_pipeline"
    topics: Dict[str, str] = field(default_factory=lambda: {
        "raw_messages": "raw.messages",
        "cleaned_messages": "cleaned.messages",
        "deep_analysis": "deep.analysis.tasks",
        "image_analysis": "image.analysis.tasks"
    })
    consumer: Dict[str, Any] = field(default_factory=dict)
    producer: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LightRAGConfig:
    working_dir: str = "./rag_storage"
    llm: Dict[str, Any] = field(default_factory=dict)
    llm_backup: Dict[str, Any] = field(default_factory=dict)
    embedding: Dict[str, Any] = field(default_factory=dict)
    storage: Dict[str, str] = field(default_factory=dict)
    neo4j: Dict[str, str] = field(default_factory=dict)
    postgresql: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineConfig:
    routing: Dict[str, float] = field(default_factory=dict)
    light_channel: Dict[str, Any] = field(default_factory=dict)
    deep_channel: Dict[str, Any] = field(default_factory=dict)
    collection: Dict[str, Any] = field(default_factory=dict)
    cleaning: Dict[str, Any] = field(default_factory=dict)
    classification: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SlangLearningConfig:
    thresholds: Dict[str, int] = field(default_factory=dict)
    reject: Dict[str, Any] = field(default_factory=dict)
    token_control: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutoEvolutionConfig:
    enabled: bool = True
    silver: Dict[str, Any] = field(default_factory=dict)
    error_book: Dict[str, Any] = field(default_factory=dict)
    retrain: Dict[str, Any] = field(default_factory=dict)
    schedule: Dict[str, int] = field(default_factory=dict)


class Config:
    """Main configuration class that loads and provides access to all config values."""

    _instance: Optional['Config'] = None

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        _load_env_file()  # Load .env file first
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            # Try relative to this file's directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, self.config_path)
            if os.path.exists(config_path):
                self.config_path = config_path
            else:
                raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        # Resolve environment variables
        self._resolve_env_vars()

    def _resolve_env_vars(self) -> None:
        """Resolve ${ENV_VAR} patterns in config values."""
        self._config = self._resolve_dict(self._config)

    def _resolve_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively resolve environment variables in dict."""
        result = {}
        for k, v in d.items():
            if isinstance(v, dict):
                result[k] = self._resolve_dict(v)
            elif isinstance(v, str) and v.startswith('${') and v.endswith('}'):
                env_var = v[2:-1]
                result[k] = os.environ.get(env_var, v)
            else:
                result[k] = v
        return result

    @property
    def app(self) -> AppConfig:
        return AppConfig(**self._config.get('app', {}))

    @property
    def mongodb(self) -> MongoDBConfig:
        return MongoDBConfig(**self._config.get('mongodb', {}))

    @property
    def kafka(self) -> KafkaConfig:
        return KafkaConfig(**self._config.get('kafka', {}))

    @property
    def lightrag(self) -> LightRAGConfig:
        return LightRAGConfig(**self._config.get('lightrag', {}))

    @property
    def pipeline(self) -> PipelineConfig:
        return PipelineConfig(**self._config.get('pipeline', {}))

    @property
    def slang_learning(self) -> SlangLearningConfig:
        return SlangLearningConfig(**self._config.get('slang_learning', {}))

    @property
    def auto_evolution(self) -> AutoEvolutionConfig:
        return AutoEvolutionConfig(**self._config.get('auto_evolution', {}))

    @property
    def taxonomy(self) -> Dict[str, Any]:
        return self._config.get('taxonomy', {})

    @property
    def seed_words(self) -> Dict[str, Any]:
        return self._config.get('seed_words', {})

    @property
    def channels(self) -> Dict[str, Any]:
        return self._config.get('channels', {})

    @property
    def monitoring(self) -> Dict[str, Any]:
        return self._config.get('monitoring', {})

    @property
    def export(self) -> Dict[str, Any]:
        return self._config.get('export', {})

    @property
    def logging(self) -> Dict[str, Any]:
        return self._config.get('logging', {})

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by dot-separated key path."""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default


# Global config instance
_config: Optional[Config] = None


def get_config(config_path: str = "config.yaml") -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config


def reload_config(config_path: str = "config.yaml") -> Config:
    """Reload configuration from file."""
    global _config
    _config = Config(config_path)
    return _config