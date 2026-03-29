class Item:
    def __init__(self, id: int, name: str) -> None:
        self.id = id
        self.name = name

    def __repr__(self) -> str:
        return f"Item(id={self.id}, name={self.name!r})"


class ItemList:
    def __init__(self) -> None:
        self.items: list[Item] = []

    def add(self, item: Item) -> None:
        self.items.append(item)
