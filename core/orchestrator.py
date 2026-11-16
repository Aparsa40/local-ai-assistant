from typing import List, Dict, Tuple
from .config_manager import ConfigManager
from .providers.base import BaseLLMProvider
from .providers.ollama_provider import OllamaProvider
from .providers.openrouter_provider import OpenRouterProvider

class Orchestrator:
    def __init__(self):
        self.config = ConfigManager.load_config()

    def get_provider(self) -> BaseLLMProvider:
        self.config = ConfigManager.load_config()
        active = self.config.get("active_provider", "ollama")

        if active == "ollama":
            url = self.config["providers_config"]["ollama"]["base_url"]
            return OllamaProvider(base_url=url)
        elif active == "openrouter":
            cfg = self.config["providers_config"]["openrouter"]
            return OpenRouterProvider(api_key=cfg["api_key"], base_url=cfg["base_url"])
        else:
            raise ValueError(f"سرویس‌دهنده ناشناخته: {active}")

    def select_model(self, user_message: str) -> str:
        """انتخاب هوشمند مدل بر اساس محتوای پیام کاربر"""
        models = self.config["models"]
        mode = self.config.get("routing_mode", "auto")

        if mode != "auto":
            return models.get(mode, models["general"])

        msg_lower = user_message.lower()
        code_keywords = ["کد", "پایتون", "جاوا", "برنامه", "تابع", "ارور", "خطا", "code", "python", "function", "script", "bug", "html", "css", "sql"]
        reasoning_keywords = ["تحلیل", "مقایسه", "استدلال", "سند", "خلاصه", "چرا", "منطق", "analyze", "compare", "reason", "document", "explain"]

        if any(k in msg_lower for k in code_keywords):
            return models["coder"]
        elif any(k in msg_lower for k in reasoning_keywords):
            return models["reasoning"]
        else:
            return models["general"]

    def build_messages(self, history: List[Dict[str, str]], new_message: str) -> Tuple[List[Dict[str, str]], str]:
        """تزریق شخصیت واحد دستیار و آماده‌سازی تاریخچه گفتگو"""
        self.config = ConfigManager.load_config()
        selected_model = self.select_model(new_message)

        system_instruction = (
            f"نام تو {self.config['assistant_name']} است. "
            f"{self.config['system_prompt']}"
        )

        formatted_messages = [{"role": "system", "content": system_instruction}]
        formatted_messages.extend(history[-10:]) # نگهداری ۱۰ پیام آخر برای حفظ سرعت و حافظه کوتاه‌مدت
        formatted_messages.append({"role": "user", "content": new_message})

        return formatted_messages, selected_model