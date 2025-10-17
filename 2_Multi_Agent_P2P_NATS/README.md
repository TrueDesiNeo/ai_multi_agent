## Multi-Agent DeCentralized (P2P) (Distributed Deployment)

This folder implements the **multi-agent DeCentralized (P2P) pattern** within a **distributed environment**. This sophisticated architecture is explicitly designed for **scalability** and **resilience** by deploying individual agents across separate **Virtual Machines (VMs)** or distinct network endpoints.

| Feature | Description |
| :--- | :--- |
| **Distribution** | Agents are deployed across different **Virtual Machines (VMs)**. |
| **Inter-Agent Communication (IAC)** | Communication between distinct agents is facilitated using the **NATS**. This protocol ensures reliable and structured message passing between agents residing on separate host machines. |
| **Scope** | Suitable for **production environments** requiring **horizontal scaling**, fault isolation, and the distribution of computational load across a network infrastructure. |

### Directory Structure: `2.Multi_Agent_P2P_NATS`

The structure below reflects the independent nature of each agent and the client, where each directory represents a potentially separate deployment unit (e.g., a distinct VM or service container).

Directory structure:

    Multi_Agent_P2P_NATS/
    ├── Common/a2a_protocol   
    │   ├── __init__.py
    │   ├── README.MD
    │   ├── common_envelope.py
    │   └── common_trace.py
    |
    ├── RetrieverAgent/     
    │   ├── retriever_agent.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── WriterAgent/        
    │   ├── writer_agent.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── ReviewerAgent/          
    │   ├── reviewer_agent.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    └── Client/
        ├── send_task.py
        ├── .env
        ├── README.MD    
        └── requirements.txt
