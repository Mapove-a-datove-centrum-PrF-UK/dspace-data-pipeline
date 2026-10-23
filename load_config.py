import os
from pathlib import Path


def get_config(file_path: str = "config.env") -> dict:
    """
    Parses a plain-text configuration file formatted as key-value pairs (KEY=VALUE).
    
    Ignores empty lines, trailing whitespaces, and full-line comments starting with '#'.
    Strips single and double quotes around values.

    :param file_path: Relative or absolute path to the configuration file.
    :return: Dictionary containing parsed configuration key-value mappings.
    :raises FileNotFoundError: If the configuration file does not exist.
    """
    cfg_path = Path(file_path)

    # Validate config existence
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path.resolve()}")

    config = {}

    # Open the configuration file using UTF-8 encoding
    with open(cfg_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comment lines
            if not line or line.startswith("#"):
                continue

            # Process only lines containing an =
            if "=" in line:
                # Split only on the first '=' to allow values that contain '=' (e.g., tokens, base64)
                k, v = line.split("=", 1)

                # Clean whitespace from key; strip whitespace and wrapping quotes from value
                config[k.strip()] = v.strip().strip("'\"")

    return config


# load the configuration
#CONFIG = load_text_config()


# def get_config(key: str, default: str = "") -> str:
#     """
#     Retrieves a configuration value by key with fallback precedence:
#       1. System environment variable (os.getenv) - allows runtime/container overrides.
#       2. Key from the parsed configuration file (CONFIG dictionary).
#       3. User-provided default fallback value.

#     :param key: Configuration parameter name.
#     :param default: Fallback string value if key is not found.
#     :return: Configuration value as a string.
#     """
#     return os.getenv(key, CONFIG.get(key, default))


# def get_config_bool(key: str, default: bool = False) -> bool:
#     """
#     Retrieves a configuration value and parses it into a standard boolean.
    
#     Recognizes truthy string representations: 'true', '1', and 'yes' (case-insensitive).
#     All other values evaluate to False.

#     :param key: Configuration parameter name.
#     :param default: Fallback boolean value if key is not found.
#     :return: Parsed boolean value.
#     """
#     val = get_config(key, str(default)).lower()
#     return val in ("true", "1", "yes")