import unittest

from reasonable.editor.project_page import _kill_process_tree


class ProcessStopTests(unittest.TestCase):
    def test_direct_process_is_always_killed(self) -> None:
        class FakeProcess:
            killed = False

            def processId(self) -> int:
                return 0

            def kill(self) -> None:
                self.killed = True

        process = FakeProcess()
        _kill_process_tree(process)  # type: ignore[arg-type]
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
