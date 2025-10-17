## Execution Command

This is a simple demo client that connects to a NATS server, publishes a research task, and waits for the final response on `demo.done`.  
It matches responses using a `conversation_id` to ensure correctness.


| Scenario | Command | Description |
| :--- | :--- | :--- |
| **Example 1: Default Question** | `python send_task.py` | Executes the client using a pre-defined default question and standard configuration parameters. |
| **Example 2: Custom Question with Parameters** | `python demo_client.py --task "Explain quantum computing in simple terms."` | Executes the client with a custom question and overrides default settings for maximum search results and retry attempts. |
