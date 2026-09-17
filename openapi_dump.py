"""Write the generated OpenAPI schema to stdout or a file.

The schema is generated from the app rather than hand-maintained, so it cannot
drift from the models. Commit it only if you want reviewable diffs of contract
changes; CI regenerates it either way.
"""

from __future__ import annotations

import json
import sys

from jarvis_host_agent.app import build_app
from jarvis_host_agent.config import Config
from tests.conftest import StubProvider


def main() -> None:
    app = build_app(
        config=Config(host="127.0.0.1", port=7724, token="unused", platform_override=None),
        provider=StubProvider(),
    )
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as handle:
            handle.write(schema + "\n")
    else:
        print(schema)


if __name__ == "__main__":
    main()
