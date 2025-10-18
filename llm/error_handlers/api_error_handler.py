from loguru import logger
from requests import Response, HTTPError

from llm.error_handlers.exceptions import RateLimitError


class ApiErrorHandler:
    def transform_api_error_to_exception(
        self, response: Response, model_id: str
    ) -> Exception:
        # 429: quota exhausted
        if response.status_code == 429:
            if response.reason == "Too Many Requests":
                headers = response.headers
                cooldown_seconds = headers["retry-after"]
                return RateLimitError(
                    message=f"Too many request in the last 60s. Model: {model_id}",
                    cooldown_seconds=int(cooldown_seconds),
                )

        # 400: likely unsupported (e.g. system prompt / json)
        elif response.status_code == 400:
            logger.debug("Error 400: bad request for model {}.", model_id)
            return HTTPError(f"Bad request for model {model_id}")

        else:
            # Other errors
            logger.error(
                "Probing error for model {}: {} - {}",
                model_id,
                response.status_code,
                (response.text or "").strip(),
            )
            return Exception(
                f"Probing error for model {model_id}: {response.status_code} - {response.text}"
            )
        return Exception(
            f"Unhandled error for model {model_id}, status code {response.status_code}"
        )
