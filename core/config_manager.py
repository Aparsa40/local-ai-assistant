import json
import shutil
from pathlib import Path
from typing import Dict, Any

CONFIG_PATH = Path("config/settings.json")
EXAMPLE_CONFIG_PATH = Path("config/settings.example.json")

class ConfigManager:
    @staticmethod
    def load_config() -> Dict[str, Any]:
        # اگر فایل اصلی وجود نداشت، از روی فایل نمونه می‌سازد
        if not CONFIG_PATH.exists():
            if EXAMPLE_CONFIG_PATH.exists():
                shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
            else:
                raise FileNotFoundError("هیچ فایل تنظیماتی (اصلی یا نمونه) یافت نشد.")
                
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_config(new_config: Dict[str, Any]) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)

    @staticmethod
    def update_config(partial_data: Dict[str, Any]) -> Dict[str, Any]:
        config = ConfigManager.load_config()
        config.update(partial_data)
        ConfigManager.save_config(config)
        return config
