Design a multi-tenant SaaS platform for real-time product analytics.

Customers (B2B, ~500 tenants at launch, growing to ~5,000) instrument their web
and mobile apps with our SDK, which streams clickstream and custom events to us.
We ingest up to 50,000 events/second at peak. Customers query their data through
dashboards (funnels, retention, segmentation) that must feel interactive — most
queries should return in under 2 seconds over the last 90 days of data, with
cheaper cold storage for older data.

Requirements:
- Strict tenant data isolation; some customers are in the EU and require data
  residency in-region.
- Self-serve signup plus SSO (SAML/OIDC) for enterprise tenants.
- 99.9% availability target for the query/dashboard path.
- Usage-based billing derived from ingested event volume.
- A small team (8 engineers); we want to minimize undifferentiated ops toil.
