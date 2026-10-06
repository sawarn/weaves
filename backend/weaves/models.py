import os

import httpx


def answer(
    task: str,
    sources: list[dict[str, str]],
    instructions: str = "",
) -> tuple[str, dict[str, str]]:
    """Use a configured OpenAI-compatible endpoint, or a predictable local mock."""
    api_key = os.getenv("MODEL_API_KEY", "").strip()
    if not api_key:
        if not sources:
            return (
                "I could not find relevant information in the connected company "
                "knowledge base. Try rephrasing the question or connect another source.",
                {"provider": "mock", "model": "mock-v1"},
            )
        bullets = "\n".join(f"- {source['content']}" for source in sources)
        return (
            "Here is what I found in the connected company knowledge base:\n\n"
            f"{bullets}\n\nSources: {', '.join(s['source'] for s in sources)}",
            {"provider": "mock", "model": "mock-v1"},
        )

    base_url = os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("MODEL_NAME", "gpt-4o-mini")
    context = (
        "\n\n".join(f"[{source['source']}]\n{source['content']}" for source in sources)
        or "No relevant source was found. Say that the available context does not answer the question."
    )
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "Answer from the supplied company context only. Cite source filenames. If context does not answer, say so.\n\nAgent instructions:\n"
                    + (instructions or "Be clear and concise."),
                },
                {"role": "user", "content": f"Question: {task}\n\nContext:\n{context}"},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]["content"], {
        "provider": "openai-compatible",
        "model": model,
    }
