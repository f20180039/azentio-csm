from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .api_client import ApiUnavailable, RenewalsApi
from .brain import CallBrain, ChatClient, GroqChatClient
from .config import Settings, load_settings
from .prompt import system_prompt


class State:
    def __init__(self) -> None:
        self.api: RenewalsApi | None = None
        self.llm: ChatClient | None = None
        self.brains: dict[str, CallBrain] = {}
        self._settings: Settings | None = None

    def settings(self) -> Settings:
        if self._settings is None:
            env_file = Path(__file__).resolve().parents[2] / ".env"
            self._settings = load_settings(env_file if env_file.exists() else None)
        return self._settings

    def get_api(self) -> RenewalsApi:
        if self.api is None:
            self.api = RenewalsApi(self.settings())
        return self.api

    def get_llm(self) -> ChatClient:
        if self.llm is None:
            self.llm = GroqChatClient(self.settings())
        return self.llm


state = State()
app = FastAPI(title="Renewal Desk voice")


class TextCallIn(BaseModel):
    callId: str


class TextTurnIn(BaseModel):
    callId: str
    text: str


@app.post("/v1/text-call")
async def text_call(body: TextCallIn) -> dict:
    existing = state.brains.get(body.callId)
    if existing is not None:
        return {"greeting": existing.greeting}
    api = state.get_api()
    try:
        call = await api.call(body.callId)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    if call.get("error") or not call.get("greeting"):
        raise HTTPException(404, "unknown call")
    brain = CallBrain(state.get_llm(), api, body.callId, system_prompt(call["greeting"]))
    await brain.say(call["greeting"])
    brain.greeting = call["greeting"]
    state.brains[body.callId] = brain
    return {"greeting": call["greeting"]}


@app.post("/v1/text-turn")
async def text_turn(body: TextTurnIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "text must not be blank")
    brain = state.brains.get(body.callId)
    if brain is None:
        raise HTTPException(404, "unknown call")
    try:
        turn = await brain.reply(body.text)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "language model unavailable") from e
    return {
        "reply": turn.text,
        "toolCalls": [{"name": t.name, "args": t.args, "result": t.result} for t in turn.tool_calls],
    }
