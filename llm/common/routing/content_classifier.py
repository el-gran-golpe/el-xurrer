import json
from pathlib import Path
from typing import Literal, Union


# rule-based or LLM-based content tags
class ContentClassifier:
    """
    Classifies prompt content as either 'hot' (needs a censored/safe model)
    or 'general' (can use uncensored models first) based on keyword matching.
    """

    HOT_KEYWORDS: set[str] = {
        "nsfw",
        "adult",
        "illegal",
        "hack",
        "weapon",
        "drugs",
        "politics",
        "self-harm",
        "suicide",
        "hate",
        "violence",
        "credit card",
        "password",
        "social security",
        "piracy",
    }

    def classify_text(self, text: str) -> Literal["hot", "general"]:
        """
        Return 'hot' if any HOT_KEYWORD is found in text (case-insensitive), else 'general'.
        """
        lower = text.lower()
        for kw in self.HOT_KEYWORDS:
            if kw in lower:
                return "hot"
        return "general"

    def classify_prompts(self, prompts: list[dict]) -> Literal["hot", "general"]:
        """
        Given a list of prompt-spec dicts, examine each 'system_prompt' and 'prompt'
        field. If any classify as 'hot', the whole is 'hot'.
        """
        for spec in prompts:
            sys_text = spec.get("system_prompt", "")
            usr_text = spec.get("prompt", "")
            if (
                self.classify_text(sys_text) == "hot"
                or self.classify_text(usr_text) == "hot"
            ):
                return "hot"
        return "general"

    def classify_file(self, filepath: Union[str, Path]) -> Literal["hot", "general"]:
        """
        Load a JSON file and classify its prompts. Supports either:
          - A JSON object with a "prompts": [ ... ] array, or
          - A top-level JSON array of prompt-spec objects.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Prompt spec file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, dict) and "prompts" in data:
            prompts = data["prompts"]
        elif isinstance(data, list):
            prompts = data
        else:
            raise ValueError(
                f"Unrecognized prompt-spec format in {path!r}: "
                f"expected a list or a {{'prompts': [...]}} object"
            )

        if not isinstance(prompts, list):
            raise ValueError(f"'prompts' key in {path!r} is not a list")

        return self.classify_prompts(prompts)
