from __future__ import annotations

import argparse

from backend.app.services.text_to_speech import TextToSpeechService


def main() -> None:
    parser = argparse.ArgumentParser(description="List available Google Cloud Text-to-Speech voices.")
    parser.add_argument("--language-code", default=None, help="Optional BCP-47 language code, for example en-US.")
    args = parser.parse_args()

    voice_list = TextToSpeechService().list_voices(language_code=args.language_code)
    print(f"Total voices: {voice_list.total_voices}")
    for voice in voice_list.voices:
        languages = ", ".join(voice.language_codes)
        voice_type = voice.voice_type or "unknown"
        print(f"{voice.name} | {languages} | {voice.ssml_gender} | {voice_type}")


if __name__ == "__main__":
    main()
