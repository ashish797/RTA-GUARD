# RTA-GUARD — LlamaIndex Example

Drop-in protection for your LlamaIndex RAG application.

## Setup

```bash
pip install rta-guard[llamaindex]
# or from source:
pip install -e ".[llamaindex]"
```

## Usage

### Option 1: Query Engine Wrapper

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from integrations.llamaindex import RtaGuardQueryEngine

# Build your index as usual
documents = SimpleDirectoryReader("data").load_data()
index = VectorStoreIndex.from_documents(documents)
engine = index.as_query_engine()

# Wrap with RTA-GUARD
protected = RtaGuardQueryEngine(engine, session_id="user-123")

# Query with protection
try:
    response = protected.query("What is this document about?")
    print(response)
except RuntimeError as e:
    print(f"Blocked: {e}")
```

### Option 2: Node PostProcessor

```python
from llama_index.core import VectorStoreIndex
from integrations.llamaindex import RtaGuardPostProcessor

index = VectorStoreIndex.from_documents(docs)

# Add as postprocessor — filters nodes BEFORE they reach the LLM
engine = index.as_query_engine(
    node_postprocessors=[
        RtaGuardPostProcessor(on_violation="remove")  # Drop nodes with PII/injection
    ]
)

response = engine.query("Tell me about the project")
# Nodes containing PII are automatically filtered out
```

### Option 3: Chat Engine

```python
from llama_index.core import VectorStoreIndex
from integrations.llamaindex import RtaGuardChatEngine

index = VectorStoreIndex.from_documents(docs)
chat_engine = index.as_chat_engine()

# Wrap with protection
protected = RtaGuardChatEngine(chat_engine, session_id="user-123")

# Chat with protection
response = protected.chat("What are the key points?")
print(response)
```

### Streaming

```python
from integrations.llamaindex import RtaGuardChatEngine

protected = RtaGuardChatEngine(chat_engine)

# Stream with per-chunk protection
for chunk in protected.stream_chat("Explain quantum computing"):
    print(chunk, end="", flush=True)
```

### Custom Guard

```python
from discus import DiscusGuard, GuardConfig
from integrations.llamaindex import RtaGuardQueryEngine, set_guard

config = GuardConfig(kill_threshold="HIGH")
guard = DiscusGuard(config)
set_guard(guard)

protected = RtaGuardQueryEngine(engine, guard=guard)
```
