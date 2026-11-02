import json
import os

path = os.path.expanduser('~/.gemini/antigravity/brain/b69e8126-44de-4f1a-907d-95c7333f9bb4/.system_generated/logs/transcript_full.jsonl')
if not os.path.exists(path):
    path = os.path.expanduser('~/.gemini/antigravity/brain/b69e8126-44de-4f1a-907d-95c7333f9bb4/.system_generated/logs/transcript.jsonl')

with open(path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            content = data.get('content', '')
            if 'MASTER PROMPT' in content:
                with open('master_prompt_extracted.txt', 'w', encoding='utf-8') as out:
                    out.write(content)
                print('Saved master prompt successfully. Length:', len(content))
                break
        except Exception as e:
            continue

