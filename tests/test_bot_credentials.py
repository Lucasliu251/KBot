import configparser
import tempfile
import unittest
from pathlib import Path

from bot_credentials import load_ini_token
from scripts.check_kook_secrets import token_lines


class CredentialTests(unittest.TestCase):
    def test_ini_case_and_punctuation_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[Kook]\nToken = test+/=value%not-interpolated\n')
            self.assertEqual(load_ini_token(path, 'Kook'), 'test+/=value%not-interpolated')

    def test_missing_and_placeholder_fail_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            with self.assertRaises(RuntimeError):
                load_ini_token(path)
            for content in ['[kook]\nToken=\n', '[kook]\nToken=your_bot_token\n', '[other]\nToken=test-value\n']:
                path.write_text(content)
                with self.assertRaises(RuntimeError):
                    load_ini_token(path)

    def test_parse_error_does_not_disclose_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('private-value-not-for-logs\n')
            with self.assertRaises(RuntimeError) as caught:
                load_ini_token(path)
            self.assertNotIn('private-value-not-for-logs', str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_configuration_paths_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'bot-{index}.ini' for index in range(2)]
            for index, path in enumerate(paths):
                path.write_text(f'[kook]\nToken = dummy-{index}\n')
            self.assertEqual([load_ini_token(path) for path in paths], ['dummy-0', 'dummy-1'])

    def test_secret_detection_and_non_token_control(self):
        # Assemble a synthetic format fixture, never a functioning credential.
        token = b'1/' + b'MTIzNA==' + b'/' + b'x' * 22 + b'=='
        self.assertEqual(list(token_lines(b'first line\n' + token)), [2])
        self.assertEqual(list(token_lines(b'not-a-token; your_bot_token_here')), [])


if __name__ == '__main__':
    unittest.main()
