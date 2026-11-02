"""Request-local timing and usage accounting without conversation payloads.

Use only static, developer-controlled labels for span names. Never pass URLs,
order/customer identifiers, prompt text, or exception messages as labels.
The only logger event is a JSON trace_summary at the end of trace_scope.
Configure ``my_agent.telemetry`` at INFO in the application to collect it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import inspect
import json
import logging
import math
import re
from functools import wraps
from threading import RLock
from time import monotonic
from uuid import UUID, uuid4

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    class BaseCallbackHandler:
        """Keep the core usable without optional LangChain dependencies."""


LOGGER = logging.getLogger("my_agent.telemetry")
_CURRENT: ContextVar[Trace | None] = ContextVar("agent_telemetry_trace", default=None)
_KINDS = frozenset({"node", "tool", "api", "llm", "graph", "request", "other"})
_ERROR_KINDS = frozenset({
    "timeout", "connection", "rate_limit", "authentication", "permission",
    "validation", "cancelled", "internal",
})
_LABEL = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


def _label(value):
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else "other"


def _trace_id(value):
    if value is not None:
        try:
            parsed = UUID(str(value))
            return parsed.hex
        except (ValueError, TypeError, AttributeError):
            pass
    return uuid4().hex


def _tokens(value):
    """Reject noncounts; numeric strings and integral finite floats are accepted."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,20}", value):
        return max(0, int(value))
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return max(0, int(value))
    return None


def _error_kind(error):
    # Classify from exception types only. Never stringify exceptions or retain them.
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ConnectionError):
        return "connection"
    if isinstance(error, PermissionError):
        return "permission"
    if isinstance(error, (ValueError, TypeError, KeyError)):
        return "validation"
    return {
        "APITimeoutError": "timeout", "ReadTimeout": "timeout",
        "ConnectTimeout": "timeout", "TimeoutException": "timeout",
        "APIConnectionError": "connection", "ConnectError": "connection",
        "RateLimitError": "rate_limit", "AuthenticationError": "authentication",
        "PermissionDeniedError": "permission", "ValidationError": "validation",
    }.get(type(error).__name__, "internal")


@dataclass
class Span:
    kind: str
    name: str
    duration_ms: float | None = None
    error_kind: str | None = None
    _started: float = field(default_factory=monotonic, repr=False)

    def _finish(self, error_kind=None):
        self.duration_ms = max(0.0, (monotonic() - self._started) * 1000)
        self.error_kind = error_kind

    def _summary(self):
        return {
            "kind": self.kind, "name": self.name,
            "duration_ms": self.duration_ms, "error_kind": self.error_kind,
        }


class Trace:
    def __init__(self, trace_id=None):
        self.trace_id = _trace_id(trace_id)
        self._started = monotonic()
        self._ended = None
        self._spans = []
        self._dropped_spans = 0
        self._input = None
        self._output = None
        self._errors = set()
        self._lock = RLock()

    @contextmanager
    def span(self, kind, name):
        item = Span(kind if kind in _KINDS else "other", _label(name))
        error = None
        try:
            yield item
        except BaseException as exc:
            error = _error_kind(exc)
            raise
        finally:
            self._finish_span(item, error)

    def _finish_span(self, item, error=None):
        item._finish(error)
        with self._lock:
            # Bound retained detail even if a model enters an unexpectedly long loop.
            if len(self._spans) < 512:
                self._spans.append(item)
            else:
                self._dropped_spans += 1
            if error:
                self._errors.add(error)

    def record_usage(self, input_tokens=None, output_tokens=None):
        inputs, outputs = _tokens(input_tokens), _tokens(output_tokens)
        with self._lock:
            if inputs is not None:
                self._input = (self._input or 0) + inputs
            if outputs is not None:
                self._output = (self._output or 0) + outputs

    def record_error(self, kind):
        with self._lock:
            self._errors.add(kind if isinstance(kind, str) and kind in _ERROR_KINDS else "internal")

    def summary(self):
        with self._lock:
            total = None if self._input is None or self._output is None else self._input + self._output
            ended = self._ended if self._ended is not None else monotonic()
            return {
                "trace_id": self.trace_id,
                "duration_ms": max(0.0, (ended - self._started) * 1000),
                "spans": [item._summary() for item in self._spans],
                "dropped_spans": self._dropped_spans,
                "tokens": {
                    "input_tokens": self._input, "output_tokens": self._output,
                    "total_tokens": total,
                    "reported": self._input is not None or self._output is not None,
                },
                "error_kinds": sorted(self._errors),
            }


@contextmanager
def trace_scope(trace_id=None):
    trace = Trace(trace_id)
    token = _CURRENT.set(trace)
    try:
        yield trace
    except BaseException as exc:
        trace.record_error(_error_kind(exc))
        raise
    finally:
        with trace._lock:
            trace._ended = monotonic()
        _CURRENT.reset(token)
        try:
            LOGGER.info(json.dumps({"event": "trace_summary", **trace.summary()}, separators=(",", ":")))
        except Exception:
            # A misconfigured logging sink must not break a customer request.
            pass


@contextmanager
def span(kind, name):
    trace = _CURRENT.get()
    if trace is None:
        # Instrumentation is safe in standalone scripts without a request scope.
        item = Span(kind if kind in _KINDS else "other", _label(name))
        error = None
        try:
            yield item
        except BaseException as exc:
            error = _error_kind(exc)
            raise
        finally:
            item._finish(error)
    else:
        with trace.span(kind, name) as item:
            yield item


def record_usage(input_tokens=None, output_tokens=None):
    trace = _CURRENT.get()
    if trace is not None:
        trace.record_usage(input_tokens, output_tokens)


def record_error(kind):
    trace = _CURRENT.get()
    if trace is not None:
        trace.record_error(kind)


def instrument(kind, name):
    """Time a sync/async callable while retaining its signature and return value."""
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def async_wrapped(*args, **kwargs):
                with span(kind, name):
                    return await function(*args, **kwargs)
            return async_wrapped

        @wraps(function)
        def wrapped(*args, **kwargs):
            with span(kind, name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


class TelemetryCallback(BaseCallbackHandler):
    """LangChain adapter. Use one callback per request or share it safely.

    ``run_inline`` preserves the active ContextVar when LangChain invokes sync
    handlers from async code. The trace is captured at start, so finish events
    in a different execution context still update the correct request.
    """

    run_inline = True
    raise_error = False

    def __init__(self):
        super().__init__()
        self._runs = {}
        self._lock = RLock()

    def _start(self, run_id):
        trace = _CURRENT.get()
        if trace is None:
            return
        with self._lock:
            # Duplicate chat/llm start notifications must not reset elapsed time.
            if run_id not in self._runs:
                self._runs[run_id] = (trace, Span("llm", "model"))

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._start(run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start(run_id)

    def _pop(self, run_id):
        with self._lock:
            return self._runs.pop(run_id, None)

    def on_llm_end(self, response, *, run_id, **kwargs):
        pending = self._pop(run_id)
        if pending is None:
            return
        trace, item = pending
        inputs, outputs = self._usage(response)
        trace.record_usage(inputs, outputs)
        trace._finish_span(item)

    def on_llm_error(self, error, *, run_id, **kwargs):
        pending = self._pop(run_id)
        if pending is not None:
            trace, item = pending
            trace._finish_span(item, _error_kind(error))

    @staticmethod
    def _usage(response):
        inputs = outputs = None
        groups = getattr(response, "generations", None)
        if isinstance(groups, (list, tuple)):
            for group in groups:
                if not isinstance(group, (list, tuple)) or not group:
                    continue
                # Additional candidate generations share the same model call.
                message = getattr(group[0], "message", None)
                usage = getattr(message, "usage_metadata", None)
                if isinstance(usage, Mapping):
                    value = _tokens(usage.get("input_tokens"))
                    if value is not None:
                        inputs = (inputs or 0) + value
                    value = _tokens(usage.get("output_tokens"))
                    if value is not None:
                        outputs = (outputs or 0) + value
        if inputs is None and outputs is None:
            output = getattr(response, "llm_output", None)
            usage = output.get("token_usage") if isinstance(output, Mapping) else None
            if isinstance(usage, Mapping):
                inputs = _tokens(usage.get("prompt_tokens", usage.get("input_tokens")))
                outputs = _tokens(usage.get("completion_tokens", usage.get("output_tokens")))
        return inputs, outputs


def current_trace():
    return _CURRENT.get()
