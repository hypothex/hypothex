"""Exception hierarchy for Hypothex."""


class HypothexError(Exception):
    """Base class for all expected Hypothex errors."""


class ConfigError(HypothexError):
    """``hypothex.yaml`` is missing or invalid."""


class TemplateError(ConfigError):
    """A command template cannot be rendered."""


class RemoteProjectError(ConfigError):
    """
    A project the hub copied from a host has no checkout here.

    Its ``ProjectEntry.repo`` is the path the host reported, on that host, so
    no ``hypothex.yaml``, metric code, stage command, or git command is ever
    read or run from it here (``Context.local_repo``).
    """


class StoreError(HypothexError):
    """The file store is inconsistent or an entry is missing."""


class RunNotFoundError(StoreError):
    """No run with the given id exists."""


class RunError(HypothexError):
    """A run cannot be created, started, or controlled."""


class EvalError(HypothexError):
    """Evaluation of a run failed."""


class NoPredictionsError(EvalError):
    """The run has no ``predictions/predictions.jsonl`` file."""


class GitError(HypothexError):
    """A git operation failed."""
