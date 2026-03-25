# Qdrant Migration Guide — Brahmanda Map

## Switching from In-Memory to Qdrant

### Prerequisites

```bash
pip install qdrant-client>=1.7.0
```

You also need:
- A running Qdrant instance (`docker run -p 6333:6333 qdrant/qdrant`)
- An OpenAI API key for embeddings

### Option 1: Environment Variables (Recommended)

Set these env vars before starting the dashboard:

```bash
export QDRANT_URL=http://localhost:6333
export QDRANT_API_KEY=          # Optional, for Qdrant Cloud
export OPENAI_API_KEY=sk-...
export BRAHMANDA_BACKEND=auto   # "auto" uses Qdrant if QDRANT_URL set
```

The dashboard (`dashboard/app.py`) auto-detects and uses Qdrant when `QDRANT_URL` is present.

### Option 2: Explicit Backend Selection

```bash
export BRAHMANDA_BACKEND=qdrant  # Forces Qdrant (fails if unavailable)
```

### Option 3: Programmatic

```python
from brahmanda.qdrant_client import QdrantBrahmanda, create_qdrant_seed_map
from brahmanda.verifier import BrahmandaVerifier

# Create Qdrant-backed map (auto-seeds 11 facts if empty)
brahmanda = create_qdrant_seed_map(url="http://localhost:6333")

# Use with existing BrahmandaVerifier (same interface)
verifier = BrahmandaVerifier(brahmanda)
result = verifier.verify("The capital of France is Paris")
print(result.decision)  # pass
```

### Docker Compose

Add Qdrant to your `docker-compose.yml`:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.7.4
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  dashboard:
    build: .
    environment:
      - QDRANT_URL=http://qdrant:6333
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - qdrant

volumes:
  qdrant_data:
```

### Verifying It Works

```bash
# Start Qdrant
docker run -d -p 6333:6333 --name qdrant qdrant/qdrant

# Run tests
export QDRANT_URL=http://localhost:6333
export OPENAI_API_KEY=sk-...
python -m brahmanda.test_qdrant_search
```

### Key Differences

| Feature | In-Memory (`BrahmandaMap`) | Qdrant (`QdrantBrahmanda`) |
|---|---|---|
| Search type | Keyword/word overlap | Vector cosine similarity |
| Persistence | None (lost on restart) | Persistent in Qdrant |
| Scale | ~10K facts | Millions of facts |
| Semantic matching | No | Yes — rephrasings find matches |
| Dependencies | None | qdrant-client, openai |
| Embedding cost | Free | OpenAI API calls |

### Reverting to In-Memory

Simply unset `QDRANT_URL`:

```bash
unset QDRANT_URL
# Dashboard falls back to in-memory automatically
```
