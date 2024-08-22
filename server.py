import os
import urllib
import httpx
import asyncio
import urllib.parse
from retell import Retell
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from twilio_server import TwilioClient
from webhook import router as webhook_router
from twilio.twiml.voice_response import VoiceResponse
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
twilio_client = TwilioClient()
retell = Retell(api_key= os.getenv('RETELL_API_KEY'))


#Mofify the phone number for inbound calls.
twilio_client.register_phone_agent(os.getenv("PHONE_NUMBER"), os.getenv('RETELL_AGENT_ID'))

load_dotenv(override=True)

#Routers
app.include_router(webhook_router)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class WebCallRequest(BaseModel):
    agent_id: str
    metadata: dict = None
    retell_llm_dynamic_variables: dict = None

@app.post("/create-web-call")
async def create_web_call(request: WebCallRequest):
    payload = {"agent_id": request.agent_id}

    # Agregar opcionalmente los campos si son proporcionados
    if request.metadata:
        payload["metadata"] = request.metadata

    if request.retell_llm_dynamic_variables:
        payload["retell_llm_dynamic_variables"] = request.retell_llm_dynamic_variables

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.retellai.com/v2/create-web-call",
                json=payload,
                headers={
                    "Authorization": "Bearer f90c66b6-5bef-405f-920d-787e21bf2939",  # Reemplaza con tu token real
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        print(f"Error creating web call: {exc.response.text}")
        raise HTTPException(status_code=500, detail="Failed to create web call")


@app.post("/outbound-call")
async def handle_twilio_voice_webhook(request: Request):
    body = await request.json()
    to_number = body.get('to_number')
    custom_variables = body.get('custom_variables', None)
    call = twilio_client.create_phone_call(os.getenv("PHONE_NUMBER"), to_number, os.environ['RETELL_AGENT_ID'], custom_variables)#from,to
    return {"call_sid": call.sid, "msg": "done"}


@app.post("/call-status")
async def handle_status_callback(request: Request):
   body = await request.json()
   call_sid = body.get("call_sid")
   call = twilio_client.get_call_status(call_sid)
   return {
        "sid": call.sid,
        "duration": call.duration,
        "status": call.status,
        "direction": call.direction,
        "from": call.from_formatted,
        "to": call.to_formatted,
        "start_time": call.start_time,
        "end_time": call.end_time,
    }



class Item(BaseModel):
    phone: str


async def send_data(url ,item: Item):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url, json=item.model_dump()
        )
        if response.status_code not in range(200, 300):
            raise HTTPException(
                status_code=response.status_code, detail="Error calling external API"
            )
        return response.json()



@app.post("/twilio-voice-webhook/{agent_id_path}")
async def handle_twilio_voice_webhook(request: Request, agent_id_path: str):

    query_params = request.query_params
    custom_variables = {key: query_params[key] for key in query_params}

    try:
        # Check if it is machine
        post_data = await request.form()
        if "AnsweredBy" in post_data and post_data["AnsweredBy"] == "machine_start":
            call = twilio_client.get_call_status(post_data["CallSid"])
            url = os.getenv("GHL_VOICE_MAIL_URL")
            if url is not None and len(url) != 0:
                asyncio.create_task(
                    send_data( os.getenv("GHL_VOICE_MAIL_URL"),Item(phone=call.to))
                )
            twilio_client.end_call(post_data["CallSid"])
            return PlainTextResponse("")
        elif "AnsweredBy" in post_data:
            return PlainTextResponse("")

        url = os.getenv("GHL_VOICE_MAIL_URL")
        if url is not None and len(url) != 0:
            asyncio.create_task(
                    send_data( os.getenv("GHL_REMOVE_VOICE_MAIL_URL"),Item(phone=post_data["To"]))
            )

        call_response = retell.call.register(
            agent_id=agent_id_path,
            audio_websocket_protocol="twilio",
            audio_encoding="mulaw",
            sample_rate=8000,  # Sample rate has to be 8000 for Twilio
            from_number=post_data["From"],
            to_number=post_data["To"],
            retell_llm_dynamic_variables=custom_variables,
            metadata={"twilio_call_sid": post_data["CallSid"]},
        )
        response = VoiceResponse()
        start = response.connect()
        start.stream(
            url=f"wss://api.retellai.com/audio-websocket/{call_response.call_id}"
        )
        return PlainTextResponse(str(response), media_type="text/xml")
    except Exception as err:
        print(f"Error in twilio voice webhook: {err}")
        return JSONResponse(
            status_code=500, content={"message": "Internal Server Error"}
        )
