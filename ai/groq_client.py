import os
from config.settings import load_settings

class GroqAI:
    def __init__(self):
        s=load_settings()
        self.key=s.get("groq_api_key") or os.getenv("GROQ_API_KEY")
        self.model=s.get("groq_model","openai/gpt-oss-120b")

    def chat(self,messages,temperature=0.2):
        if not self.key:
            raise RuntimeError("GROQ_API_KEY topilmadi")
        from groq import Groq
        client=Groq(api_key=self.key)
        r=client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        return r.choices[0].message.content
