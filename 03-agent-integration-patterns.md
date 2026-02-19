# AI Agent Integration with RAG Systems

## Overview
How multiple AI agents communicate with and use a centralized RAG system.

---

## Architecture Patterns

### 1. RAG as a Service (API Gateway)
```
Agent 1 ──┐
Agent 2 ──┼──> RAG API ──> Vector DB + LLM ──> Response
Agent 3 ──┘
```

**Implementation:**
- RAG exposed as REST/GraphQL API
- Agents make HTTP requests with query + context
- Centralized access control, logging, caching

**Example Endpoint:**
```http
POST /api/v1/retrieve
{
  "query": "What's the Q3 revenue?",
  "agent_id": "finance-agent",
  "tenant_id": "company_a",
  "top_k": 5
}
```

---

### 2. RAG as a Tool (Function Calling)
```
Agent → LLM with Tools → [RAG Tool, Calculator, Search] → Response
```

**LangChain Example:**
```python
from langchain.tools import Tool

rag_tool = Tool(
    name="KnowledgeBase",
    func=rag_engine.search,
    description="Search internal knowledge base for company documents"
)

agent = initialize_agent([rag_tool], llm, agent_type="openai-functions")
```

**Best for:** Agents that need RAG + other capabilities (calculation, APIs, etc.)

---

### 3. Agentic RAG (Retrieval Orchestration)
```
Agent → Query Planner → Multiple Retrieval Strategies → Synthesis → Response
              ↓
        - Semantic Search
        - Keyword Search  
        - Knowledge Graph
        - External APIs
```

**Key Features:**
- Agent decides WHEN to retrieve
- Agent decides WHAT to retrieve from
- Multiple retrieval methods combined
- Dynamic query rewriting

**Use Cases:**
- Complex multi-step questions
- Cross-source verification
- Iterative research

---

### 4. Multi-Agent RAG with A2A Protocol
```
Agent A (Finance) ←→ Agent B (HR) ←→ Shared RAG Layer
       ↓                    ↓
   Specialized         Specialized
   Knowledge           Knowledge
```

**Pattern:**
- Each agent has domain-specific instructions
- Shared RAG infrastructure with tenant filtering
- Agents can collaborate via message passing
- Central RAG ensures consistent data access

---

## Communication Methods

### Method 1: Direct API Calls
**Pros:** Simple, language-agnostic, easy to debug
**Cons:** Network latency, authentication overhead

```python
# Agent code
response = requests.post(
    "http://rag-service:8000/api/retrieve",
    json={"query": query, "tenant_id": tenant},
    headers={"Authorization": f"Bearer {agent_token}"}
)
context = response.json()["results"]
```

---

### Method 2: Message Queue (Async)
**Pros:** Decoupled, scalable, handles spikes
**Cons:** More complex, eventual consistency

```
Agent → Publish Query → Redis/RabbitMQ → RAG Worker → Return Results
```

---

### Method 3: Shared Memory/KV Store
**Pros:** Fast, low-latency
**Cons:** Shared state complexity

```python
# Agent writes query
redis.set(f"query:{agent_id}", query)

# RAG processor monitors and responds
redis.set(f"response:{agent_id}", rag_results)
```

---

## Access Control Integration

### Token-Based Agent Authentication
```python
# Main RBAC system issues tokens
agent_token = rbac.issue_agent_token(
    agent_id="finance-agent",
    tenant_id="company_a",
    permissions=["read:finance", "read:general"]
)

# RAG validates token on every request
def retrieve(query, tenant_id, agent_token):
    permissions = rbac.verify_token(agent_token)
    if not permissions.allows(tenant_id):
        raise PermissionDenied()
    return vector_db.search(query, filters=permissions.to_filter())
```

---

### Tenant-Aware Agent Routing
```python
class AgentRAGRouter:
    def __init__(self):
        self.tenant_rag_instances = {
            "company_a": RAGEngine(collection="company_a"),
            "company_b": RAGEngine(collection="company_b"),
        }
    
    def route(self, query, tenant_id, agent_credentials):
        # Validate agent has access to tenant
        if not rbac.can_access(agent_credentials, tenant_id):
            raise PermissionDenied()
        
        # Route to tenant-specific RAG
        rag = self.tenant_rag_instances[tenant_id]
        return rag.search(query)
```

---

## Implementation Options

### Option 1: FastAPI RAG Service
```python
from fastapi import FastAPI, Depends, HTTPException

app = FastAPI()

@app.post("/api/retrieve")
async def retrieve(
    query: str,
    tenant_id: str,
    agent_credentials: dict = Depends(verify_agent)
):
    if not await rbac.can_access(agent_credentials, tenant_id):
        raise HTTPException(403, "Unauthorized")
    
    results = await rag.search(query, filters={"tenant_id": tenant_id})
    return {"results": results}
```

---

### Option 2: LangChain Tool Integration
```python
from langchain.agents import Tool, initialize_agent
from langchain.llms import OpenAI

def rag_search(query: str, tenant_id: str) -> str:
    """Search knowledge base"""
    results = rag_engine.search(query, tenant_id)
    return "\n".join([r.text for r in results])

rag_tool = Tool(
    name="CompanyKB",
    func=lambda q: rag_search(q, tenant_id="company_a"),
    description="Search company knowledge base"
)

agent = initialize_agent([rag_tool], OpenAI(), agent="zero-shot-react-description")
```

---

### Option 3: LlamaIndex Query Engine
```python
from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.pinecone import PineconeVectorStore

# Shared vector store with metadata filtering
vector_store = PineconeVectorStore(index_name="company_knowledge")

# Tenant-specific query engine
def get_query_engine(tenant_id: str):
    filters = MetadataFilters(filters=[
        MetadataFilter(key="tenant_id", value=tenant_id)
    ])
    return index.as_query_engine(filters=filters)

# Agent uses tenant-specific engine
engine = get_query_engine("company_a")
response = engine.query("What are our HR policies?")
```

---

## Best Practices

1. **Centralize RAG logic** - Don't duplicate retrieval code in every agent
2. **Cache frequently accessed data** - Redis/Memcached for common queries
3. **Rate limit per agent** - Prevent单个 agent from monopolizing resources
4. **Log all queries** - Audit trail for compliance
5. **Validate agent permissions on every request** - Don't cache authorization
6. **Use connection pooling** - Reuse DB connections across agents
7. **Implement circuit breakers** - Graceful degradation if RAG is down

---

## References
- LangChain Agentic RAG: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- FastAPI + RAG: https://thenewstack.io/how-to-build-production-ready-ai-agents-with-rag-and-fastapi/
- Multi-agent A2A protocol: https://blogs.oracle.com/developers/build-a-scalable-multi-agent-rag-system-with-a2a-protocol-and-langchain
