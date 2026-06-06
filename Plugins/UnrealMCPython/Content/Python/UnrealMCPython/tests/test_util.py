from UnrealMCPython.tests.base import MCPTestCase


class TestUtilActions(MCPTestCase):

    def test_get_output_log_default(self):
        r = self.call("util_actions", "ue_get_output_log", line_count=10)
        self.assertSuccess(r)
        self.assertIn("log", r)
        self.assertIn("total_lines", r)
        self.assertIn("returned_lines", r)

    def test_get_output_log_with_keyword(self):
        r = self.call("util_actions", "ue_get_output_log", line_count=20, keyword="LogMCPython")
        self.assertSuccess(r)
        self.assertIn("log", r)

    def test_print_message(self):
        r = self.call("util_actions", "ue_print_message", message="MCP unittest ping")
        self.assertSuccess(r)
        self.assertEqual(r["received_message"], "MCP unittest ping")

    def test_print_message_missing_param(self):
        r = self.call("util_actions", "ue_print_message")
        self.assertFalse(r.get("success"))
