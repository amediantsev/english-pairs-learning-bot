def sort_pairs_by_priority(translation_pairs):
    return sorted(translation_pairs, key=lambda x: x.get("polls_count", 0))
