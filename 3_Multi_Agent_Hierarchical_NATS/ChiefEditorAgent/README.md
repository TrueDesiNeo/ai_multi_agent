# 📰 Chief Editor Agent

The **Chief Editor Agent** (`chief_editor_service.py`) is a core component of the system, implemented as a **NATS-backed Python service**. Its primary role is to orchestrate the topic generation process by receiving incoming requests, proposing a set of topics using an internal agent, and distributing these topics to the next stage in the workflow.

---

## 🌟 Key Features

* **NATS Communication:** Utilizes **NATS** for asynchronous, message-based communication.
* **TLS Support:** Secure connections to the NATS server with **optional custom CA** configuration.
* **A2A Envelope Processing:** Handles standardized **Application-to-Application (A2A) envelopes** for data transfer.
* **Conversation Tracing:** Supports **tracing and conversation correlation** across messages for end-to-end observability.
* **Structured Logging:** Implements **structured logging** to facilitate monitoring and debugging.
* **Graceful Shutdown:** Provides mechanisms for a **graceful shutdown** upon receiving `SIGINT` or `SIGTERM` signals.
* **Topic Delegation:** Delegates the core logic of topic proposal to the dedicated `ChiefEditorAgent`.
* **Fan-Out:** Distributes the proposed topics to downstream services via the section editor subject.

---

## 🛠️ Functionality Summary

The service performs the following steps upon receiving a message:

1.  **Listens** on the designated input NATS subject for A2A envelopes.
2.  **Extracts** the request payload (e.g., area, limits) from the A2A envelope.
3.  **Delegates** to the `ChiefEditorAgent` to propose the relevant topics.
4.  **Creates** child A2A envelopes for each proposed topic, maintaining the original `conversation_id` and updating the trace context.
5.  **Fan-Outs** the child envelopes to the Section Editor subject for further processing.
6.  **Serializes** outgoing messages using **pydantic v2 JSON serialization** (`model_dump_json`).

---

## 📡 NATS Subjects

| Type | Subject | Description |
| :--- | :--- | :--- |
| **Input** | `demo.chief.in` | Subject the service **listens** on for incoming A2A envelopes (requests). |
| **Output** | `demo.section.in` | Subject the service **publishes** child A2A envelopes (fan-out topics) to. |

---

## ⚙️ Configuration (Environment Variables)

The following environment variables are used to configure the NATS connection and TLS settings:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NATS_HOST` | `127.0.0.1` | The hostname or IP address of the NATS server. |
| `NATS_PORT` | `4222` | The port for the NATS server connection. |
| `NATS_USER` | `""` | Username for NATS authentication (if required). |
| `NATS_PASS` | `""` | Password for NATS authentication (if required). |
| `NATS_TLS` | `"true"` | Enables or disables TLS for the NATS connection. |
| `NATS_TLS_CAFILE` | `None` | Path to a custom CA certificate file for NATS TLS (optional). |

---

## 🚀 Getting Started

### Prerequisites

* **Python 3.10+**
* **NATS Server** running and accessible.

### Dependencies

#### To run the service, you need to install the required external Python libraries:
```bash
pip install -r requirements.txt
```

#### Start the Chief Editor Agent
```bash
python chief_editor_service.py
```