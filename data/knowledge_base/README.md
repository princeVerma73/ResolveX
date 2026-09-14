# NovaCart Knowledge Base

This directory contains the knowledge documents used by the ResolveX RAG pipeline for the NovaCart demo company.

## Documents

- `faq.pdf` — Frequently asked questions and general customer information
- `refund_policy.pdf` — Refund eligibility and refund processing rules
- `cancellation_policy.pdf` — Order cancellation rules
- `shipping_policy.pdf` — Shipping and delivery policies
- `payment_policy.pdf` — Payment verification and payment issue handling
- `account_policy.pdf` — Account, privacy, and security support policies
- `support_guidelines.pdf` — Guidelines for AI support, tool failures, memory, and human escalation

## Purpose

These documents provide company-specific knowledge that ResolveX retrieves during customer conversations.

The RAG pipeline will:

1. Load the documents
2. Extract text
3. Split text into chunks
4. Generate embeddings
5. Store embeddings in Supabase pgvector
6. Retrieve relevant chunks for customer queries
7. Provide the retrieved context to the LLM
8. Generate a grounded response with the relevant source

## Important

This is fictional demo-company data created for the ResolveX internship project.

Live operational data such as customers, orders, payments, and tickets will be stored separately in the application database and accessed through functional tools.
