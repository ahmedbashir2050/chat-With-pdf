# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from .api.routers import auth, chats, messages
# from .database import Base, engine

# Base.metadata.create_all(bind=engine)

# app = FastAPI(title="Chat with PDF API")

# # Tighten allow_origins to your actual app's domain/scheme in production.
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(auth.router)
# app.include_router(chats.router)
# app.include_router(messages.router)


# @app.get("/")
# def root():
#     return {"status": "ok"}
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .api.routers import auth, chats, messages
from .database import Base, engine


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        # -------------------------
        # REQUEST
        # -------------------------
        body = await request.body()

        print("\n========== REQUEST ==========")
        print(f"{request.method} {request.url}")

        if body:
            try:
                request_json = json.loads(body)
                print(json.dumps(
                    request_json,
                    indent=2,
                    ensure_ascii=False
                ))
            except Exception:
                print(body.decode("utf-8", errors="replace"))
        else:
            print("(empty body)")

        # -------------------------
        # PROCESS REQUEST
        # -------------------------
        response = await call_next(request)

        # -------------------------
        # RESPONSE
        # -------------------------
        response_body = b""

        async for chunk in response.body_iterator:
            response_body += chunk

        print("========== RESPONSE ==========")
        print(f"Status: {response.status_code}")

        if response_body:
            try:
                response_json = json.loads(response_body)
                print(json.dumps(
                    response_json,
                    indent=2,
                    ensure_ascii=False
                ))
            except Exception:
                print(response_body.decode("utf-8", errors="replace"))
        else:
            print("(empty body)")

        print("==============================\n")

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )


# -------------------------
# DATABASE
# -------------------------
Base.metadata.create_all(bind=engine)


# -------------------------
# FASTAPI
# -------------------------
app = FastAPI(title="Chat with PDF API")


# -------------------------
# REQUEST/RESPONSE LOGGING
# -------------------------
app.add_middleware(RequestResponseLoggingMiddleware)


# -------------------------
# CORS
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------
# ROUTERS
# -------------------------
app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(messages.router)


# -------------------------
# ROOT
# -------------------------
@app.get("/")
def root():
    return {"status": "ok"}

