# 🤖 Hierarchical Multi Agent

This repository contains a modular, **NATS-backed multi agent** designed for generating structured, quality-controlled content (like articles or technical documents) using large language models (LLMs). The workflow is hierarchical and asynchronous, moving a root request through distinct editor, writer, and verifier stages.

---

## 🎯 System Overview

The system is composed of five core Python microservices and two client interfaces, all communicating via **NATS** using a standardized **A2A envelope** for tracing and context propagation.

The pipeline flow is: **Client Request** $\to$ **Chief Editor** $\to$ **Section Editor** $\to$ **Writer** $\leftrightarrow$ **Verifier** $\to$ **Final Output**.

### 🗺️ Component Architecture

| Component | File | Role | NATS Input Subject | NATS Output Subject(s) |
| :--- | :--- | :--- | :--- | :--- |
| **Chief Editor** | `chief_editor_service.py` | Receives root requests, delegates topic proposal, and **fans out** topics. | `demo.chief.in` | `demo.section.in` |
| **Section Editor** | `section_editor_service.py` | Receives topics, delegates section/outline generation, and forwards tasks. | `demo.section.in` | `demo.write.in` |
| **Writer** | `writer_service.py` | Receives section tasks (or revisions), delegates drafting via LLM, and forwards draft. | `demo.write.in` | `demo.verify.in` |
| **Verifier** | `verify_service.py` | Scores draft via LLM. **Routes** bad drafts back for revision, or approves the final content. | `demo.verify.in` | `demo.write.in`, `demo.done` |
| **CLI Client** | `client.py` | Publishes root request, subscribes to final output, and logs results. | (N/A) | `demo.chief.in` (Pub), `demo.done` (Sub) |
| **Streamlit Client** | `streamlit_client.py` | Interactive web UI for pipeline initiation, monitoring, and result download. | (N/A) | `demo.chief.in` (Pub), `demo.done` (Sub) |

---

### Directory Structure: `2.Multi_Agent_P2P_NATS`

The structure below reflects the independent nature of each agent and the client, where each directory represents a potentially separate deployment unit (e.g., a distinct VM or service container).

Directory structure:

    Multi_Agent_P2P_NATS/
    ├── README.MD   
    ├── ChiefEditorAgent   
    │   ├── ChiefEditorAgent.py
    │   ├── chief_editor_service.py
    │   ├── llm_openai.py
    │   ├── logging_init.py
    │   ├── common_context.py
    │   ├── common_envelope.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── SectionEditorAgent/        
    │   ├── SectionEditorAgent.py
    │   ├── section_editor_service.py
    │   ├── llm_openai.py
    │   ├── logging_init.py
    │   ├── common_context.py
    │   ├── common_envelope.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── WriterAgent/        
    │   ├── WriterAgent.py
    │   ├── writer_service.py
    │   ├── llm_openai.py
    │   ├── logging_init.py
    │   ├── common_context.py
    │   ├── common_envelope.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── VerifierAgent/
    │   ├── verify_service.py
    │   ├── llm_openai.py
    │   ├── logging_init.py
    │   ├── common_context.py
    │   ├── common_envelope.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    └── Client/
        ├── client.py
        ├── streamlit_client.py        
        ├── .env
        ├── README.MD    
        └── requirements.txt
        
## 🚀 Getting Started

### Prerequisites

* **Python 3.10+**
* **NATS Server** running and accessible (default `127.0.0.1:4222`).
* **LLM API Access** (e.g., OpenAI, as implied by `WriterAgent` and `score_with_llm`).

## 🏃‍♂️ Running the System

### 1. Start the NATS Server  
Ensure the NATS server is running before proceeding.

---

### 2. Start the Agents  
*(Replace `python` with `python3` if required in your environment.)*

#### Chief Editor Agent
```bash
# Chief Editor (Input: demo.chief.in, Output: demo.section.in)
python chief_editor_service.py
```

#### Section Editor Agent
```bash
# Section Editor (Input: demo.section.in, Output: demo.write.in)
python section_editor_service.py
```

#### Writer Agent
```bash
# Writer (Input: demo.write.in, Output: demo.verify.in)
python writer_service.py
```

#### Verifier Agent
```bash
# Verifier (Input: demo.verify.in, Outputs: demo.write.in, demo.done)
python verify_service.py
```

### 3. Run the client 
Use one of the following options to initiate the workflow and monitor results.

🧠 CLI Client

Publishes the request and logs the final output. 
```bash
python client.py --area "Quantum Computing Ethics" --max-topics 1 --expected-results 4
```

💻 Streamlit UI

Provides an interactive web interface for configuration and real-time visualization.
```bash
streamlit run streamlit_client.py
```