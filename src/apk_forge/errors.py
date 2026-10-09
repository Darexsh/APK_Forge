class ForgeError(Exception):
    """Base error for expected APK Forge failures."""


class ConfigError(ForgeError):
    """Raised when apps.json is invalid."""


class SourceApkError(ForgeError):
    """Raised when a configured source APK cannot be used."""
