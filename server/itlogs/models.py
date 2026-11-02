"""Wire and domain types shared by the server, the evals and (mirrored) the iOS client."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FrameMeta(BaseModel):
    """Sent by the phone before each JPEG frame on the WebSocket."""

    t_ms: int = Field(description="capture time on the phone, ms since session start")
    width: int
    height: int


class VoiceText(BaseModel):
    """Speech already recognized on the phone; the server only sees text."""

    t_ms: int
    text: str


class AudioMeta(BaseModel):
    """Sent by the phone before each binary PCM chunk (16-bit little-endian mono)."""

    t_ms: int
    encoding: Literal["PCM_24KHZ"] = "PCM_24KHZ"


class CaptureMeta(BaseModel):
    """The deliberate trigger: the wearer pressed the button or said "log it"."""

    t_ms: int


class WatchMeta(BaseModel):
    """Weighing mode on or off: the server reads the scale on its own while it is on. With
    ``ask`` the ear asks "..., right?" after each food; without it the foods are logged quietly
    and read back as a list when the session ends."""

    on: bool
    t_ms: int = 0
    ask: bool = False


class ClientMessage(BaseModel):
    kind: Literal["frame", "audio", "voice", "capture", "watch", "end_session"]
    frame: FrameMeta | None = None
    audio: AudioMeta | None = None
    voice: VoiceText | None = None  # text recognized on the phone (fallback path)
    capture: CaptureMeta | None = None
    watch: WatchMeta | None = None


class EntryRead(BaseModel):
    """One look at the scale: what the reader saw on one frame."""

    food: str = Field(description='short lowercase name, or "none" when nothing is on the scale')
    grams: float | None = Field(default=None, description="the display, converted to grams")
    confidence: float = Field(ge=0, le=1)
    raw: str | None = Field(default=None, description="what the model said, e.g. '113 unknown'")

    @property
    def readable(self) -> bool:
        # 0 is an empty or tared scale; a negative number is a scale tared with food on it
        # (2026-NOVEMBER-02 18:36, the apple as the tare): neither is a weight to log
        return self.food != "none" and self.grams is not None and self.grams > 0


class Nutrients(BaseModel):
    """What the grams mean, from a per-100 g table. None when the food is not in the table."""

    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sodium_mg: float


class Entry(BaseModel):
    """One logged food. ``status`` is the label the eval loop produced for free:
    agreed = both reads matched; confirmed = the wearer said yes to a read; corrected = the
    wearer changed the food or the grams by voice; spoken = no camera read at all, the wearer
    said the food and the grams (the hands-free fallback when the display cannot be read);
    auto = two matching reads in quiet weighing mode, nobody asked, read back at the end."""

    index: int
    food: str
    grams: float
    status: Literal["agreed", "confirmed", "corrected", "spoken", "auto"]
    reads: list[EntryRead] = Field(default_factory=list)
    nutrients: Nutrients | None = None
    t_ms: int


class Question(BaseModel):
    """What the server asked the wearer when the two reads disagreed."""

    text: str
    foods: list[str]
    grams: list[float]


class ServerMessage(BaseModel):
    kind: Literal["read", "entry", "ask", "say", "state"]
    read: EntryRead | None = None
    entry: Entry | None = None
    ask: Question | None = None
    say: str | None = Field(default=None, description="text for the phone to speak in the ear")
    entries: list[Entry] | None = None
    watching: bool | None = None  # rides on "state": weighing mode on or off


class Reply(BaseModel):
    """A spoken sentence, parsed. ``start``: weighing mode on ("I'm weighing my food").
    ``stop``: weighing mode off ("done"). ``log``: take a look at the scale now. ``confirm``:
    the read was right. ``correct``: the food and/or the grams given replace the read.
    ``cancel``: forget it. ``none``: not addressed to the logger."""

    action: Literal["start", "stop", "log", "confirm", "correct", "cancel", "none"]
    food: str | None = None
    grams: float | None = None
