from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger("agent_team.retry")

F = TypeVar("F", bound=Callable[..., Any])

RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,
)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "%s 在 %d 次尝试后仍然失败: %s",
                            func.__name__, attempt, exc,
                        )
                        raise
                    logger.warning(
                        "%s 第 %d/%d 次失败: %s — %.1fs 后重试",
                        func.__name__, attempt, max_attempts, exc, delay,
                    )
                    if on_retry:
                        on_retry(exc, attempt)
                    time.sleep(delay)
                    delay = min(delay * backoff, max_delay)
            if last_exc:
                raise last_exc
        return wrapper  # type: ignore[return-value]
    return decorator


def safe_run(func: Callable[..., Any], *args: Any,
             default: Any = None, timeout: float = 30.0,
             **kwargs: Any) -> Any:
    import concurrent.futures
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logger.error("%s 超时 (%.1fs)", getattr(func, "__name__", str(func)), timeout)
        return default
    except Exception as exc:
        logger.error("%s 异常: %s", getattr(func, "__name__", str(func)), exc)
        return default
