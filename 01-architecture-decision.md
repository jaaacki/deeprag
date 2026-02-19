# Architecture Decision: Build vs Buy

## Date
2026-02-20

## Context
Multiple companies/entities under 1 roof with:
- Various data sources: Google Drive, OCR scanning, databases (CRM), Xero accounting
- Main RBAC system in development
- Need multi-tenant RAG with entity separation
- Budget preference: $0 for software licenses

## Decision
**BUILD** using open-source frameworks

## Rationale

### Why Not Onyx (Open Core)
- Community Edition (free): Lacks document-level permissions and multi-tenant RBAC
- Enterprise Edition (paid): Has required features but violates $0 budget constraint
- Free version only gives basic roles (admin/curator/basic), not entity-level isolation

### Why Build Wins
| Factor | Build | Buy (Onyx EE) |
|--------|-------|---------------|
| Cost | $0 (dev time only) | ~$500-2000/month |
| Multi-tenant RBAC | Custom implementation | Built-in |
| Connector flexibility | Unlimited | 40+ pre-built |
| RBAC integration | Deep integration with main system | API-based sync |
| Time to MVP | 4-8 weeks | 1-2 weeks |

### Recommended Stack
- **Framework**: LlamaIndex (better for structured data: CRM, Xero, DBs)
- **Alternative**: LangChain (more integrations, rapid prototyping)
- **Vector DB**: Hosted (Pinecone, Weaviate Cloud, Milvus Cloud) - free tiers available
- **API Layer**: FastAPI
- **LLM**: OpenAI/Anthropic or self-hosted (Ollama)

## Implications
- Full control over access control logic
- Custom connectors for Xero, CRM systems
- Maintenance burden on team
- No licensing costs
- Can evolve with business needs
