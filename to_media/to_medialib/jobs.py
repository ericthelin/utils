"""A job is plain data: which recipe, which inputs, where the output goes.

It never holds a shell command, so a job can be queued and sent to another
machine, which rebuilds the command from the recipe it already knows.
"""

import dataclasses
import json


@dataclasses.dataclass
class Job:
    recipe: str
    inputs: list
    output: str
    options: dict = dataclasses.field(default_factory=dict)

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(data["recipe"], list(data["inputs"]), data["output"], dict(data.get("options", {})))

    def to_json(self):
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))
