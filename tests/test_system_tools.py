import unittest

from desktop_agent.tools.system import SystemTools


class SystemToolsTests(unittest.TestCase):
    def test_sleep_is_registered_as_a_long_wait(self) -> None:
        tools = SystemTools()
        specs = {spec.name: spec for spec in tools.specs()}
        self.assertIn("sleep", specs)
        self.assertEqual(specs["sleep"].parameters["properties"]["seconds"]["maximum"], 120)
        self.assertEqual(tools.sleep(0), {"ok": True, "seconds": 0, "kind": "long_wait"})

    def test_sleep_checks_for_cancellation(self) -> None:
        class Cancelled(RuntimeError):
            pass

        checks = 0

        def cancel_check() -> None:
            nonlocal checks
            checks += 1
            raise Cancelled("cancelled")

        with self.assertRaises(Cancelled):
            SystemTools(cancel_check=cancel_check).sleep(30)
        self.assertEqual(checks, 1)


if __name__ == "__main__":
    unittest.main()
