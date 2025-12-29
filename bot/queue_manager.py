import collections

class QueueManager:
    """Manages per-guild music queues with FIFO behavior."""
    def __init__(self):
        self._queues = collections.defaultdict(list)
        self._history = collections.defaultdict(list)

    def get_queue(self, guild_id: int):
        return self._queues[guild_id]

    def add_to_queue(self, guild_id: int, item: dict):
        """adds a song to the guild's queue."""
        if len(self._queues[guild_id]) < 500: # Limit check from config
            self._queues[guild_id].append(item)
            return True
        return False

    def get_next(self, guild_id: int):
        """Pops and returns the next song in queue."""
        if self._queues[guild_id]:
            song = self._queues[guild_id].pop(0)
            self.add_to_history(guild_id, song)
            return song
        return None

    def add_to_history(self, guild_id: int, item: dict):
        self._history[guild_id].insert(0, item)
        if len(self._history[guild_id]) > 100:
            self._history[guild_id].pop()

    def get_history(self, guild_id: int):
        return self._history[guild_id]

    def clear(self, guild_id: int):
        self._queues[guild_id].clear()

    def move(self, guild_id: int, from_idx: int, to_idx: int):
        try:
            item = self._queues[guild_id].pop(from_idx)
            self._queues[guild_id].insert(to_idx, item)
            return True
        except IndexError:
            return False

    def remove(self, guild_id: int, index: int):
        try:
            return self._queues[guild_id].pop(index)
        except IndexError:
            return None
