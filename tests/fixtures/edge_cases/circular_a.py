from .circular_b import process_b


def process_a(data: str) -> str:
    return process_b(data) + "_a"


class CircularA:
    name: str = "a"
