SYSTEM_PROMPT = """Voce e um assistente no Discord. Responda em portugues.
Use o CONTEXTO para responder com precisao.
Se o contexto nao contiver a resposta, diga que nao encontrou nos documentos e peca esclarecimentos.
"""


def build_user_prompt(question: str, context: str) -> str:
    return f"""CONTEXTO (trechos relevantes):
{context}

PERGUNTA:
{question}

INSTRUCOES:
- Responda usando o contexto acima.
- Se faltar informacao, diga explicitamente que nao esta nos documentos.
"""
