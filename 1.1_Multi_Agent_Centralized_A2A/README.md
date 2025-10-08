This folder implements the multi-agent centralized pattern within a distributed environment. This architecture is designed for scalability and resilience by deploying individual agents across separate virtual machines (VMs) or distinct network endpoints.

Distribution: Agents are deployed across different Virtual Machines (VMs).

Inter-Agent Communication (IAC): Communication between the distinct agents is facilitated using the Google Agent-to-Agent (A2A) protocol. This protocol ensures reliable and structured message passing between agents residing on separate host machines.

Scope: Suitable for production environments requiring horizontal scaling, fault isolation, and the distribution of computational load across a network infrastructure.

Directory structure:

    Multi_Agent_Centralized_A2A/
    ├── CoordinatorAgent/   
    │   ├── coordinator.py
    │   ├── __main__.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── RetrieverAgent/     
    │   ├── retriever.py
    │   ├── __main__.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── WriterAgent/        
    │   ├── writer.py
    │   ├── __main__.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    ├── ReviewerAgent/          
    │   ├── review.py
    │   ├── __main__.py
    │   ├── .env
    │   ├── README.MD
    │   └── requirements.txt
    |
    └── Client/
        ├── client.py
        ├── .env
        ├── README.MD    
        └── requirements.txt
