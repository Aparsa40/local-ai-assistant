from abc import ABC, abstractmethod
from typing import List, Dict, AsyncGenerator

class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if False:
            yield ""
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> List[str]:
        """دریافت لیست مدل‌های موجود در این سرویس‌دهنده"""
        pass