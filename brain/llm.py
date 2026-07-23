"""
OpenRouter client â€” the main cloud brain. OpenAI-compatible API, streaming
supported. All conversation / drafting / research / summarization flows
through here. The local Qwen router never touches this.
"""
import threading
import json
import re
import time

from config import Config, valid_openrouter_key


class LLM:
    def __init__(self, api_key=None, model=None, base_url=None):
        self.api_key = (api_key if api_key is not None else Config.OPENROUTER_API_KEY).strip()
        self.model = (model or Config.OPENROUTER_MODEL).strip()
        self.base_url = (base_url or Config.OPENROUTER_BASE_URL).strip()
        self.last_error = ""
        self._lock = threading.Lock()
        self._client = None
        # Client construction imports the provider stack and may inspect proxy
        # or certificate configuration.  Keep startup and every local command
        # independent of that work; chat()/stream() build it on first use.

    # ------------------------------------------------------------ plumbing
    @property
    def available(self):
        return valid_openrouter_key(self.api_key)

    def _build_client(self):
        try:
            import httpx
            from openai import OpenAI
            http_client = httpx.Client(timeout=Config.OPENROUTER_TIMEOUT, follow_redirects=True)
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers={
                    "HTTP-Referer": "https://jarvis.local",
                    "X-Title": "JARVIS Desktop Assistant",
                },
                timeout=Config.OPENROUTER_TIMEOUT,
                http_client=http_client,
            )
        except Exception as exc:  # openai lib missing, etc.
            self.last_error = str(exc)
            self._client = None

    # ---------------------------------------------------------------- chat
    def chat(self, messages, temperature=0.7, max_tokens=2048):
        """Non-streaming completion with retry. Returns empty on failure (see last_error)."""
        if not self.available:
            self.last_error = "OPENROUTER_API_KEY not set"
            return ""
        if self._client is None:
            self._build_client()
            if self._client is None:
                return ""
        last_error = ""
        for attempt in range(1, Config.OPENROUTER_RETRIES + 1):
            try:
                with self._lock:
                    resp = self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=False,
                    )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                last_error = str(exc)
                if attempt < Config.OPENROUTER_RETRIES:
                    time.sleep(1.0 * attempt)
                    continue
                break
        msg = last_error
        if self.api_key and self.api_key in msg:
            msg = msg.replace(self.api_key, "***")
        if "402" in msg or "insufficient_quota" in msg:
            msg = "Provider returned 402 - insufficient quota or payment required"
        elif "429" in msg:
            msg = "Rate limited (429) - reduce request frequency"
        elif "403" in msg:
            msg = "Access denied (403) - check API key permissions"
        elif "401" in msg:
            msg = "Unauthorized (401) - invalid API key"
        self.last_error = f"{msg} (after {Config.OPENROUTER_RETRIES} attempts)"
        return ""


    # ------------------------------------------------------- test connection
    def test_connection(self):
        """Verify OpenRouter connectivity with a tiny request. Returns (ok, model, detail)."""
        if not self.available:
            return False, self.model, "OPENROUTER_API_KEY not set"
        try:
            # Reuse an initialized provider client when one exists.  Apart
            # from avoiding an unnecessary second connection setup, this
            # keeps the diagnostic on the same configured transport as chat
            # and makes its error handling deterministic for callers.
            client = self._client
            if client is None:
                from openai import OpenAI
                import httpx
                client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    default_headers={
                        "HTTP-Referer": "https://jarvis.local",
                        "X-Title": "JARVIS Desktop Assistant",
                    },
                    timeout=15.0,
                    http_client=httpx.Client(timeout=15.0, follow_redirects=True),
                )
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
                temperature=0,
                stream=False,
            )
            model_used = resp.model or self.model
            return True, model_used, "connected"
        except Exception as exc:
            msg = str(exc)
            if self.api_key and self.api_key in msg:
                msg = msg.replace(self.api_key, "***")
            if "402" in msg or "insufficient_quota" in msg:
                msg = "402 - insufficient quota"
            elif "429" in msg:
                msg = "429 - rate limited"
            elif "403" in msg:
                msg = "403 - access denied"
            elif "401" in msg:
                msg = "401 - invalid API key (***)"
            return False, self.model, msg

    # ----------------------------------------------------------- streaming
    def stream(self, messages, temperature=0.7, max_tokens=2048):
        """Generator yielding text chunks. Use for real-time UI streaming."""
        if not self.available:
            self.last_error = "OPENROUTER_API_KEY not set"
            return
        if self._client is None:
            self._build_client()
            if self._client is None:
                return
        for attempt in range(1, Config.OPENROUTER_RETRIES + 1):
            try:
                with self._lock:
                    stream_resp = self._client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True,
                    )
                for chunk in stream_resp:
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        yield delta
                return
            except Exception as exc:
                if attempt < Config.OPENROUTER_RETRIES:
                    time.sleep(1.0 * attempt)
                    continue
                msg = str(exc)
                if self.api_key and self.api_key in msg:
                    msg = msg.replace(self.api_key, "***")
                self.last_error = msg
                return

    # ---------------------------------------------------------- quick / json
    def quick(self, prompt, system=None, temperature=0.7, max_tokens=512):
        """One-shot convenience: send a single user message."""
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return self.chat(msgs, temperature=temperature, max_tokens=max_tokens)

    def quick_json(self, prompt, system=None):
        """One-shot convenience returning a parsed JSON dict."""
        raw = self.quick(prompt, system=system, temperature=0.0, max_tokens=1024)
        if not raw:
            return {}
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}

    @staticmethod
    def extract_json(text):
        """Extract the first balanced JSON object from model prose."""
        raw = (text or "").strip()
        start = raw.find("{")
        if start < 0:
            return {}
        depth = 0
        quoted = False
        escaped = False
        end = None
        for index, char in enumerate(raw[start:], start):
            if escaped:
                escaped = False
                continue
            if char == "\\" and quoted:
                escaped = True
                continue
            if char == '"':
                quoted = not quoted
                continue
            if quoted:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            return {}
        candidate = re.sub(r",\s*([}\]])", r"\1", raw[start:end])
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
