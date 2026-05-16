from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse
from contextlib import asynccontextmanager

from app.config import settings
from app.database import init_db
from app.api import api_router
from app.caldav.router import caldav_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CalDAV middleware — intercepts WebDAV methods before FastAPI routing
@app.middleware("http")
async def caldav_middleware(request: Request, call_next):
    path = request.url.path
    is_caldav = path.startswith("/caldav/") or path == "/caldav" or path == "/.well-known/caldav"
    is_webdav = request.method.upper() in ("PROPFIND", "REPORT", "MKCALENDAR", "PROPPATCH", "MKCOL", "COPY", "MOVE", "LOCK", "UNLOCK")
    
    if is_caldav or is_webdav:
        # Let CalDAV ASGI app handle the request
        async def receive():
            return {"type": "http.request", "body": await request.body(), "more_body": False}
        
        scope = {"type": "http", "method": request.method, "path": path, "headers": list(request.headers.raw),
                 "query_string": request.url.query.encode() if request.url.query else b"",
                 "root_path": "", "server": ("localhost", 8000), "client": request.client or ("localhost", 0),
                 "scheme": "http", "http_version": "1.1"}
        
        response_started = False
        response_body = []
        response_status = None
        response_headers = []

        async def _send(message):
            nonlocal response_started, response_status, response_headers
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                response_headers = [(k.decode(), v.decode()) for k, v in message.get("headers", [])]
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))
        
        await caldav_app(scope, receive, _send)
        if response_status:
            r = Response(content=b"".join(response_body), status_code=response_status)
            for k, v in response_headers:
                r.headers[k] = v
            return r
        return Response(status_code=500)
    
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/.well-known/caldav")
async def wellknown_redirect():
    """Redirect GET requests for .well-known/caldav to CalDAV service root."""
    return RedirectResponse(url="/caldav/", status_code=301)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
