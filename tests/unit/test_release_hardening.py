"""Unit tests for Neuron AI v0.1.0 Release Hardening.

Covers:
1. Version metadata consistency (0.1.0, Neuron AI, NeuronAI).
2. Windows Credential Manager abstraction and MemoryCredentialStore.
3. User non-secret configuration (%LOCALAPPDATA%/NeuronAI/config.json) & secret rejection.
4. Resource path abstraction in source mode and simulated PyInstaller packaged mode.
5. Bundled faster-whisper model resolution and controlled missing-model error.
6. Settings resolution precedence: Environment variables -> .env -> CredentialStore.
7. First-run setup decision logic and dialog flow with mock connection test.
8. PyInstaller spec security verification (.env exclusion, no pynput).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config.credentials import (
    MemoryCredentialStore,
    TARGET_ELEVENLABS,
    TARGET_GEMINI,
    delete_api_credentials,
    get_elevenlabs_api_key,
    get_gemini_api_key,
    save_api_credentials,
    set_credential_store,
)
from app.config.settings import NeuronSettings
from app.config.user_config import (
    get_user_voice_id,
    load_user_config,
    save_user_config,
    set_user_voice_id,
)
from app.stt.errors import STTUnavailableError
from app.stt.whisper_stt import LocalWhisperSTTAdapter
from app.utils.paths import (
    get_app_icon_path,
    get_app_root,
    get_resource_path,
    get_user_config_path,
    get_user_data_dir,
    is_packaged,
    resolve_whisper_model_path,
)
from app.version import EXECUTABLE_NAME, PRODUCT_NAME, VERSION, __version__


class TestVersionMetadata(unittest.TestCase):
    """Verify single source of truth for version and product naming."""

    def test_version_values(self):
        self.assertEqual(__version__, "0.1.0")
        self.assertEqual(VERSION, "0.1.0")
        self.assertEqual(PRODUCT_NAME, "Neuron AI")
        self.assertEqual(EXECUTABLE_NAME, "NeuronAI")

    def test_app_package_exports(self):
        import app

        self.assertEqual(app.__version__, "0.1.0")
        self.assertEqual(app.PRODUCT_NAME, "Neuron AI")
        self.assertEqual(app.EXECUTABLE_NAME, "NeuronAI")


class TestCredentialStoreAbstraction(unittest.TestCase):
    """Verify CredentialStore behavior without exposing secrets."""

    def setUp(self):
        self.mem_store = MemoryCredentialStore()
        set_credential_store(self.mem_store)

    def tearDown(self):
        set_credential_store(None)

    def test_memory_store_crud(self):
        self.assertIsNone(self.mem_store.get_credential("test/target"))
        self.assertTrue(self.mem_store.set_credential("test/target", "secret_value_123"))
        self.assertEqual(self.mem_store.get_credential("test/target"), "secret_value_123")
        self.assertTrue(self.mem_store.delete_credential("test/target"))
        self.assertIsNone(self.mem_store.get_credential("test/target"))

    def test_save_and_retrieve_api_credentials(self):
        self.assertTrue(save_api_credentials("gemini_secret_key", "eleven_secret_key"))
        self.assertEqual(get_gemini_api_key(), "gemini_secret_key")
        self.assertEqual(get_elevenlabs_api_key(), "eleven_secret_key")

        self.assertTrue(delete_api_credentials())
        self.assertIsNone(get_gemini_api_key())
        self.assertIsNone(get_elevenlabs_api_key())

    def test_empty_secret_rejected(self):
        self.assertFalse(self.mem_store.set_credential("test/target", ""))


class TestUserConfig(unittest.TestCase):
    """Verify non-secret user configuration at %LOCALAPPDATA%/NeuronAI/config.json."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_user_config(self):
        cfg = {"elevenlabs_voice_id": "test_voice_abc", "whisper_model": "base.en"}
        self.assertTrue(save_user_config(cfg, config_path=self.config_file))

        loaded = load_user_config(config_path=self.config_file)
        self.assertEqual(loaded.get("elevenlabs_voice_id"), "test_voice_abc")
        self.assertEqual(loaded.get("whisper_model"), "base.en")

    def test_secret_key_rejection(self):
        """Active safety check: config.json must reject any secret or API key."""
        with self.assertRaises(ValueError) as ctx:
            save_user_config({"gemini_api_key": "fake_secret_key"}, config_path=self.config_file)
        self.assertIn("Security violation", str(ctx.exception))

        with self.assertRaises(ValueError):
            save_user_config({"user_token": "token123"}, config_path=self.config_file)

    def test_voice_id_helpers(self):
        self.assertTrue(set_user_voice_id("voice_xyz", config_path=self.config_file))
        self.assertEqual(get_user_voice_id(config_path=self.config_file), "voice_xyz")

    def test_corrupt_config_file_returns_empty(self):
        with open(self.config_file, "w") as f:
            f.write("NOT_VALID_JSON{{{")
        loaded = load_user_config(config_path=self.config_file)
        self.assertEqual(loaded, {})


class TestPathsAndResourceResolution(unittest.TestCase):
    """Verify portable resource path resolution in source mode and simulated packaged mode."""

    def test_source_mode_resolution(self):
        """In development mode, paths resolve relative to the repository root."""
        self.assertFalse(is_packaged())
        root = get_app_root()
        self.assertTrue(os.path.isabs(root))
        self.assertTrue(os.path.exists(os.path.join(root, "app")))

        res_path = get_resource_path("demo")
        self.assertTrue(os.path.isabs(res_path))
        self.assertTrue(res_path.endswith("demo"))

    def test_simulated_packaged_mode_resolution(self):
        """In packaged mode, paths resolve relative to sys._MEIPASS."""
        mock_meipass = r"C:\fake\frozen_bundle"
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "_MEIPASS", mock_meipass, create=True):
                self.assertTrue(is_packaged())
                root = get_app_root()
                self.assertEqual(root, mock_meipass)
                res = get_resource_path("models/faster-whisper-base.en")
                self.assertEqual(res, os.path.normpath(r"C:\fake\frozen_bundle\models\faster-whisper-base.en"))

    def test_whisper_bundled_model_selection(self):
        """resolve_whisper_model_path selects bundled folder if present, or base.en in dev mode."""
        # When bundled folder does not exist and not packaged -> 'base.en'
        res = resolve_whisper_model_path("base.en")
        self.assertEqual(res, "base.en")

        # In simulated packaged mode when bundled folder missing -> returns expected bundled path
        mock_meipass = r"C:\fake\bundle"
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "_MEIPASS", mock_meipass, create=True):
                bundled = resolve_whisper_model_path("base.en")
                self.assertEqual(bundled, os.path.normpath(r"C:\fake\bundle\models\faster-whisper-base.en"))

    def test_brand_icon_path_fallback(self):
        """get_app_icon_path returns None when assets/neuron.ico is absent."""
        icon = get_app_icon_path()
        # Either None (if neuron.ico not yet added) or an existing file
        if icon is not None:
            self.assertTrue(os.path.isfile(icon))


class TestWhisperBundledModelAdapter(unittest.TestCase):
    """Verify STT adapter behavior with bundled models and controlled error handling."""

    def test_packaged_missing_bundled_model_raises_controlled_error(self):
        """Packaged execution with missing bundled model raises STTUnavailableError, not a crash."""
        with patch("app.utils.paths.is_packaged", return_value=True):
            adapter = LocalWhisperSTTAdapter(model_size_or_path=r"C:\nonexistent\model_dir")
            with self.assertRaises(STTUnavailableError) as ctx:
                adapter._get_model()
            self.assertIn("Bundled faster-whisper model directory not found", str(ctx.exception))


class TestSettingsAndFirstRunDecision(unittest.TestCase):
    """Verify credentials precedence and first-run dialog triggers."""

    def setUp(self):
        self.mem_store = MemoryCredentialStore()
        set_credential_store(self.mem_store)

    def tearDown(self):
        set_credential_store(None)

    def test_settings_retrieves_from_credential_store_when_env_empty(self):
        self.mem_store.set_credential(TARGET_GEMINI, "cred_gemini_key_123")
        self.mem_store.set_credential(TARGET_ELEVENLABS, "cred_eleven_key_456")

        # Mock os.environ to have no API keys
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.config.settings._load_env_file", return_value={}):
                settings = NeuronSettings.from_env(env_file="nonexistent.env")
                self.assertEqual(settings.gemini_api_key, "cred_gemini_key_123")
                self.assertEqual(settings.elevenlabs_api_key, "cred_eleven_key_456")
                self.assertTrue(settings.has_required_credentials())

    def test_settings_missing_credentials_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.config.settings._load_env_file", return_value={}):
                settings = NeuronSettings.from_env(env_file="nonexistent.env")
                self.assertFalse(settings.has_required_credentials())

    def test_first_run_dialog_bypassed_when_credentials_present(self):
        from app.desktop.setup_dialog import show_first_run_dialog_if_needed

        with patch("app.desktop.setup_dialog.get_settings") as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.has_required_credentials.return_value = True
            mock_get_settings.return_value = mock_settings

            result = show_first_run_dialog_if_needed()
            self.assertTrue(result)


class TestPyInstallerSpecSecurity(unittest.TestCase):
    """Verify neuron.spec security rules and dependencies."""

    def test_neuron_spec_excludes_dot_env_and_pynput(self):
        spec_path = os.path.join(get_app_root(), "neuron.spec")
        self.assertTrue(os.path.exists(spec_path))

        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()

        # pynput must NOT be in hidden imports
        self.assertNotIn("'pynput'", content)
        self.assertNotIn("'pynput.keyboard'", content)

        # Security check: explicit filtering of .env
        self.assertIn("'.env'", content)
        self.assertIn("sanitized_datas", content)


class TestFirstRunSetupDialog(unittest.TestCase):
    """Verify first-run setup dialog UI and save flows."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.mem_store = MemoryCredentialStore()
        set_credential_store(self.mem_store)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        set_credential_store(None)
        self.temp_dir.cleanup()

    def test_dialog_ui_components_and_password_masking(self):
        from PySide6.QtWidgets import QLineEdit
        from app.desktop.setup_dialog import FirstRunSetupDialog

        dialog = FirstRunSetupDialog()
        self.assertEqual(dialog._gemini_input.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(dialog._eleven_input.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(dialog._voice_input.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertIn("Welcome to Neuron AI", dialog.windowTitle())
        dialog.close()

    def test_dialog_test_connection_and_save_flow(self):
        from app.desktop.setup_dialog import FirstRunSetupDialog

        mock_tester = MagicMock(return_value=(True, "Mock connection succeeded!"))
        dialog = FirstRunSetupDialog(connection_tester=mock_tester)

        dialog._gemini_input.setText("mock_gemini_key_12345")
        dialog._eleven_input.setText("mock_eleven_key_12345")
        dialog._voice_input.setText("mock_voice_123")

        # Test connection button
        dialog._on_test_connection()
        mock_tester.assert_called_once_with("mock_gemini_key_12345", "mock_eleven_key_12345")
        self.assertIn("Mock connection succeeded", dialog._status_label.text())

        # Save & start button
        with patch("app.desktop.setup_dialog.set_user_voice_id") as mock_set_voice:
            with patch.object(dialog, "accept") as mock_accept:
                dialog._on_save_and_start()
                mock_set_voice.assert_called_once_with(voice_id="mock_voice_123")
                mock_accept.assert_called_once()

        self.assertEqual(get_gemini_api_key(), "mock_gemini_key_12345")
        self.assertEqual(get_elevenlabs_api_key(), "mock_eleven_key_12345")
        dialog.close()


if __name__ == "__main__":
    unittest.main()

