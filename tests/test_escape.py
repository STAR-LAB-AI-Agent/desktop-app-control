import unittest
from unittest.mock import patch

from desktop_agent.escape import EscapeStopListener


class EscapeStopListenerTests(unittest.TestCase):
    def test_short_escape_press_triggers_cancel(self) -> None:
        calls = []
        listener = None

        def cancel() -> None:
            calls.append(True)
            listener._stop_event.set()

        listener = EscapeStopListener(cancel, poll_interval=0.01)
        # 低位表示 Esc 在两次轮询之间被短暂按下，即使此刻已经松开也应捕获。
        with patch(
            "desktop_agent.escape.ctypes.windll.user32.GetAsyncKeyState",
            return_value=0x0001,
        ):
            listener._run()

        self.assertEqual(calls, [True])
        self.assertTrue(listener.triggered.is_set())


if __name__ == "__main__":
    unittest.main()
