import os
import sys
from openai import OpenAI

# Force UTF-8 on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-c7ccieiPaHYwHsBA13fNYQ")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://zro.moonmath.ai/v1")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash-0731")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def stream_chat(messages):
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            stream=True
        )
        full_text = []
        for chunk in response:
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                sys.stdout.write(content)
                sys.stdout.flush()
                full_text.append(content)
        print()
        return "".join(full_text)
    except Exception as e:
        print(f"\n[Error communicating with DeepSeek]: {e}")
        return ""

def main():
    args = sys.argv[1:]
    
    # One-shot mode: deepseek "prompt"
    if args:
        prompt = " ".join(args)
        messages = [
            {"role": "system", "content": "You are DeepSeek, an expert AI programming and general assistant. Provide accurate, practical, and clean answers."},
            {"role": "user", "content": prompt}
        ]
        stream_chat(messages)
        return

    # Interactive REPL mode: deepseek
    print("=" * 68)
    print("  DeepSeek (Moonmath) - Interactive Terminal Assistant")
    print(f"  Model: {MODEL} | Base URL: {BASE_URL}")
    print("  Commands: 'exit' / 'quit' to leave | 'clear' to reset chat memory")
    print("=" * 68)
    print()

    history = [
        {"role": "system", "content": "You are DeepSeek, an expert AI programming and general assistant. Provide accurate, practical, and clean answers."}
    ]

    while True:
        try:
            user_input = input("\nYou > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            if user_input.lower() == "clear":
                history = [history[0]]
                print("[Chat memory cleared.]")
                continue

            history.append({"role": "user", "content": user_input})
            print("\nDeepSeek > ", end="", flush=True)
            assistant_reply = stream_chat(history)
            if assistant_reply:
                history.append({"role": "assistant", "content": assistant_reply})
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

if __name__ == "__main__":
    main()
