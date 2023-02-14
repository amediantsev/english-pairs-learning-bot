from boto3 import client

translate_client = client("translate")


def translate_text(text, from_lang="en", to_lang="uk"):
    return translate_client.translate_text(Text=text, SourceLanguageCode=from_lang, TargetLanguageCode=to_lang)[
        "TranslatedText"
    ].capitalize()
