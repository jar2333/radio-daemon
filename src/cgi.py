from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
import imghdr
import datetime

DAEMON_DIR = "/home/elaine/app/source_daemon"

app = FastAPI()

app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

@app.get("/metadata")
async def get_metadata():
    with open(f"{DAEMON_DIR}/tmp/metadata.txt", "r") as f:
        m = f.read()
        return dict([tuple(l.split('=')) for l in m.split('\n')])

@app.get("/image",
    response_class=Response,
)
async def get_image():
    headers = {"Cache-Control": "no-store"}
    image_type = imghdr.what("tmp/current")
    with open(f"{DAEMON_DIR}/tmp/current", "rb") as f:
        return Response(content=f.read(), media_type=f"image/{image_type}", headers=headers)

@app.get("/time", 
    response_class=PlainTextResponse
)
async def get_time():
    return str(datetime.datetime.now(datetime.timezone.utc))