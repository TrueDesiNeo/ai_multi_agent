## Project Overview

---

Welcome to **Bot-to-Bot: Engineering Multi-Agent Conversations**, the definitive code repository accompanying the blog series dedicated to designing, scaling, and governing sophisticated multi-agent AI systems.

This repository contains the **live, production-focused implementations** of the examples covered throughout the series. This project is a hands-on guide dedicated to building agentic architectures that transition smoothly from proof-of-concept to **production-ready deployment**.

Dive in to explore the practical code that makes multi-agent collaboration effective, reliable, and production-grade.

**Read the Series:** [https://medium.com/@ratneshyadav\_26063/bot-to-bot-engineering-multi-agent-conversations-part-1-a8109ad324a0](https://medium.com/@ratneshyadav\_26063/bot-to-bot-engineering-multi-agent-conversations-part-1-a8109ad324a0)

---

## Multi-Agent Centralized (Local Deployment)

### `1_Multi_Agent_Centralized`

This folder contains the implementation for a **multi-agent centralized pattern** where all computational agents operate within a single, local execution environment (e.g., one machine or server).

* **Architecture:** Centralized control flow managed via **LangGraph**.
* **User Interface:** An interactive UI is provided using **Streamlit** to facilitate monitoring and interaction with the agent system.
* **Scope:** Ideal for proof-of-concept development, local testing, and scenarios where agents have high-throughput, low-latency communication requirements and share a unified computational resource pool.

---

## Multi-Agent Centralized (Distributed Deployment)

### `1.1_Multi_Agent_Centralized_A2A`

This folder implements the **multi-agent centralized pattern** within a **distributed environment**. This architecture is designed for scalability and resilience by deploying individual agents across separate virtual machines (VMs) or distinct network endpoints.

* **Distribution:** Agents are deployed across different **Virtual Machines (VMs)**.
* **Inter-Agent Communication (IAC):** Communication between the distinct agents is facilitated using the **Google Agent-to-Agent (A2A) protocol**. This protocol ensures reliable and structured message passing between agents residing on separate host machines.
* **Scope:** Suitable for production environments requiring **horizontal scaling**, fault isolation, and the distribution of computational load across a network infrastructure.

---

## Multi-Agent DeCentralized (P2P) (Distributed Deployment)

### `2.Multi_Agent_P2P_NATS`

This folder implements the **multi-agent DeCentralized (P2P) pattern** within a **distributed environment**. This sophisticated architecture is explicitly designed for **scalability** and **resilience** by deploying individual agents across separate **Virtual Machines (VMs)** or distinct network endpoints.

| Feature | Description |
| :--- | :--- |
| **Distribution** | Agents are deployed across different **Virtual Machines (VMs)**. |
| **Inter-Agent Communication (IAC)** | Communication between distinct agents is facilitated using the **NATS**. This protocol ensures reliable and structured message passing between agents residing on separate host machines. |
| **Scope** | Suitable for **production environments** requiring **horizontal scaling**, fault isolation, and the distribution of computational load across a network infrastructure. |

## Hierarchical Multi Agent

### ``3_Multi_Agent_Hierarchical_NATS
This folder implements the **NATS-backed multi agent** designed for generating structured, quality-controlled content (like articles or technical documents) using large language models (LLMs). The workflow is hierarchical and asynchronous, moving a root request through distinct editor, writer, and verifier stages.

| Component | File | Role | NATS Input Subject | NATS Output Subject(s) |
| :--- | :--- | :--- | :--- | :--- |
| **Chief Editor** | `chief_editor_service.py` | Receives root requests, delegates topic proposal, and **fans out** topics. | `demo.chief.in` | `demo.section.in` |
| **Section Editor** | `section_editor_service.py` | Receives topics, delegates section/outline generation, and forwards tasks. | `demo.section.in` | `demo.write.in` |
| **Writer** | `writer_service.py` | Receives section tasks (or revisions), delegates drafting via LLM, and forwards draft. | `demo.write.in` | `demo.verify.in` |
| **Verifier** | `verify_service.py` | Scores draft via LLM. **Routes** bad drafts back for revision, or approves the final content. | `demo.verify.in` | `demo.write.in`, `demo.done` |
| **CLI Client** | `client.py` | Publishes root request, subscribes to final output, and logs results. | (N/A) | `demo.chief.in` (Pub), `demo.done` (Sub) |
| **Streamlit Client** | `streamlit_client.py` | Interactive web UI for pipeline initiation, monitoring, and result download. | (N/A) | `demo.chief.in` (Pub), `demo.done` (Sub) |