import json
import re
from pathlib import Path
from typing import Union
import logging

logger = logging.getLogger(__name__)

def extract_sections(markdown_text):
    reply_match = re.search(r"\*\*REPLY\*\*\s*(.*?)(?=\*\*[A-Z0-9\- ]+\*\*|$)", markdown_text, re.DOTALL | re.IGNORECASE)
    transcript_match = re.search(r"\*\*TRANSCRIPTION\*\*\s*(.*?)(?=\*\*[A-Z0-9\- ]+\*\*|$)", markdown_text, re.DOTALL | re.IGNORECASE)
    image_descs = re.findall(r"\*\*IMAGE[-\s]?(\d+)[-\s]?DESCRIPTION\*\*\s*(.*?)(?=\*\*[A-Z0-9\- ]+\*\*|$)", markdown_text, re.DOTALL | re.IGNORECASE)

    reply = reply_match.group(1).strip() if reply_match else ""
    transcript = transcript_match.group(1).strip() if transcript_match else ""
    images = [desc.strip() for _, desc in image_descs]

    return reply, transcript, images

def normalize_text(text):
    text = text.replace('\\n', ' ').replace('\n', ' ').replace('\"', '"')
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\b(CRIPTION|TRANSCRIPTION)\b', '', text, flags=re.IGNORECASE)
    return text.strip()

def deduplicate_sentences(text):
    sentences = re.split(r'(?<=[.?!])\s+', text)
    seen = set()
    deduped = []
    for sentence in sentences:
        s = sentence.strip()
        if s and s not in seen:
            deduped.append(s)
            seen.add(s)
    return ' '.join(deduped)

def clean(text):
    return deduplicate_sentences(normalize_text(text))

def convert_chat_history(raw_data: list, output_path: Union[str, Path]):
    converted = []
    skipped = 0
    for entry in raw_data:
        if entry["role"] != "model":
            continue

        text = entry.get("text", "")
        if not text.strip():
            logging.warning(f"Skipping model entry with empty text.")
            skipped += 1
            continue

        reply, transcript, images = extract_sections(text)
        reply = clean(reply)
        transcript = clean(transcript)
        images = [f"IMAGE: {clean(img)}" for img in images]

        user_parts = [part for part in [transcript] + images if part]
        if user_parts:
            converted.append({"role": "user", "parts": user_parts})

        if reply:
            converted.append({"role": "model", "parts": [reply]})

    logging.info(f"🧠 Semantic conversion complete: {len(converted)} entries written, {skipped} skipped.")
    
    if converted:
        try:
            output_path = Path(output_path)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(converted, f, indent=2, ensure_ascii=False)
            logging.info(f"✅ Semantic chat saved to {output_path}")
        except Exception as e:
            logging.error(f"❌ Failed to save semantic_chat.json: {e}")
    else:
        logging.warning("⚠️ No semantic content extracted. semantic_chat.json not written.")