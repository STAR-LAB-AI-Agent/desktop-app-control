import io
import json
import threading
import time
import unittest
from unittest.mock import patch

from desktop_agent.vision import DeepSeekVisionLocator
from desktop_agent.tools.monitor import TaskCancelledError


class VisionApiTests(unittest.TestCase):
    def test_text_json_request_uses_text_only_message(self) -> None:
        response = io.BytesIO(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"route": "general"},
                                    ensure_ascii=False,
                                )
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            ).encode("utf-8")
        )
        locator = DeepSeekVisionLocator(api_key="test-key")

        with patch(
            "desktop_agent.vision.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = locator.ask_text_json("选择路由")

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, {"route": "general"})
        self.assertEqual(
            payload["messages"],
            [{"role": "user", "content": "选择路由"}],
        )
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_connection_reset_is_retried(self) -> None:
        response = io.BytesIO(
            json.dumps({
                "choices": [{"message": {"content": '{"route":"general"}'}}]
            }).encode("utf-8")
        )
        locator = DeepSeekVisionLocator(
            api_key="test-key", max_retries=2, retry_backoff=0,
        )
        with patch(
            "desktop_agent.vision.urllib.request.urlopen",
            side_effect=[ConnectionResetError(10054, "connection reset"), response],
        ) as urlopen:
            result = locator.ask_text_json("选择路由")
        self.assertEqual(result, {"route": "general"})
        self.assertEqual(urlopen.call_count, 2)

    def test_api_wait_can_be_cancelled_immediately(self) -> None:
        started = threading.Event()

        def slow_urlopen(*_args, **_kwargs):
            started.set()
            time.sleep(0.5)
            return io.BytesIO(b'{}')

        def cancel_check() -> None:
            if started.is_set():
                raise TaskCancelledError("任务已由用户终止")

        locator = DeepSeekVisionLocator(
            api_key="test-key", cancel_check=cancel_check,
        )
        began = time.monotonic()
        with patch("desktop_agent.vision.urllib.request.urlopen", side_effect=slow_urlopen):
            with self.assertRaises(TaskCancelledError):
                locator.ask_text_json("选择路由")
        self.assertLess(time.monotonic() - began, 0.3)


if __name__ == "__main__":
    unittest.main()
