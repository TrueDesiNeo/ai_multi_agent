# 📥 Client

The **Client** (`client.py`) is a lightweight command-line interface tool used to initiate and monitor the content generation workflow. It connects to the **NATS** message bus, publishes the initial request, and waits for all final, approved results from the pipeline's end point.

---

## ✨ Key Features

* **Request Initiation:** Publishes the **root request** directly to the Chief Editor service's input subject.
* **Result Monitoring:** Subscribes to the final output subject (`demo.done`) and **filters messages by `conversation_id`** to ensure correlation.
* **Streaming Logs:** Streams incoming results to the logs until a specified message count is reached or timeout limits are hit.
* **Config Flexibility:** Uses a `Config` dataclass for **environment-driven configuration**.
* **Security:** Supports **TLS** for NATS connections, with an option for a custom CA bundle.
* **Clean Exit:** Implements **signal handlers** for a clean shutdown.

---

## 🚀 Usage

The client is executed via the command line, where you pass the content generation parameters as arguments.

### Execution Example

```bash
python a2a_client.py \
    --area "AI in Climate Modeling" \
    --max-topics 2 \
    --max-sections 4 \
    --style "technical, SEO-aware, concise" \
    --sources "IPCC 2023" "NASA EarthData" \
    --research-notes "Focus on real-time inference and satellite data fusion." \
    --expected-results 8
```


# 🖥️ Streamlit Client

The **Streamlit Client** (`streamlit_client.py`) provides a rich, interactive web interface for interacting with the hierarchical content generation pipeline. It simplifies the process of initiating a request, observing the live progress, and reviewing the final, approved results.

---

## ✨ Key Features

* **Interactive UI:** A **Streamlit-based** application offering an easy-to-use web interface for the content pipeline.
* **Pipeline Initiation:** Publishes a **seed envelope** (the root request) directly to the **Chief Editor agent** via NATS.
* **Real-time Monitoring:** Subscribes to the final output subject (`demo.done`) and **streams matching results** filtered by the unique `conversation_id`.
* **Data Visualization:** **Displays drafts, quality scores, and rich metadata** directly within the Streamlit UI.
* **Content Download:** Supports **downloading individual or all drafts** in formats like markdown or a compressed ZIP file.
* **NATS Configuration:** Allows configuration of the NATS connection, including optional **TLS support**.

---

## 🏗️ Functionality

The client provides the full user-facing interaction:

1.  **Configuration:** Reads NATS connection details, subject names, and timeout settings from environment variables.
2.  **Request Input:** Provides a form in the UI for users to input parameters (area, topics, style, etc.) for the root content request.
3.  **Publish:** On submission, a root envelope is created and published to the **Chief Editor's input subject (`SUBJ_CHIEF_IN`)**.
4.  **Subscription:** Immediately subscribes to the **Final Done subject (`SUBJ_DONE`)** to begin listening for results matching the generated `conversation_id`.
5.  **Display:** As final drafts arrive, the UI updates dynamically, presenting the content, verification score, and relevant metadata for the user.

---

## 🚀 Usage

The client is run using the Streamlit CLI command:

```bash
streamlit run streamlit_client.py
```