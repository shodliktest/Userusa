from pathlib import Path
from ai.groq_client import GroqAI

class Operator:
    def __init__(self):
        self.ai=GroqAI()
        self.prompt=Path("config/agent_prompt.txt").read_text(encoding="utf-8")

    def reply(self,history,user_text):
        messages=[{"role":"system","content":self.prompt}]
        messages.extend(history[-12:])
        messages.append({"role":"user","content":user_text})
        return self.ai.chat(messages)
