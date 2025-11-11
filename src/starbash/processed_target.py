from typing import Any


class ProcessedTarget:
    """The repo file based config for a single processed target.

    The backing store for this class is a .toml file located in the output directory
    for the processed target.
    """

    pass

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = context
        self._dir = context["output"]["base_path"]
        # if starbash.toml does not exist in self._dir create it from template
        # else create a Repo instance based on it

    def _init_from_template(self) -> None:
        """Create a default starbash.toml file ."""
        # use toml_from_template() and self._context to create a default starbash.toml
        pass

    def _update_from_context(self) -> None:
        """Update the repo toml based on the current context."""
        pass  # placeholder don't implement yet
