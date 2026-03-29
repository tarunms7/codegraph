from .circular_a import process_a  # noqa: F401


def process_b(data: str) -> str:
    return data + "_b"


class CircularB:
    name: str = "b"
