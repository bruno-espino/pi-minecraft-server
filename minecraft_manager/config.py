"""Runtime settings, read from the environment (the installer's .env file)."""

from dataclasses import dataclass
import os

SERVICE = "minecraft"


def _flag(value):
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    rcon_password: str
    rcon_port: int = 25575
    minecraft_port: int = 25565
    minecraft_version: str = "unknown"
    server_type: str = "paper"
    server_address: str = ""
    discord_token: str = ""
    notification_channel_id: int | None = None
    idle_timeout_minutes: int = 30
    check_interval_seconds: int = 60
    auto_shutdown: bool = True

    @property
    def server_label(self):
        return f"Minecraft {self.minecraft_version} ({self.server_type.capitalize()})"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        password = env.get("RCON_PASSWORD", "")
        if not password:
            raise SystemExit("RCON_PASSWORD is not set; run ./install.sh")
        channel = env.get("NOTIFICATION_CHANNEL_ID", "").strip()
        return cls(
            rcon_password=password,
            rcon_port=int(env.get("RCON_PORT", 25575)),
            minecraft_port=int(env.get("MINECRAFT_PORT", 25565)),
            minecraft_version=env.get("MINECRAFT_VERSION", "unknown"),
            server_type=env.get("SERVER_TYPE", "paper"),
            server_address=env.get("SERVER_ADDRESS", "").strip(),
            discord_token=env.get("DISCORD_TOKEN", "").strip(),
            notification_channel_id=int(channel) if channel else None,
            idle_timeout_minutes=int(env.get("IDLE_TIMEOUT_MINUTES", 30)),
            check_interval_seconds=int(env.get("CHECK_INTERVAL_SECONDS", 60)),
            auto_shutdown=_flag(env.get("AUTO_SHUTDOWN", "true")),
        )
