# RTA-GUARD — LangChain Example

Drop-in protection for your LangChain application.

## Setup

```bash
pip install rta-guard[langchain]
# or from source:
pip install -e ".[langchain]"
```

## Usage

### Option 1: Callback Handler (Simplest)

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from integrations.langchain import RtaGuardCallbackHandler

# Create your chain as usual
llm = ChatOpenAI(model="gpt-4")
prompt = ChatPromptTemplate.from_template("You are a helpful assistant. Answer: {input}")
chain = LLMChain(llm=llm, prompt=prompt)

# Add RTA-GUARD protection
handler = RtaGuardCallbackHandler(session_id="user-123")

# Run with protection
try:
    result = chain.invoke({"input": "What is Python?"}, config={"callbacks": [handler]})
    print(result)
except RuntimeError as e:
    print(f"Blocked: {e}")

# Check violations
print(f"Violations: {handler.violations}")
```

### Option 2: Chain Wrapper (Recommended)

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from integrations.langchain import RtaGuardChain

# Create chain
llm = ChatOpenAI(model="gpt-4")
prompt = ChatPromptTemplate.from_template("{input}")
chain = LLMChain(llm=llm, prompt=prompt)

# Wrap with RTA-GUARD
protected = RtaGuardChain(chain, session_id="user-123", on_violation="raise")

# Normal usage — protection is automatic
result = protected.invoke({"input": "Hello!"})

# This will be BLOCKED:
result = protected.invoke({"input": "My SSN is 123-45-6789"})  # RuntimeError
```

### Option 3: LCEL Runnable

```python
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from integrations.langchain import RtaGuardRunnable

# Build LCEL chain
prompt = ChatPromptTemplate.from_template("Answer: {input}")
llm = ChatOpenAI(model="gpt-4")
parser = StrOutputParser()
chain = prompt | llm | parser

# Wrap with protection
protected = RtaGuardRunnable(chain)

# Usage
result = protected.invoke({"input": "Tell me a joke"})
```

### Option 4: LLM Wrapper

```python
from langchain_openai import ChatOpenAI
from integrations.langchain import RtaGuardLLM

# Wrap the LLM directly
llm = ChatOpenAI(model="gpt-4")
protected_llm = RtaGuardLLM(llm, session_id="user-123")

# All calls are protected
response = protected_llm.invoke("Hello!")
# PII, injection, etc. will be blocked before reaching the LLM
```

### Violation Handling

```python
# "raise" (default) — raises RuntimeError on violation
handler = RtaGuardCallbackHandler(on_violation="raise")

# "warn" — logs warning but continues
handler = RtaGuardCallbackHandler(on_violation="warn")

# "block" — returns "[BLOCKED BY RTA-GUARD]" instead
handler = RtaGuardCallbackHandler(on_violation="block")
```

### Custom Guard Configuration

```python
from discus import DiscusGuard, GuardConfig
from integrations.langchain import RtaGuardChain, set_guard

# Create custom guard
config = GuardConfig(kill_threshold="HIGH")
guard = DiscusGuard(config)

# Use it globally
set_guard(guard)

# Or pass to individual wrappers
protected = RtaGuardChain(chain, guard=guard)
```
