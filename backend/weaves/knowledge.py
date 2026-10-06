from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).with_name("knowledge")


def search(query: str, limit: int = 3) -> list[dict[str, str]]:
    """Small deterministic retrieval capability for the POC demo corpus."""
    terms = {word.lower().strip(".,?!:;()") for word in query.split() if len(word) > 2}
    matches = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text()
        score = sum(text.lower().count(term) for term in terms)
        if score:
            matches.append((score, path, text.strip()))
    matches.sort(key=lambda item: (-item[0], item[1].name))
    return [
        {"source": path.name, "content": content}
        for _, path, content in matches[:limit]
    ]
