from dataclasses import dataclass

@dataclass
class ASR:
    text: str
    conf: float

def transcribe(seconds:int=4) -> ASR:
    # TODO: call Whisper. For now, stub a response.
    return ASR(text="Hi, I have a package for Amanda", conf=0.85)
