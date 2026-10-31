import unittest

from app.launch import inference_arguments


class ConfigurationTests(unittest.TestCase):
    def test_configmap_cannot_override_privacy_or_authentication(self):
        for key in ("api_key", "enable_log_requests", "enable_log_outputs", "middleware", "model", "trust_remote_code"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                inference_arguments({key: "unsafe"})

    def test_invalid_resource_limits_are_rejected(self):
        for value in (0, -1, True, "2048"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inference_arguments({"max_model_len": value})


if __name__ == "__main__":
    unittest.main()
