import json
import os
from typing import List, Dict

import openai

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY


class NoCredentialsError(Exception):
    pass


def suggest_new_pairs(learnt_pairs: List[Dict[str, str]]) -> List[tuple]:
    pairs_for_prompt = "".join([f'{pair["english_text"]} - {pair["native_text"]}; ' for pair in learnt_pairs])
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {
                "role": "user",
                "content": (
                    "Generate 5 words/phrases in English with translation to Ukrainian "
                    "in json format with array of 2 string to learn for a person "
                    f"who last learned words/phrases: : {pairs_for_prompt}."
                ),
            }
        ],
        temperature=0.25,
    )
    return [(pair[0], pair[1]) for pair in json.loads(response["choices"][0]["message"]["content"])]
