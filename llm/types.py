from pydantic import BaseModel, ConfigDict


class PromptSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str
    prompt: str
    cache_key: str
    # json: bool = False
    # force_reasoning: bool = False
    # large_output: bool = False
    # validate: bool = False
