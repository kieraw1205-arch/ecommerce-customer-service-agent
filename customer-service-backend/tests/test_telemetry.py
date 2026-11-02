import asyncio
import io
import json
import logging
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from my_agent import telemetry as t
except ModuleNotFoundError:
    t = None


def response(*messages, usage=None):
    return SimpleNamespace(
        generations=[[SimpleNamespace(message=m) for m in messages]],
        llm_output={} if usage is None else {"token_usage": usage},
    )


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(t, "telemetry module is not implemented")

    def test_absent_usage_differs_from_reported_zero(self):
        with t.trace_scope() as trace:
            self.assertEqual(trace.summary()["tokens"], {
                "input_tokens": None, "output_tokens": None,
                "total_tokens": None, "reported": False,
            })
            t.record_usage(0, 0)
        self.assertEqual(trace.summary()["tokens"], {
            "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "reported": True,
        })

    def test_malformed_usage_does_not_inflate_or_raise(self):
        with t.trace_scope() as trace:
            t.record_usage("7", 2)
            t.record_usage(-5, "not a number")
            t.record_usage(True, float("inf"))
            t.record_usage({}, 3.5)
        self.assertEqual(trace.summary()["tokens"]["input_tokens"], 7)
        self.assertEqual(trace.summary()["tokens"]["output_tokens"], 2)
        self.assertEqual(trace.summary()["tokens"]["total_tokens"], 9)

    def test_partial_usage_remains_unknown_on_unreported_side(self):
        with t.trace_scope() as trace:
            t.record_usage(5, None)
        self.assertEqual(trace.summary()["tokens"]["input_tokens"], 5)
        self.assertIsNone(trace.summary()["tokens"]["output_tokens"])
        self.assertIsNone(trace.summary()["tokens"]["total_tokens"])

    def test_span_records_monotonic_duration_and_safe_failure(self):
        with t.trace_scope() as trace:
            with self.assertRaisesRegex(TimeoutError, "private credential"):
                with t.span("api", "lookup_order") as item:
                    time.sleep(0.001)
                    raise TimeoutError("private credential")
        row = trace.summary()["spans"][0]
        self.assertEqual(row["kind"], "api")
        self.assertEqual(row["name"], "lookup_order")
        self.assertEqual(row["error_kind"], "timeout")
        self.assertGreater(row["duration_ms"], 0)
        self.assertEqual(item.error_kind, "timeout")
        self.assertEqual(trace.summary()["error_kinds"], ["timeout"])
        self.assertNotIn("private credential", json.dumps(trace.summary()))

    def test_trace_logs_structured_summary_and_no_private_payloads(self):
        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        logger = logging.getLogger("my_agent.telemetry")
        previous = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            with self.assertRaises(ValueError):
                with t.trace_scope() as trace:
                    raise ValueError("PROMPT credential=TOPSECRET")
            emitted = json.loads(capture.getvalue())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        self.assertEqual(emitted["event"], "trace_summary")
        self.assertEqual(emitted["trace_id"], trace.trace_id)
        self.assertEqual(emitted["error_kinds"], ["validation"])
        self.assertNotIn("TOPSECRET", capture.getvalue())
        self.assertNotIn("PROMPT", capture.getvalue())

    def test_opaque_ids_preserved_and_unsafe_labels_redacted(self):
        opaque_id = uuid4().hex
        with t.trace_scope(opaque_id) as trace:
            with t.span("api?secret=foo", "GET /orders?customer=private"):
                pass
            t.record_error("private password")
        row = trace.summary()["spans"][0]
        self.assertEqual(trace.trace_id, opaque_id)
        self.assertEqual(row["kind"], "other")
        self.assertEqual(row["name"], "other")
        self.assertEqual(trace.summary()["error_kinds"], ["internal"])

    def test_nested_traces_restore_outer_and_snapshots_are_detached(self):
        with t.trace_scope() as outer:
            t.record_usage(1, 2)
            with t.trace_scope() as inner:
                t.record_usage(10, 20)
            t.record_usage(3, 4)
        self.assertNotEqual(outer.trace_id, inner.trace_id)
        self.assertEqual(outer.summary()["tokens"]["total_tokens"], 10)
        self.assertEqual(inner.summary()["tokens"]["total_tokens"], 30)
        old = outer.summary()
        old["tokens"]["total_tokens"] = 999
        self.assertEqual(outer.summary()["tokens"]["total_tokens"], 10)
        t.record_usage(100, 100)  # No active request is harmless.
        self.assertEqual(outer.summary()["tokens"]["total_tokens"], 10)

    def test_concurrent_async_requests_do_not_share_tokens(self):
        async def worker(value):
            with t.trace_scope() as trace:
                await asyncio.sleep(0)
                t.record_usage(value, 1)
                await asyncio.sleep(0)
            return trace.summary()["tokens"]["total_tokens"]

        async def run():
            return await asyncio.gather(worker(10), worker(20))

        self.assertEqual(asyncio.run(run()), [11, 21])

    def test_callback_counts_usage_metadata_once_even_with_fallback(self):
        callback = t.TelemetryCallback()
        run_id = uuid4()
        with t.trace_scope() as trace:
            callback.on_chat_model_start({}, [["PROMPT SECRET"]], run_id=run_id)
            result = response(SimpleNamespace(usage_metadata={
                "input_tokens": 3, "output_tokens": 4, "total_tokens": 7,
            }), usage={"prompt_tokens": 3, "completion_tokens": 4})
            callback.on_llm_end(result, run_id=run_id)
            callback.on_llm_end(result, run_id=run_id)
        summary = trace.summary()
        self.assertEqual(summary["tokens"]["total_tokens"], 7)
        self.assertEqual(len(summary["spans"]), 1)
        self.assertEqual(summary["spans"][0]["kind"], "llm")
        self.assertNotIn("SECRET", json.dumps(summary))

    def test_callback_uses_provider_fallback_and_zero(self):
        callback = t.TelemetryCallback()
        with t.trace_scope() as trace:
            run_id = uuid4()
            callback.on_llm_start({}, ["SECRET"], run_id=run_id)
            callback.on_llm_end(response(usage={
                "prompt_tokens": 0, "completion_tokens": 0,
            }), run_id=run_id)
        self.assertEqual(trace.summary()["tokens"]["total_tokens"], 0)
        self.assertTrue(trace.summary()["tokens"]["reported"])

    def test_callback_unreported_usage_stays_unknown(self):
        callback = t.TelemetryCallback()
        with t.trace_scope() as trace:
            run_id = uuid4()
            callback.on_llm_start({}, [], run_id=run_id)
            callback.on_llm_end(response(), run_id=run_id)
        self.assertFalse(trace.summary()["tokens"]["reported"])

    def test_callback_captures_start_trace_across_request_contexts(self):
        callback = t.TelemetryCallback()
        run_id = uuid4()
        with t.trace_scope() as outer:
            callback.on_llm_start({}, [], run_id=run_id)
            with t.trace_scope() as inner:
                callback.on_llm_end(response(usage={
                    "prompt_tokens": 8, "completion_tokens": 9,
                }), run_id=run_id)
        self.assertEqual(outer.summary()["tokens"]["total_tokens"], 17)
        self.assertFalse(inner.summary()["tokens"]["reported"])

    def test_callback_error_never_stores_raw_error_and_clears_run(self):
        callback = t.TelemetryCallback()
        run_id = uuid4()
        with t.trace_scope() as trace:
            callback.on_llm_start({}, [], run_id=run_id)
            callback.on_llm_error(ConnectionError("SECRET API KEY"), run_id=run_id)
            callback.on_llm_error(ConnectionError("SECRET API KEY"), run_id=run_id)
        self.assertEqual(trace.summary()["error_kinds"], ["connection"])
        self.assertEqual(len(trace.summary()["spans"]), 1)
        self.assertNotIn("SECRET", json.dumps(trace.summary()))

    def test_callback_sums_separate_batch_messages(self):
        callback = t.TelemetryCallback()
        with t.trace_scope() as trace:
            run_id = uuid4()
            callback.on_llm_start({}, [], run_id=run_id)
            callback.on_llm_end(SimpleNamespace(generations=[
                [SimpleNamespace(message=SimpleNamespace(usage_metadata={
                    "input_tokens": 2, "output_tokens": 1}))],
                [SimpleNamespace(message=SimpleNamespace(usage_metadata={
                    "input_tokens": 3, "output_tokens": 2}))],
            ], llm_output=None), run_id=run_id)
        self.assertEqual(trace.summary()["tokens"]["total_tokens"], 8)

    def test_instrument_preserves_sync_arguments_result_and_signature(self):
        @t.instrument("node", "intent")
        def operation(value, *, amount=2):
            """Original operation."""
            return value + amount

        with t.trace_scope() as trace:
            self.assertEqual(operation(3, amount=4), 7)
        self.assertEqual(operation.__name__, "operation")
        self.assertEqual(operation.__doc__, "Original operation.")
        self.assertEqual(trace.summary()["spans"][0]["name"], "intent")

    def test_instrument_times_awaited_async_body_and_failure(self):
        @t.instrument("api", "lookup_order")
        async def operation():
            await asyncio.sleep(0.001)
            raise TimeoutError("SECRET")

        async def run():
            with t.trace_scope() as trace:
                with self.assertRaises(TimeoutError):
                    await operation()
            return trace.summary()

        result = asyncio.run(run())
        self.assertEqual(result["error_kinds"], ["timeout"])
        self.assertGreater(result["spans"][0]["duration_ms"], 0)

    def test_span_without_trace_preserves_failure_and_classifies_it(self):
        with self.assertRaises(PermissionError):
            with t.span("tool", "lookup_order") as item:
                raise PermissionError("SECRET")
        self.assertEqual(item.error_kind, "permission")

    def test_invalid_trace_id_cannot_echo_private_data(self):
        with t.trace_scope("customer@example.com") as trace:
            pass
        self.assertNotIn("customer", json.dumps(trace.summary()))
        self.assertEqual(len(trace.trace_id), 32)


if __name__ == "__main__":
    unittest.main()
