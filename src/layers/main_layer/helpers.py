def sort_pairs_by_priority(translation_pairs):
    return sorted(translation_pairs, key=lambda x: x.get("polls_count", 0))


def get_polling_rule_name(user_chat_id):
    return f"{user_chat_id}_POLLING"
