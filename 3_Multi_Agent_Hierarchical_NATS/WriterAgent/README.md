# 🖋️ Writer Agent

The **Writer Agent** (`writer_service.py`) is the engine for content creation in the pipeline. Implemented as a **NATS-backed Python service**, its main function is to receive section outlines from the Section Editor, use an LLM to generate the draft content, and forward the result to the Verifier for quality control.

---

## ✨ Key Features

* **LLM-Powered Drafting:** Delegates to the **`WriterAgent`** to generate section drafts using a **Large Language Model (LLM)**.
* **Revision Handling:** Capable of receiving both initial drafting requests and **revision requests** from the Verifier (via the same input subject `demo.write.in`).
* **Pydantic Compatibility:** Ensures seamless message serialization, supporting **Pydantic v1/v2 JSON compatibility** for publishing.
* **TLS Support:** Secure connections to NATS with **optional custom CA**.
* **Observability:** Maintains **structured logging** and **A2A envelope trace/context propagation** across all services.
* **Graceful Shutdown:** Supports **graceful shutdown** via `SIGINT`/`SIGTERM`.

---

## 🏗️ Functionality & Workflow

The service manages the content generation process:

1.  **Listens** on the designated input NATS subject for A2A envelopes containing drafting instructions (topic, sections, or revision notes) from the **Section Editor** or the **Verifier**.
2.  **Extracts** the necessary **drafting parameters** from the incoming envelope's payload.
3.  **Delegates** the content generation task to the **`WriterAgent`** to produce the section draft via the LLM.
4.  **Publishes** the newly generated draft within a child A2A envelope to the **Verifier subject** (`demo.verify.in`) for quality check and approval.

---

## 📡 NATS Subjects

| Type | Subject | Description |
| :--- | :--- | :--- |
| **Input** | `demo.write.in` | Subject the service **listens** on for incoming drafting requests (initial or revision) from the Section Editor or Verifier. |
| **Output** | `demo.verify.in` | Subject the service **publishes** the generated section draft to, forwarding it to the Verifier service. |

---

## ⚙️ Configuration (Environment Variables)

The service is configured primarily via environment variables for NATS connection settings:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NATS_HOST` | `127.0.0.1` | The hostname or IP address of the NATS server. |
| `NATS_PORT` | `4222` | The port for the NATS server connection. |
| `NATS_USER` | `""` | Username for NATS authentication (if required). |
| `NATS_PASS` | `""` | Password for NATS authentication (if required). |
| `NATS_TLS` | `"true"` | Enables or disables TLS for the NATS connection. |
| `NATS_TLS_CAFILE` | `None` | Path to a custom CA certificate bundle (PEM format) for NATS TLS (optional). |

---

## 🚀 Getting Started

### Prerequisites

* **Python 3.10+**
* **NATS Server** running and accessible.
* **LLM API access** (as utilized by `WriterAgent`).

### Dependencies

#### Install the required external Python libraries:
```bash
pip install -r requirements.txt
```

#### Start the Writer Agent
```bash
python writer_service.py
```