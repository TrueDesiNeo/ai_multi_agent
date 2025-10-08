## Multi-Agent Centralized (Local Deployment)

### `1_Multi_Agent_Centralized`

This folder contains the implementation for a **multi-agent centralized pattern** where all computational agents operate within a single, local execution environment (e.g., one machine or server).

* **Architecture:** Centralized control flow managed via **LangGraph**.
* **User Interface:** An interactive UI is provided using **Streamlit** to facilitate monitoring and interaction with the agent system.
* **Scope:** Ideal for proof-of-concept development, local testing, and scenarios where agents have high-throughput, low-latency communication requirements and share a unified computational resource pool.


### Directory Structure: `1_Multi_Agent_Centralized`

The structure below reflects the independent nature of each agent and the client, where each directory represents a potentially separate deployment unit (e.g., a distinct VM or service container).

Directory structure:

    1_Multi_Agent_Centralized/
    ├── agents/   
    │   ├── coordinator.py
    │   ├── retriever.py
    │   ├── verifier.py
    │   └── writer.py
    ├── .env
    ├── requirements.txt
    ├── agent.py
    ├── config.py
    ├── state.py
    ├── workflow.py     
    └── ui_streamlit.py


## Execution Command

To run the Streamlit UI, execute the following command in your terminal within the respective directory:

```bash
streamlit run ui_streamlit.py