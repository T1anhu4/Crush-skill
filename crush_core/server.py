"""Local-only web adapter. Launch with python -m crush_core.server."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .characters import CHARACTERS
from .engine import Engine
from .provider import validate_base

ROOT = Path(__file__).resolve().parents[1]
# Room for 4,000 characters even when supplementary Unicode is JSON-escaped.
MAX_REQUEST_BYTES = 65536


class RequestBodyLimit:
    """Bound actual API bytes before JSON parsing, including chunked requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/') or scope['method'] in {'GET', 'HEAD'}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                response = JSONResponse({'error': '请求过大。'}, status_code=413)
                return await response(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break

        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}

        return await self.app(scope, replay, send)


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if not self.path.exists():
                return {}
            return json.loads(self.path.read_text())

    def save(self, data):
        data = dict(data, base=validate_base(data['base']))
        if not data['model'].strip():
            raise ValueError('请输入模型名。')
        with self.lock:
            previous = json.loads(self.path.read_text()) if self.path.exists() else {}
            if not data['key']:
                # Never carry a key to another endpoint by accident.
                data['key'] = previous.get('key','') if previous.get('base','').rstrip('/')==data['base'] else ''
            if not data['key']:
                raise ValueError('请输入此服务的 API Key；本地无鉴权服务可填 local。')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,name = tempfile.mkstemp(prefix='.provider-',dir=self.path.parent)
            try:
                with os.fdopen(fd,'w') as f:
                    json.dump(data,f)
                os.replace(name,self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def public(self):
        data = self.get()
        return {'base':data.get('base','https://api.openai.com/v1'),'model':data.get('model',''), 'configured':bool(data.get('key'))}


class Create(BaseModel):
    character: str = 'lin'
    mode: str = 'demo'
    timezone: str = 'Asia/Shanghai'


class Send(BaseModel):
    content: str = Field(min_length=1,max_length=4000)
    request_id: str = Field(min_length=8,max_length=100)
    reply_to: str | None = None


class Advance(BaseModel):
    seconds: float = Field(ge=1,le=604800,allow_inf_nan=False)


class Pause(BaseModel):
    paused: bool


class Branch(BaseModel):
    message_id: str


class ModelSettings(BaseModel):
    base: str = Field(max_length=500)
    model: str = Field(max_length=160)
    key: str = Field(default='',max_length=2000)


def create_app(home=None, run_worker=True):
    home = Path(home or os.environ.get('CRUSH_V3_HOME', str(Path(os.environ.get('CRUSH_HOME',str(Path.home()/'.crush')))/'v3')))
    settings = Settings(home/'provider.json')
    engine = Engine(home/'crush.sqlite3',settings=settings.get)
    token = secrets.token_urlsafe(32)
    stop = threading.Event()

    def worker():
        while not stop.wait(.5):
            try:
                engine.tick()
            except Exception:
                # A failed job is surfaced by the engine. Keep the scheduler alive.
                import logging
                logging.getLogger('crush').exception('Scheduler iteration failed')

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=worker,daemon=True)
        if run_worker:
            thread.start()
        yield
        stop.set()
        if run_worker:
            await asyncio.to_thread(thread.join,1)

    app = FastAPI(title='Crush local API',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.engine = engine
    app.state.token = token
    # Added before local_only so host/origin/token rejection happens before reads.
    app.add_middleware(RequestBodyLimit)

    @app.middleware('http')
    async def local_only(request: Request,call_next):
        try:
            host = urlsplit('http://'+request.headers.get('host','')).hostname
        except ValueError:
            return JSONResponse({'error':'仅允许本机访问。'},status_code=403)
        if host not in {'localhost','127.0.0.1','::1','testserver'}:
            return JSONResponse({'error':'仅允许本机访问。'},status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'来源不匹配。'},status_code=403)
        if request.url.path.startswith('/api/') and request.method not in {'GET','HEAD'}:
            if not secrets.compare_digest(request.headers.get('x-crush-token',''),token):
                return JSONResponse({'error':'连接已更新，请刷新页面。'},status_code=403)
            try:
                size = int(request.headers.get('content-length','0') or 0)
                if size < 0:
                    raise ValueError('negative length')
            except ValueError:
                return JSONResponse({'error':'请求长度无效。'},status_code=400)
            if size>MAX_REQUEST_BYTES:
                return JSONResponse({'error':'请求过大。'},status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse({'error':str(exc)},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Pydantic errors include raw input (including keys and private messages).
        # Return only allowlisted field labels, never input/ctx or raw error text.
        labels = {'base': '服务地址', 'model': '模型名称', 'key': 'API Key',
                  'content': '消息内容', 'request_id': '消息标识', 'seconds': '时间间隔'}
        fields = dict.fromkeys(labels[item['loc'][-1]] for item in exc.errors()
                               if item.get('loc') and item['loc'][-1] in labels)
        message = '、'.join(fields) + '格式或长度不正确。' if fields else '请求格式不正确，请检查输入后重试。'
        return JSONResponse({'error': message}, status_code=422)

    @app.get('/api/bootstrap')
    def bootstrap():
        return {'token':token,'characters':list(CHARACTERS.values()),'sessions':engine.list(),'settings':settings.public()}

    @app.get('/api/sessions')
    def sessions():
        return engine.list()

    @app.post('/api/sessions')
    def create(body:Create):
        return engine.create(body.character,body.mode,body.timezone)

    @app.get('/api/sessions/{sid}')
    def snapshot(sid:str):
        return engine.snapshot(sid)

    @app.post('/api/sessions/{sid}/messages')
    def send(sid:str,body:Send):
        return engine.send(sid,body.content,body.request_id,body.reply_to)

    @app.post('/api/sessions/{sid}/messages/{mid}/withdraw')
    def withdraw(sid:str,mid:str):
        return engine.withdraw(sid,mid)

    @app.post('/api/sessions/{sid}/jobs/{jid}/retry')
    def retry(sid:str,jid:str):
        return engine.retry(sid,jid)

    @app.post('/api/sessions/{sid}/advance')
    def advance(sid:str,body:Advance):
        return engine.advance(sid,body.seconds)

    @app.post('/api/sessions/{sid}/pause')
    def pause(sid:str,body:Pause):
        return engine.pause(sid,body.paused)

    @app.get('/api/sessions/{sid}/review')
    def review(sid:str):
        return engine.review(sid)

    @app.post('/api/sessions/{sid}/branch')
    def branch(sid:str,body:Branch):
        return engine.branch(sid,body.message_id)

    @app.get('/api/sessions/{sid}/export')
    def export(sid:str):
        return engine.export(sid)

    @app.delete('/api/sessions/{sid}')
    def delete(sid:str):
        engine.delete(sid)
        return {'deleted':True}

    @app.post('/api/settings')
    def configure(body:ModelSettings):
        settings.save(body.model_dump())
        return settings.public()

    @app.get('/api/sessions/{sid}/events')
    async def events(sid:str,request:Request):
        engine.snapshot(sid)
        async def stream():
            revision = -1
            while not await request.is_disconnected():
                try:
                    snap = await asyncio.to_thread(engine.snapshot,sid)
                except ValueError:
                    yield 'event: deleted\ndata: {}\n\n'
                    return
                if snap['revision'] != revision:
                    revision = snap['revision']
                    yield 'data: '+json.dumps(snap,ensure_ascii=False)+'\n\n'
                else:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

    dist = ROOT/'web'/'dist'
    if dist.exists():
        app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    else:
        @app.get('/')
        def not_built():
            return {'message':'请先在 web 目录运行 npm install && npm run build。'}
    return app


def main():
    import argparse
    import uvicorn
    parser=argparse.ArgumentParser(description='Crush local GUI')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--home')
    args=parser.parse_args()
    uvicorn.run(create_app(args.home),host='127.0.0.1',port=args.port,timeout_graceful_shutdown=3)


if __name__=='__main__':
    main()
