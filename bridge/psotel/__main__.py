"""ブリッジの起動口。

    OTLP_METRICS_ENDPOINT=http://localhost:4318/v1/metrics python -m psotel
"""

import os

import uvicorn

from .app import create_app
from .otlp import create_emitter

DEFAULT_ENDPOINT = "http://localhost:4318/v1/metrics"


def main() -> None:
    endpoint = os.environ.get("OTLP_METRICS_ENDPOINT", DEFAULT_ENDPOINT)
    app = create_app(emit=create_emitter(endpoint))
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
