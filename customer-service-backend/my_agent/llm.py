"""Explicit environment-only model client; no implicit dotenv discovery."""
import os
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.environ['LLM_MODEL'],
    base_url=os.environ['LLM_BASE_URL'],
    api_key=os.environ['LLM_API_KEY'],
    temperature=0,
    timeout=float(os.getenv('LLM_TIMEOUT', '30')),
    max_retries=int(os.getenv('LLM_MAX_RETRIES', '1')),
)
