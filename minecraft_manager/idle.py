"""Idle-shutdown decision logic, kept free of I/O so it can be tested."""


class IdleTracker:
    """Decides when an empty server has been idle long enough to stop.

    Times come from time.monotonic(), so wall-clock jumps (a Pi without an RTC
    battery syncing NTP after boot) cannot trigger an early shutdown.
    """

    def __init__(self, timeout_seconds):
        self.timeout_seconds = timeout_seconds
        self.idle_since = None

    def observe(self, running, player_count, now):
        """Record one check. player_count is None when RCON is not answering.

        Returns True when the server should be stopped.
        """
        if not running:
            self.idle_since = None
            return False
        if self.idle_since is None or (player_count or 0) > 0:
            # Just started, or someone is playing: restart the idle window.
            self.idle_since = now
        if player_count != 0:
            # Only a confirmed empty server counts towards shutdown.
            return False
        return now - self.idle_since >= self.timeout_seconds

    def idle_seconds(self, now):
        return 0 if self.idle_since is None else now - self.idle_since

    def reset(self):
        self.idle_since = None
