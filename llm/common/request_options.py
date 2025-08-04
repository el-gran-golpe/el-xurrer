from pydantic import BaseModel, ConfigDict


class RequestOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_json: bool = False
    large_output: bool = False
    validate: bool = False
    force_reasoning: bool = False
