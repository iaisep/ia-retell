import os
import urllib
import httpx
import asyncio
import urllib.parse
from retell import Retell
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException,WebSocket
from twilio_server import TwilioClient
from webhook import router as webhook_router
from twilio.twiml.voice_response import VoiceResponse
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from twilio.rest import Client
from fastapi.websockets import WebSocketState
import json

app = FastAPI()
twilio_client = TwilioClient()
twilio_client2 = Client(os.environ["TWILIO_ACCOUNT_ID"], os.environ["TWILIO_AUTH_TOKEN"])
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
    
class CallRequest(BaseModel):
    to: str
    sip_uri: str




@app.post("/call")
async def make_call(call_request: CallRequest):
    """
    Endpoint to handle outbound SIP calls from Twilio.
    """
    try:
        # Initiate a call via Twilio SIP
        call = twilio_client2.calls.create(
            to=f"sip:universidadisep.pstn.twilio.com",
            from_="+16282368196",
            ##sip_auth_username="your_sip_username",  # Optional SIP Auth
            ##sip_auth_password="your_sip_password",  # Optional SIP Auth
            url="https://iallamadas.universidadisep.com/twiml"
        )
        return {"status": "success", "call_sid": call.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/outbound-call")
async def make_call(call_request: CallRequest):
    """
    Endpoint to handle outbound SIP calls from Twilio.
    """
    try:
        # Initiate a call via Twilio SIP
        call = twilio_client2.calls.create(
            to=f"sip:universidadisep.pstn.twilio.com",
            from_="+16282368196",
            ##sip_auth_username="your_sip_username",  # Optional SIP Auth
            ##sip_auth_password="your_sip_password",  # Optional SIP Auth
            url="https://iallamadas.universidadisep.com/twiml"
        )
        return {"status": "success", "call_sid": call.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/twiml")
async def twiml_response(request: Request):
    """
    Endpoint to handle Twilio SIP call responses using TwiML.
    """
    voice_response = VoiceResponse()
    voice_response.say("This is a call from your SIP server.")
    return str(voice_response)
    

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
                    "Authorization": "Bearer key_cdec3f0a6377501ce7f9cbaa03b0",  # Reemplaza con tu token real
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        print(f"Error creating web call: {exc.response.text}")
        raise HTTPException(status_code=500, detail="Failed to create web call")


@app.post("/outbound-call2")
async def handle_twilio_voice_webhook(request: Request):
    body = await request.json()
    to_number = body.get('to_number')
    p_number = body.get('p_number')
    id_agent = body.get('id_agent')
    custom_variables = body.get('custom_variables',__name__)
    call = twilio_client.create_phone_call(p_number, to_number, id_agent, custom_variables)#from,to
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

        call_response = retell.call.register_phone_call(
            agent_id=agent_id_path,
            #audio_websocket_protocol="twilio",
            #audio_encoding="mulaw",
            #sample_rate=8000,  # Sample rate has to be 8000 for Twilio
            from_number=post_data["From"],
            to_number=post_data["To"],
            retell_llm_dynamic_variables=custom_variables,
            metadata={"twilio_call_sid": post_data["CallSid"]},

        )
        response = VoiceResponse()
        start = response.connect()
        start.stream(
            url=f"wss://iallamadas.universidadisep.com/llm-websocket/{call_response.call_id}"
            #url=f"wss://api.retellai.com/audio-websocket/{call_response.call_id}"
        )
        return PlainTextResponse(str(response), media_type="text/xml")
    except Exception as err:
        print(f"Error in twilio voice webhook: {err}")
        return JSONResponse(
            status_code=500, content={"message": "Internal Server Error_twillio_voice_webhook"}
        )
