from typing import Literal
from llm.constants import HOT_KEYWORDS
from llm.base_llm import PromptSpecification


class ContentClassifier:
    """
    Classifies prompts or text as 'hot' (contains sensitive keywords) or 'innocent'.
    """

    hot_keywords = HOT_KEYWORDS

    def classify_prompts(
        self, prompts: list[PromptSpecification]
    ) -> Literal["hot", "innocent"]:
        for spec in prompts:
            # Use .model_dump to get dict representation
            sys_text = spec.system_prompt
            usr_text = spec.prompt
            cache_text = spec.cache_key
            if (
                self.classify_text(sys_text) == "hot"
                or self.classify_text(usr_text) == "hot"
                or self.classify_text(cache_text) == "hot"
            ):
                return "hot"
        return "innocent"

    def classify_text(self, text: str) -> Literal["hot", "innocent"]:
        lower = text.lower()
        for kw in self.hot_keywords:
            if kw in lower:
                return "hot"
        return "innocent"
