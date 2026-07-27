"""pScheduler HTTP archiver の受信エンドポイント。"""

import logging
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .convert import Metric, convert

logger = logging.getLogger(__name__)

Emit = Callable[[list[Metric]], None]


def create_app(emit: Emit) -> FastAPI:
    app = FastAPI(title="psotel-bridge")

    # archiver は既定で op:put のため PUT を受ける。POST も同じ扱いにしておく
    @app.api_route("/archive", methods=["PUT", "POST"])
    async def archive(request: Request):
        # archiver は外部入力なので、ここが検証の境界になる。
        # 変換に失敗したら 200 を返さない。200 だとデータが消えたことが
        # archiver 側の run 詳細に残らず、欠損に誰も気付けない
        envelope = None
        try:
            envelope = await request.json()
            metrics = convert(envelope)
        except Exception:
            logger.exception("封筒の変換に失敗した。test.type=%s", _test_type(envelope))
            return JSONResponse({"status": "error"}, status_code=500)

        emit(metrics)
        return {"status": "ok"}

    return app


def _test_type(envelope) -> str:
    """ログ用にテスト種別だけ安全に取り出す。"""
    if isinstance(envelope, dict):
        return (envelope.get("test") or {}).get("type", "(不明)")
    return "(封筒を解釈できず)"
