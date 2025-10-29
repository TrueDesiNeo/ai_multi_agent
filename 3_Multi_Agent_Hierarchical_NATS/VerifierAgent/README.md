# ✅ Verifier Agent

The **Verifier Agent** (`verify_service.py`) acts as the quality gate for the content generation pipeline. Implemented as a **NATS-backed Python service**, it is responsible for evaluating the quality of draft content, initiating revisions if necessary, and ultimately publishing the approved final content.

---

## 🌟 Key Features

* **Quality Scoring:** Scores the draft content using an **LLM (Large Language Model)** with a **heuristic fallback** mechanism.
* **Revision Loop:** Manages a **revision request loop** by sending drafts back to the Writer if the score is below the threshold and retries are available.
* **Finalization:** Publishes the **approved draft** to a client-facing subject (`demo.done`).
* **TLS Support:** Secure connections to NATS with **optional custom CA**.
* **Observability:** Maintains **structured logging** and **A2A envelope trace/context propagation** across all services.
* **Graceful Shutdown:** Supports **graceful shutdown** via `SIGINT`/`SIGTERM`.

---

## 🏗️ Functionality & Workflow

The service manages the final verification and approval process:

1.  **Listens** on the designated input NATS subject for A2A envelopes containing the latest content draft from the Writer service.
2.  **Scores** the draft using the LLM (or a heuristic method) to determine quality.
3.  **Decision Branch:**
    * If the **score is below the minimum acceptable threshold** and **retries remain**, it generates a child envelope requesting a revision and publishes it back to the **Writer subject** (`demo.write.in`).
    * If the **score meets the threshold** or **no retries remain**, it finalizes the draft and publishes the approved content to the **Final Output subject** (`demo.done`).

---

## 📡 NATS Subjects

The Verifier service is a crucial routing point, using multiple output subjects:

| Type | Subject | Description |
| :--- | :--- | :--- |
| **Input** | `demo.verify.in` | Subject the service **listens** on for incoming drafts from the Writer service. |
| **Output (Revision)** | `demo.write.in` | Subject for sending the draft back to the Writer service to request a **revision**. |
| **Output (Final)** | `demo.done` | Subject for publishing the **final, approved** content to the client or next stage. |

---

## ⚙️ Configuration (Environment Variables)

The service requires configuration for both NATS connectivity and operational logic:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NATS_HOST` | `127.0.0.1` | The hostname or IP address of the NATS server. |
| `NATS_PORT` | `4222` | The port for the NATS server connection. |
| `NATS_USER` | `""` | Username for NATS authentication (if required). |
| `NATS_PASS` | `""` | Password for NATS authentication (if required). |
| `NATS_TLS` | `"true"` | Enables or disables TLS for the NATS connection. |
| `NATS_TLS_CAFILE` | `None` | Path to a custom CA certificate bundle (PEM format) for NATS TLS (optional). |
| `MIN_ACCEPTABLE_SCORE` | `7.0` | The minimum score a draft must achieve to be approved and finalized. |

---

## 🚀 Getting Started

### Prerequisites

* **Python 3.10+**
* **NATS Server** running and accessible.

### Dependencies

Install the required external Python libraries:

```bash
pip install -r requirements.txt


```bash
python verify_service.py
