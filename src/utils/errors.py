from src.utils.logging import log


class TwcertLoginError(Exception):
    pass


class GeminiQuotaExhausted(Exception):
    pass


def send_ops_alert(title: str, detail: str) -> None:
    log.error("[OPS] %s — %s", title, detail)
