"""pScheduler HTTP archiver の受信エンドポイント。"""

from collections.abc import Callable

from fastapi import FastAPI, Request

from .convert import Metric, convert

Emit = Callable[[list[Metric]], None]


def create_app(emit: Emit) -> FastAPI:
    app = FastAPI(title="psotel-bridge")

    # archiver は既定で op:put のため PUT を受ける。POST も同じ扱いにしておく
    @app.api_route("/archive", methods=["PUT", "POST"])
    async def archive(request: Request) -> dict[str, str]:
        envelope = await request.json()
        emit(convert(envelope))
        return {"status": "ok"}

    return app
