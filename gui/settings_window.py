"""
Settings window - edits %LOCALAPPDATA%\\JARVIS\\config.json.

Real audio device dropdowns (input + output), Refresh, live Test Microphone
(3 s recording + input-level meter + non-silence check) and Test Speaker
(Piper). OpenRouter secrets are protected with the current user's Windows DPAPI.
"""
import numpy as np
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox,
    QDoubleSpinBox, QVBoxLayout, QHBoxLayout, QFormLayout, QFileDialog,
    QDialogButtonBox, QTabWidget, QWidget, QProgressBar, QMessageBox,
)


class SettingsWindow(QDialog):
    hermes_probe_completed = Signal(object)
    openrouter_completed = Signal(object)

    def __init__(self, settings_store, gui_controller=None, parent=None):
        super().__init__(parent)
        self.store = settings_store
        self.gc = gui_controller
        self.setWindowTitle("JARVIS Settings")
        self.setMinimumWidth(560)
        self._widgets = {}
        self._test_stream = None
        self._test_frames = []
        self._test_timer = None
        self._hermes_probe_running = False
        self._openrouter_request_running = False
        self.hermes_probe_completed.connect(self._apply_hermes_probe)
        self.openrouter_completed.connect(self._apply_openrouter_result)
        self._build()
        self._load()
        self._populate_devices()
        self._on_test_hermes()

    # ================================================================== UI
    def _build(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._audio_tab(), "Audio")
        tabs.addTab(self._assistant_tab(), "Assistant")
        tabs.addTab(self._accounts_tab(), "Accounts")
        tabs.addTab(self._hermes_tab(), "Hermes Engine")
        tabs.addTab(self._system_tab(), "System")
        root.addWidget(tabs)
        bridge = getattr(self.gc, "bridge", None)
        if bridge is not None and hasattr(bridge, "account_connection_changed"):
            bridge.account_connection_changed.connect(self._on_account_connection)
        if bridge is not None and hasattr(bridge, "hermes_configuration_changed"):
            bridge.hermes_configuration_changed.connect(self._on_hermes_configuration)

        note = QLabel("OpenRouter keys are protected for this Windows user and are never written to config.json.")
        note.setObjectName("statusLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _audio_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        # microphone dropdown + refresh + test
        self.mic_combo = QComboBox()
        form.addRow(QLabel("Microphone device"), self.mic_combo)
        self._widgets["microphone_device"] = ("combo", self.mic_combo)

        self.spk_combo = QComboBox()
        form.addRow(QLabel("Speaker device"), self.spk_combo)
        self._widgets["speaker_device"] = ("combo", self.spk_combo)

        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh devices")
        self.btn_refresh.clicked.connect(self._populate_devices)
        self.btn_test_mic = QPushButton("Test Microphone")
        self.btn_test_mic.clicked.connect(self._on_test_mic)
        self.btn_test_spk = QPushButton("Test Speaker")
        self.btn_test_spk.clicked.connect(self._on_test_speaker)
        for b in (self.btn_refresh, self.btn_test_mic, self.btn_test_spk):
            btn_row.addWidget(b)
        form.addRow(btn_row)

        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setValue(0)
        form.addRow(QLabel("Input level"), self.level)
        self.mic_result = QLabel("-")
        self.mic_result.setObjectName("statusLabel")
        self.mic_result.setWordWrap(True)
        form.addRow(self.mic_result)

        self._add_line(form, "wake_word", "Wake word")
        self._add_spin(form, "wake_threshold", "Wake-word threshold", 0.1, 1.0, 0.05)
        self._add_combo(form, "whisper_model", "Whisper model",
                        ["tiny", "base", "small", "medium", "large-v3"])
        self._add_line(form, "piper_voice", "Piper voice model")
        self._add_check(form, "start_voice_automatically", "Start voice automatically")
        return w

    def _assistant_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        privacy = QLabel(
            "Connect your own OpenRouter account to use its available models. "
            "Your key is masked and stored only in the local Windows credential vault."
        )
        privacy.setObjectName("statusLabel")
        privacy.setWordWrap(True)
        form.addRow(privacy)
        self.openrouter_key = QLineEdit()
        self.openrouter_key.setEchoMode(QLineEdit.Password)
        self.openrouter_key.setPlaceholderText("sk-or-v1-…")
        form.addRow(QLabel("OpenRouter API key"), self.openrouter_key)
        self.btn_connect_openrouter = QPushButton("Connect OpenRouter")
        self.btn_connect_openrouter.clicked.connect(self._on_connect_openrouter)
        form.addRow(self.btn_connect_openrouter)
        self.openrouter_model_combo = QComboBox()
        self.openrouter_model_combo.setEditable(True)
        self.openrouter_model_combo.setEnabled(False)
        form.addRow(QLabel("OpenRouter model"), self.openrouter_model_combo)
        self._widgets["openrouter_model"] = ("combo", self.openrouter_model_combo)
        self.btn_refresh_models = QPushButton("Load available models")
        self.btn_refresh_models.clicked.connect(self._on_load_openrouter_models)
        self.btn_refresh_models.setEnabled(False)
        form.addRow(self.btn_refresh_models)
        self.conn_result = QLabel("Connect an OpenRouter key to load models.")
        self.conn_result.setObjectName("statusLabel")
        self.conn_result.setWordWrap(True)
        form.addRow(self.conn_result)
        self._add_combo(form, "browser_preference", "Browser preference",
                        ["edge", "chrome", "chromium"])
        self._add_combo(form, "theme", "Theme", ["cinematic"])
        self._add_check(form, "reduce_motion", "Reduce motion / animations")
        self._add_spin(form, "live_typing_speed", "Live typing delay (seconds)",
                       0.0, 0.25, 0.01)
        self._add_combo(form, "default_save_behavior", "Default save behavior",
                        ["ask", "research_folder"])
        self._add_combo(form, "confirmation_policy", "Confirmation policy",
                        ["risk_based", "always_confirm"])
        self._add_check(form, "conversation_mode_enabled", "Enable human conversation mode")
        self._add_check(form, "followup_listening_enabled", "Enable follow-up listening")
        self._add_check(form, "barge_in_enabled", "Enable barge-in interruption")
        self._add_spin(form, "silence_reminder_seconds", "First silence reminder (seconds)",
                       1.0, 120.0, 1.0)
        self._add_spin(form, "second_silence_reminder_seconds", "Second silence reminder (seconds)",
                       2.0, 180.0, 1.0)
        self._add_spin(form, "conversation_inactivity_timeout_seconds",
                       "Conversation inactivity timeout (seconds)", 5.0, 600.0, 5.0)
        self._add_spin(form, "silence_detection_seconds", "Silence detection duration (seconds)",
                       0.3, 5.0, 0.1)
        self._add_spin(form, "speech_start_threshold", "Speech start threshold (VAD frames)",
                       1.0, 12.0, 1.0)
        self._add_spin(form, "minimum_speech_seconds", "Minimum speech duration (seconds)",
                       0.0, 5.0, 0.05)
        self._add_spin(form, "maximum_recording_seconds", "Maximum recording duration (seconds)",
                       3.0, 300.0, 1.0)
        self._add_spin(form, "post_speech_listening_delay_seconds",
                       "Post-speech listening delay (seconds)", 0.0, 5.0, 0.05)
        self._add_spin(form, "background_noise_threshold", "Background noise threshold",
                       0.0, 1.0, 0.005)
        self._add_combo(form, "conversation_response_length", "Conversation response length",
                        ["concise", "normal", "detailed"])
        self._add_spin(form, "conversation_memory_limit", "Conversation memory limit (turns)",
                       4.0, 100.0, 1.0)
        self._add_check(form, "return_to_wake_after_inactivity",
                        "Return to wake word after inactivity")
        self._add_line(form, "conversation_exit_phrases", "Exit phrases")
        self._add_spin(form, "microphone_sensitivity", "Microphone sensitivity",
                       0.1, 5.0, 0.1)
        self._add_check(form, "echo_suppression_enabled", "Echo suppression")
        self._add_check(form, "background_noise_filtering_enabled",
                        "Background noise filtering")
        return w

    def _accounts_tab(self):
        """Provider-owned sign-in flows; passwords and tokens never enter JARVIS."""
        w = QWidget()
        root = QVBoxLayout(w)
        note = QLabel(
            "Connect accounts in their official windows. JARVIS never asks for, "
            "displays, or stores passwords, MFA codes, cookies, or OAuth tokens."
        )
        note.setObjectName("statusLabel")
        note.setWordWrap(True)
        root.addWidget(note)

        gmail = QLabel("GMAIL / EMAIL")
        gmail.setObjectName("dataValue")
        root.addWidget(gmail)
        self.gmail_status = QLabel(self._account_status_text("gmail"))
        self.gmail_status.setWordWrap(True)
        root.addWidget(self.gmail_status)
        gmail_buttons = QHBoxLayout()
        self.btn_connect_gmail = QPushButton("Open Google sign-in")
        self.btn_connect_gmail.clicked.connect(lambda: self._begin_account_login("gmail"))
        self.btn_verify_gmail = QPushButton("Verify Gmail")
        self.btn_verify_gmail.clicked.connect(lambda: self._verify_account_login("gmail"))
        gmail_buttons.addWidget(self.btn_connect_gmail)
        gmail_buttons.addWidget(self.btn_verify_gmail)
        root.addLayout(gmail_buttons)

        whatsapp = QLabel("WHATSAPP DESKTOP")
        whatsapp.setObjectName("dataValue")
        root.addWidget(whatsapp)
        self.whatsapp_status = QLabel(self._account_status_text("whatsapp"))
        self.whatsapp_status.setWordWrap(True)
        root.addWidget(self.whatsapp_status)
        whatsapp_buttons = QHBoxLayout()
        self.btn_connect_whatsapp = QPushButton("Open WhatsApp Desktop login")
        self.btn_connect_whatsapp.clicked.connect(
            lambda: self._begin_account_login("whatsapp")
        )
        self.btn_verify_whatsapp = QPushButton("Verify WhatsApp")
        self.btn_verify_whatsapp.clicked.connect(
            lambda: self._verify_account_login("whatsapp")
        )
        whatsapp_buttons.addWidget(self.btn_connect_whatsapp)
        whatsapp_buttons.addWidget(self.btn_verify_whatsapp)
        root.addLayout(whatsapp_buttons)
        root.addStretch(1)
        return w

    @staticmethod
    def _account_status_text(account):
        try:
            from core.account_connections import AccountConnectionManager
            status = AccountConnectionManager.status(account)
            return f"{status['state']}: {status['detail']}"
        except Exception as exc:
            return f"UNKNOWN: {exc}"

    def _begin_account_login(self, account):
        if self.gc is None or not hasattr(self.gc, "begin_account_login"):
            self._set_account_status(account, "ERROR: Running JARVIS controller unavailable.")
            return
        self._set_account_status(account, "Opening official sign-in window…")
        self.gc.begin_account_login(account)

    def _verify_account_login(self, account):
        if self.gc is None or not hasattr(self.gc, "verify_account_login"):
            self._set_account_status(account, "ERROR: Running JARVIS controller unavailable.")
            return
        self._set_account_status(account, "Verifying the existing account session…")
        self.gc.verify_account_login(account)

    def _on_account_connection(self, account, result):
        result = result if isinstance(result, dict) else {}
        detail = result.get("detail", "No verification detail returned.")
        state = result.get("state", "UNKNOWN")
        self._set_account_status(str(account).lower(), f"{state}: {detail}")

    def _set_account_status(self, account, text):
        label = {
            "gmail": getattr(self, "gmail_status", None),
            "whatsapp": getattr(self, "whatsapp_status", None),
        }.get(account)
        if label is not None:
            label.setText(str(text))

    def _hermes_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        note = QLabel("Hermes runs as JARVIS's external agent engine. Provider secrets stay in Hermes's supported login/configuration flow and are never shown here.")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_check(form, "hermes_enabled", "Enable Hermes engine")
        self._add_combo(form, "hermes_provider", "Provider", ["openrouter", "openai", "anthropic", "custom"])
        self._add_line(form, "hermes_model", "Agent model")
        self._add_combo(form, "hermes_mode", "Runtime mode", ["disabled", "cli"])
        self._add_spin(form, "hermes_concurrency_limit", "Concurrent tasks", 1, 2, 1)
        self._add_combo(form, "hermes_approval_mode", "Approval mode", ["strict"])
        self._widgets["hermes_approval_mode"][1].setEnabled(False)
        self._widgets["hermes_approval_mode"][1].setToolTip(
            "Strict approval is required until the constrained pilot passes."
        )
        self._add_check(form, "hermes_background_enabled", "Enable background tasks")
        self._add_check(form, "hermes_schedules_enabled", "Enable schedules")
        self._add_check(form, "hermes_learning_enabled", "Enable generated-skill proposals")
        for key in (
            "hermes_background_enabled", "hermes_schedules_enabled",
            "hermes_learning_enabled",
        ):
            self._widgets[key][1].setEnabled(False)
            self._widgets[key][1].setToolTip("Locked off until the constrained Hermes pilot passes.")
        self.hermes_status = QLabel("Checking installed Hermes runtime…")
        self.hermes_status.setWordWrap(True)
        form.addRow("RUNTIME", self.hermes_status)
        self.btn_test_hermes = QPushButton("Test Hermes Runtime")
        self.btn_test_hermes.clicked.connect(self._on_test_hermes)
        form.addRow(self.btn_test_hermes)
        self.btn_configure_hermes = QPushButton("Open Official Provider / Model Setup")
        self.btn_configure_hermes.clicked.connect(self._on_configure_hermes)
        form.addRow(self.btn_configure_hermes)
        return w

    def _on_test_hermes(self):
        if self._hermes_probe_running:
            return
        self._hermes_probe_running = True
        self.btn_test_hermes.setEnabled(False)
        self.hermes_status.setText("Checking installed Hermes runtime…")

        def probe():
            result = {}
            try:
                from brain.hermes_runtime_manager import HermesRuntimeManager
                result = HermesRuntimeManager().snapshot()
            except Exception as exc:
                result = {"state": "FAILED", "detail": str(exc)}
            self.hermes_probe_completed.emit(result)

        threading.Thread(
            target=probe, name="JARVIS-Hermes-Settings-Probe", daemon=True,
        ).start()

    def _apply_hermes_probe(self, status):
        status = status if isinstance(status, dict) else {}
        self._hermes_probe_running = False
        self.btn_test_hermes.setEnabled(True)
        try:
            self.hermes_status.setText(f"{status.get('state')}: {status.get('detail')}")
        except Exception as exc:
            self.hermes_status.setText(f"FAILED: {exc}")

    def _on_configure_hermes(self):
        if self.gc is None or not hasattr(self.gc, "open_hermes_provider_setup"):
            self.hermes_status.setText("FAILED: Running JARVIS controller unavailable.")
            return
        self.hermes_status.setText("Opening the official Hermes provider/model setup…")
        if not self.gc.open_hermes_provider_setup():
            self.hermes_status.setText("FAILED: JARVIS is shutting down.")

    def _on_hermes_configuration(self, result):
        result = result if isinstance(result, dict) else {}
        self.hermes_status.setText(
            f"{result.get('state', 'UNKNOWN')}: "
            f"{result.get('detail', 'No setup result returned.')}"
        )

    def _system_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self._add_check(form, "start_with_windows", "Start JARVIS with Windows")
        self._add_check(form, "minimize_to_tray", "Minimize to tray on close")
        self._add_check(form, "developer_mode", "Developer mode")
        self._add_path(form, "desktop_folder", "Desktop folder")
        self._add_path(form, "research_folder", "Research folder")
        self._add_path(form, "logs_folder", "Logs folder")
        return w

    # ---- widget helpers ---------------------------------------------------
    def _add_line(self, form, key, label):
        w = QLineEdit()
        form.addRow(QLabel(label), w)
        self._widgets[key] = ("line", w)

    def _add_combo(self, form, key, label, options):
        w = QComboBox()
        w.setEditable(True)
        w.addItems(options)
        form.addRow(QLabel(label), w)
        self._widgets[key] = ("combo", w)

    def _add_check(self, form, key, label):
        w = QCheckBox(label)
        form.addRow(w)
        self._widgets[key] = ("check", w)

    def _add_spin(self, form, key, label, mn, mx, step):
        w = QDoubleSpinBox()
        w.setRange(mn, mx)
        w.setSingleStep(step)
        form.addRow(QLabel(label), w)
        self._widgets[key] = ("spin", w)

    def _add_path(self, form, key, label):
        row = QHBoxLayout()
        w = QLineEdit()
        btn = QPushButton("Browse")
        btn.clicked.connect(lambda _=False, w=w: self._browse(w))
        row.addWidget(w)
        row.addWidget(btn)
        form.addRow(QLabel(label), row)
        self._widgets[key] = ("line", w)

    def _browse(self, widget):
        path = QFileDialog.getExistingDirectory(self, "Select folder", widget.text())
        if path:
            widget.setText(path)

    # ---- devices --------------------------------------------------------------
    def _populate_devices(self):
        try:
            from voice.devices import input_devices, output_devices
            mics = input_devices()
            spks = output_devices()
            self.mic_combo.clear()
            self.mic_combo.addItem("default", "default")
            for d in mics:
                self.mic_combo.addItem(f"{d['index']}: {d['name']}", d["index"])
            self.spk_combo.clear()
            self.spk_combo.addItem("default", "default")
            for d in spks:
                self.spk_combo.addItem(f"{d['index']}: {d['name']}", d["index"])
        except Exception as exc:
            self.mic_result.setText(f"Device enumeration failed: {exc}")

    def _selected_mic_index(self):
        data = self.mic_combo.currentData()
        if data in (None, "default"):
            return None
        try:
            return int(data)
        except Exception:
            return None

    # ---- test microphone ------------------------------------------------------
    def _on_test_mic(self):
        if self._test_stream is not None:
            return
        self.mic_result.setText("Recording 3 seconds...")
        self._test_frames = []
        try:
            import sounddevice as sd
            from voice.capture import SAMPLE_RATE, CHUNK
            device = self._selected_mic_index()
            self._test_stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=CHUNK, device=device,
                callback=self._on_test_frame,
            )
            self._test_stream.start()
            self._test_elapsed = 0
            self._test_timer = QTimer(self)
            self._test_timer.timeout.connect(self._test_tick)
            self._test_timer.start(100)
        except Exception as exc:
            self._test_stream = None
            self.mic_result.setText(f"Microphone open failed: {exc}")

    def _on_test_frame(self, indata, frames, time_info, status):
        try:
            audio = np.frombuffer(indata, dtype=np.int16).copy()
            self._test_frames.append(audio)
            peak = float(np.max(np.abs(audio))) / 32768.0
            self.level.setValue(int(min(100, peak * 100)))
        except Exception:
            pass

    def _test_tick(self):
        self._test_elapsed += 100
        if self._test_elapsed < 3000:
            return
        self._test_timer.stop()
        try:
            self._test_stream.stop()
            self._test_stream.close()
        except Exception:
            pass
        self._test_stream = None
        if not self._test_frames:
            self.mic_result.setText("No audio captured.")
            return
        audio = np.concatenate(self._test_frames)
        # save temp wav then verify non-silence, then delete
        import tempfile, wave, os
        fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="jarvis_mictest_")
        os.close(fd)
        try:
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio.tobytes())
            peak = float(np.max(np.abs(audio))) / 32768.0
            rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) / 32768.0
            if peak > 0.01 or rms > 0.003:
                self.mic_result.setText(
                    f"Non-silent audio captured (peak {peak:.2f}, rms {rms:.3f}). Microphone OK.")
            else:
                self.mic_result.setText(
                    f"Only silence captured (peak {peak:.2f}). Check the microphone.")
        except Exception as exc:
            self.mic_result.setText(f"Test failed: {exc}")
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        self.level.setValue(0)

    # ---- test speaker -----------------------------------------------------------
    def _on_test_speaker(self):
        if self.gc is None:
            self.mic_result.setText("Speaker test needs the running assistant.")
            return
        self.mic_result.setText("Speaking test through Piper...")
        self.gc.speak("JARVIS speaker test. Piper is online, sir.")

    # ---- OpenRouter connection and model discovery ---------------------------
    def _on_connect_openrouter(self):
        key = self.openrouter_key.text().strip()
        if not key:
            self.conn_result.setText("Enter an OpenRouter API key first.")
            return
        model = self.openrouter_model_combo.currentText().strip()
        self._start_openrouter_request(key, model, load_models=True)

    def _on_load_openrouter_models(self):
        key = self.openrouter_key.text().strip()
        if not key and self.gc is not None:
            controller = getattr(self.gc, "controller", self.gc)
            context = getattr(controller, "ctx", None)
            key = str(getattr(getattr(context, "llm", None), "api_key", "") or "")
        if not key:
            self.conn_result.setText("Connect an OpenRouter API key before loading models.")
            return
        model = self.openrouter_model_combo.currentText().strip()
        self._start_openrouter_request(key, model, load_models=True, test_connection=False)

    def _start_openrouter_request(self, key, model, *, load_models, test_connection=True):
        if self._openrouter_request_running:
            return
        self._openrouter_request_running = True
        self.btn_connect_openrouter.setEnabled(False)
        self.btn_refresh_models.setEnabled(False)
        self.conn_result.setText("Connecting to OpenRouter…" if test_connection else "Loading available models…")

        def work():
            result = {"key": key, "ok": False, "models": []}
            try:
                from brain.llm import LLM
                llm = LLM(api_key=key, model=model)
                if test_connection:
                    result["ok"], result["model"], result["detail"] = llm.test_connection()
                    if not result["ok"]:
                        self.openrouter_completed.emit(result)
                        return
                else:
                    result.update(ok=True, model=llm.model, detail="Connected")
                if load_models:
                    result["models"] = llm.list_models()
            except Exception as exc:
                result["detail"] = str(exc)
            self.openrouter_completed.emit(result)

        threading.Thread(target=work, name="JARVIS-OpenRouter-Settings", daemon=True).start()

    def _apply_openrouter_result(self, result):
        self._openrouter_request_running = False
        self.btn_connect_openrouter.setEnabled(True)
        result = result if isinstance(result, dict) else {}
        if not result.get("ok"):
            self.conn_result.setText(f"Connection failed: {result.get('detail', 'unknown error')}")
            return
        key = str(result.get("key") or "")
        model = str(result.get("model") or self.openrouter_model_combo.currentText() or "")
        controller = getattr(self.gc, "controller", self.gc)
        if controller is not None and hasattr(controller, "configure_openrouter"):
            saved, detail = controller.configure_openrouter(key, model)
            if not saved:
                self.conn_result.setText(detail)
                return
        else:
            from core.secret_store import save_openrouter_key
            if not save_openrouter_key(key):
                self.conn_result.setText("Could not secure the key in the Windows credential vault.")
                return
        models = result.get("models") or []
        if models:
            current = model
            self.openrouter_model_combo.blockSignals(True)
            self.openrouter_model_combo.clear()
            self.openrouter_model_combo.addItems(models)
            self.openrouter_model_combo.setCurrentText(current if current in models else models[0])
            self.openrouter_model_combo.blockSignals(False)
            self.conn_result.setText(f"Connected. {len(models)} models are available.")
        else:
            self.conn_result.setText("Connected. No model list was returned; enter a model id manually.")
        self.openrouter_model_combo.setEnabled(True)
        self.btn_refresh_models.setEnabled(True)

    # ---- load/save -----------------------------------------------------------
    def _load(self):
        data = self.store.as_dict()
        for key, (kind, w) in self._widgets.items():
            if w in (self.mic_combo, self.spk_combo):
                continue
            value = data.get(key)
            if kind == "check":
                w.setChecked(bool(value))
            elif kind == "spin":
                try:
                    w.setValue(float(value))
                except Exception:
                    pass
            elif kind == "combo":
                w.setCurrentText(str(value))
            else:
                w.setText(str(value))
        # restore saved device selections
        self._restore_combo(self.mic_combo, data.get("microphone_device"))
        self._restore_combo(self.spk_combo, data.get("speaker_device"))
        selected = str(data.get("openrouter_model") or "")
        if selected:
            self.openrouter_model_combo.addItem(selected)
            self.openrouter_model_combo.setCurrentText(selected)
        controller = getattr(self.gc, "controller", self.gc)
        context = getattr(controller, "ctx", None)
        if getattr(getattr(context, "llm", None), "available", False):
            self.btn_refresh_models.setEnabled(True)

    def _restore_combo(self, combo, saved):
        if saved in (None, "", "default"):
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            if str(combo.itemData(i)) == str(saved) or combo.itemText(i).endswith(str(saved)):
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _on_save(self):
        mapping = {}
        for key, (kind, w) in self._widgets.items():
            if w in (self.mic_combo, self.spk_combo):
                data = w.currentData()
                mapping[key] = "default" if data in (None, "default") else data
                continue
            if kind == "check":
                mapping[key] = w.isChecked()
            elif kind == "spin":
                mapping[key] = float(w.value())
            elif kind == "combo":
                mapping[key] = w.currentText()
            else:
                mapping[key] = w.text()
        self.store.update(mapping)
        controller = getattr(self.gc, "controller", self.gc)
        if controller is not None and hasattr(controller, "configure_openrouter"):
            controller.configure_openrouter("", mapping.get("openrouter_model", ""))
        if self.gc is not None and hasattr(self.gc, "apply_settings"):
            self.gc.apply_settings()
        self.accept()
