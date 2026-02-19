# Multi-Tenant RAG Architecture Patterns

## Overview
Design patterns for building RAG systems that serve multiple tenants/entities with strict data isolation.

## Architecture Options

### 1. Single RAG with Metadata Filtering
```
User Query → RBAC Check → Filtered Vector Search → LLM
                    ↓
            {tenant_id: "company_a", department: ["hr", "finance"]}
```

**Pros:**
- Unified infrastructure
- Easier maintenance
- Cross-entity insights possible (if allowed)

**Cons:**
- Complex access control logic
- Risk of data leaks if filtering fails
- Single point of failure

**Best for:** Trusted tenants, cost-sensitive deployments

---

### 2. Tenant-Scoped Collections/Indexess
```
Tenant A → Collection A → LLM
Tenant B → Collection B → LLM
```

**Pros:**
- Clean data separation
- Simpler security model
- Independent scaling per tenant

**Cons:**
- Duplicate infrastructure
- Cannot cross-query
- Higher operational overhead

**Best for:** High-security requirements, compliance needs

---

### 3. Hybrid Approach (Recommended)
- Single RAG infrastructure
- Logical separation via collections/namespaces
- Pre-retrieval authorization from main RBAC system
- Vector metadata tagged with: `tenant_id`, `department`, `access_level`

**Implementation:**
```python
# RBAC system validates user
user_permissions = rbac.get_permissions(user_id)
# Pass scoped token to RAG
results = rag.search(query, filters={
    "tenant_id": user_permissions.tenant_id,
    "access_level": {"$lte": user_permissions.clearance}
})
```

---

## Key Design Patterns

### Pre-Retrieval Authorization
- RBAC checks happen BEFORE vector search
- User → Main System → [tenant_id, roles, permissions] → RAG Gateway
- Prevents unauthorized data from ever being retrieved

### Metadata Filtering at Query Time
- Documents tagged during ingestion
- Filters applied during semantic search
- Example (Pinecone):
```python
index.query(
    vector=embedding,
    filter={
        "tenant_id": {"$eq": "company_a"},
        "department": {"$in": ["hr", "finance"]}
    }
)
```

### Permission Mirroring
- Sync permissions from source systems (CRM, Xero, Google Drive)
- External app permissions → RAG metadata
- Ensures consistent access rules across platforms

---

## Vector DB Support for Multi-Tenancy

| Provider | Multi-Tenant Feature | Notes |
|----------|---------------------|-------|
| **Pinecone** | Namespaces + Metadata Filtering | Easy partitioning, serverless options |
| **Weaviate** | Multi-tenancy module | Tenant-specific indexes |
| **Milvus** | RBAC + Collections | Built-in role-based access control |
| **Qdrant** | Payload filtering + Collections | Open source, self-hostable |

---

## Security Considerations

1. **Never trust client-side filters** - Always validate on backend
2. **Audit logging** - Track who queried what
3. **Embedding isolation** - Ensure embeddings don't leak cross-tenant info
4. **Rate limiting per tenant** - Prevent abuse
5. **Encryption at rest** - Vector DB data encrypted

---

## References
- Milvus multi-tenancy guide: https://milvus.io/blog/build-multi-tenancy-rag-with-milvus-best-practices-part-one.md
- Pinecone access control: https://www.pinecone.io/learn/rag-access-control/
- Azure multi-tenant RAG: https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/secure-multitenant-rag
