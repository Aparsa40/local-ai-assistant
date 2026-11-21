from typing import Dict, List, Tuple

from .config_manager import ConfigManager



class Orchestrator:
    def __init__(self):
        self.config = ConfigManager.load_config()

    def get_provider_id(self) -> str:
        """Return the user's explicitly selected provider identifier."""
        self.config = ConfigManager.load_config()
        return self.config.get("active_provider", "openrouter")

    def select_model(self, user_message: str = "") -> str:
        """Return the model explicitly selected for the active provider."""
        active = self.config.get("active_provider", "openrouter")
        provider_config = self.config.get("providers_config", {}).get(active, {})
        selected = provider_config.get("model")
        if selected:
            return selected
        if active == "openrouter":
            return "openrouter/free"
        models = self.config.get("models", {})
        return models.get("general") or next(iter(models.values()), "")

    def build_messages(
        self, history: List[Dict[str, str]], new_message: str
    ) -> Tuple[List[Dict[str, str]], str]:
        self.config = ConfigManager.load_config()
        selected_model = self.select_model(new_message)
        if not selected_model:
            raise ValueError("No model is selected for the active provider. Choose a model in Settings.")
        system_instruction = (
            f"نام تو {self.config['assistant_name']} است. "
            f"{self.config['system_prompt']}"
        )
        messages = [{"role": "system", "content": system_instruction}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": new_message})
        return messages, selected_model
