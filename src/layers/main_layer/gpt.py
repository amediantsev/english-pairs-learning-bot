import json
import os
from typing import List, Dict
import re

import backoff
import openai

from exceptions import GptResponseFormatError

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

NUM_LIST_REGEX = re.compile(r"^\d+\.\s*")


@backoff.on_exception(backoff.expo, GptResponseFormatError, max_tries=3)
def suggest_new_pairs(learnt_pairs: List[Dict[str, str]]) -> List[tuple]:
    if not learnt_pairs:
        return []
    pairs_for_prompt = "".join([f'{pair["english_text"]} - {pair["native_text"]}; ' for pair in learnt_pairs])
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {
                "role": "user",
                "content": (
                    "Generate 5 words/phrases in English with translation to Ukrainian "
                    "in json format with array of 2 strings to learn for a person "
                    f"who last learned words/phrases: {pairs_for_prompt}."
                ),
            }
        ],
        temperature=0.25,
    )
    print(response)
    try:
        raw_generated_pairs = json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError):
        raise GptResponseFormatError()

    return [
        (NUM_LIST_REGEX.sub("", pair[0]), NUM_LIST_REGEX.sub("", pair[1]))
        for pair in raw_generated_pairs  # fmt: skip
    ]
