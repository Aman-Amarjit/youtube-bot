import os
import yaml
import pathlib
from typing import List, Dict, Union, Any

class ConfigError(Exception):
    """Raised when there is an issue loading or validating a game configuration."""
    pass

class SourceConfig:
    def __init__(self, provenance: str, url: str = None, channel_id: str = None):
        if not provenance:
            raise ConfigError("Missing required field 'provenance' in source configuration.")
        
        allowed_provenances = {"own_footage", "permissioned_channel", "publisher_press_kit", "creative_commons"}
        if provenance not in allowed_provenances:
            raise ConfigError(f"Invalid provenance '{provenance}'. Must be one of {allowed_provenances}.")
            
        if not url and not channel_id:
            raise ConfigError("Source entry must contain at least one of 'url' or 'channel_id'.")
            
        self.provenance = provenance
        self.url = url
        self.channel_id = channel_id

class GameConfig:
    def __init__(self, **kwargs):
        required_fields = {
            "game_name", "game_slug", "enabled", "cloud_project_id",
            "credential_secret", "schedule", "tags", "upload_title_template",
            "upload_description_template", "blocklist", "sources"
        }
        
        # Check required fields
        missing = required_fields - set(kwargs.keys())
        if missing:
            raise ConfigError(f"Missing required config fields: {missing}")
            
        self.game_name: str = kwargs["game_name"]
        self.game_slug: str = kwargs["game_slug"]
        self.enabled: bool = bool(kwargs["enabled"])
        self.cloud_project_id: str = kwargs["cloud_project_id"]
        self.credential_secret: str = kwargs["credential_secret"]
        self.schedule: str = kwargs["schedule"]
        self.tags: List[str] = list(kwargs["tags"])
        self.upload_title_template: str = kwargs["upload_title_template"]
        self.upload_description_template: str = kwargs["upload_description_template"]
        
        # Handle blocklist
        blocklist = kwargs["blocklist"]
        if isinstance(blocklist, str):
            # Treat as path, validate existence
            if not os.path.isfile(blocklist):
                raise ConfigError(f"Blocklist file '{blocklist}' does not exist or is not a file.")
            self.blocklist_path: str = blocklist
            self.blocklist_inline: List[str] = []
        elif isinstance(blocklist, list):
            self.blocklist_path: str = ""
            self.blocklist_inline: List[str] = [str(x) for x in blocklist]
        else:
            raise ConfigError("Field 'blocklist' must be a list of strings or a file path string.")
            
        # Validate sources
        sources_raw = kwargs["sources"]
        if not isinstance(sources_raw, list) or not sources_raw:
            raise ConfigError("Field 'sources' must be a non-empty list.")
            
        self.sources: List[SourceConfig] = []
        for src in sources_raw:
            if not isinstance(src, dict):
                raise ConfigError("Each source entry must be a dictionary.")
            self.sources.append(SourceConfig(**src))

def load(config_path: str) -> GameConfig:
    """Load and validate a Game Config YAML file."""
    path = pathlib.Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Config file not found at {config_path}")
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise ConfigError(f"Failed to parse YAML file {config_path}: {e}")
        
    if not isinstance(data, dict):
        raise ConfigError(f"Config data in {config_path} must be a dictionary/mapping.")
        
    # Validate game_slug equals filename stem
    slug_from_filename = path.stem
    if data.get("game_slug") != slug_from_filename:
        raise ConfigError(
            f"game_slug '{data.get('game_slug')}' must equal the filename stem "
            f"'{slug_from_filename}' (config file: {config_path})"
        )
        
    return GameConfig(**data)
