from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Transcript:
    words: list[Word]
    text: str

    def to_dict(self) -> dict:
        return {"text": self.text, "words": [asdict(w) for w in self.words]}

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(words=[Word(**w) for w in d["words"]], text=d["text"])


@dataclass
class Acoustics:
    times: list[float]
    f0_hz: list[float | None]
    intensity_db: list[float]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Acoustics":
        return cls(**d)


@dataclass
class Pause:
    after_word: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start
