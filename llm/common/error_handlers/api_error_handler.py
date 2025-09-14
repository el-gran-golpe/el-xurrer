from loguru import logger
from requests import Response


class ApiErrorHandler:
    # TODO: FOR MOI - It would be nice that here I could update the model object directly
    # but I don't have access to it here since when this method is called, it is literally
    # in the (middle of the) process of creating the LLMModel object
    def handle_json_probing_error(self, response: Response, model_id: str) -> bool:
        # 429: quota exhausted
        if response.status_code == 429:
            logger.warning(
                "Error 429: quota is already exhausted for model {}.",
                model_id,
            )
            return False

        # 400: likely unsupported (e.g. system prompt / json)
        elif response.status_code == 400:
            logger.debug("Error 400: bad request for model {}.", model_id)
            return False

        else:
            # Other errors
            logger.error(
                "Probing error for model {}: {} - {}",
                model_id,
                response.status_code,
                (response.text or "").strip(),
            )
            return False

