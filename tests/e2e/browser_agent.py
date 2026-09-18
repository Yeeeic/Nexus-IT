"""Keep a real diagnostic-only agent available for interactive browser acceptance.

Run only in the disposable e2e-runner service. Enrollment credentials and the
issued agent token stay in memory. The process cannot reboot or change services.
"""
import base64
import os
from pathlib import Path
import tempfile
import time

from exercise import BASE, Console
from agent.nexus_agent.actions import SQLiteActionStore
from agent.nexus_agent.storage import LocalQueue
from agent.run_agent import NexusAgent, make_action_handlers


def main() -> None:
    console = Console()
    console.request("POST", "/auth/login", {
        "email": os.environ["NEXUS_E2E_EMAIL"],
        "password": os.environ["NEXUS_E2E_PASSWORD"],
    })
    device = console.request("POST", "/devices", {
        "hostname": "e2e-browser-agent", "display_name": "Agente real para ensayo de navegador",
    }, expected=201)
    with tempfile.TemporaryDirectory(prefix="nexus-e2e-browser-") as temporary:
        state = Path(temporary)
        handlers = make_action_handlers()
        agent = NexusAgent(BASE, device["id"], device["token"], LocalQueue(state / "agent.db"),
            action_store=SQLiteActionStore(state / "actions.sqlite3"),
            public_keys={1: base64.b64decode(os.environ["NEXUS_E2E_PUBLIC_KEY"])},
            action_handlers={"collect_extended_diagnostics": handlers["collect_extended_diagnostics"]},
        )
        print("Browser diagnostic agent ready: " + device["id"], flush=True)
        while True:
            agent.collect_and_send_inventory()
            agent.collect_and_enqueue()
            agent.dispatcher.dispatch_once()
            count = agent.poll_and_execute_actions()
            if count:
                print(f"Diagnostic actions executed: {count}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
