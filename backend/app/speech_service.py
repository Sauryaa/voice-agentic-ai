from google.cloud import speech


class SpeechToTextService:
    def __init__(self, language_code: str = "en-US"):
        self.language_code = language_code
        self._client: speech.SpeechClient | None = None

    def _get_client(self) -> speech.SpeechClient:
        if self._client is None:
            self._client = speech.SpeechClient()
        return self._client

    def transcribe_webm_opus(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""

        responses = []
        for encoding in (
            speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        ):
            try:
                responses.append(self._recognize(audio_bytes, encoding=encoding))
            except Exception:
                continue

        if not responses:
            raise RuntimeError("Google Speech-to-Text request failed for WEBM_OPUS and OGG_OPUS audio.")

        response = responses[0]

        chunks = []
        for result in response.results:
            if not result.alternatives:
                continue
            chunks.append(result.alternatives[0].transcript.strip())
        return " ".join(chunk for chunk in chunks if chunk).strip()

    def _recognize(
        self,
        audio_bytes: bytes,
        encoding: speech.RecognitionConfig.AudioEncoding,
    ) -> speech.RecognizeResponse:
        config = speech.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=48000,
            language_code=self.language_code,
            enable_automatic_punctuation=True,
            model="latest_long",
        )
        audio = speech.RecognitionAudio(content=audio_bytes)
        return self._get_client().recognize(config=config, audio=audio)
